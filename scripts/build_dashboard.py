"""Builds docs/index.html — a vibrant static dashboard deployed to GitHub Pages.

The page is self-contained (no build step). The actual document scans are an
optional overlay: if a DOC_API_URL (an Apps Script web app) is configured, the
page fetches a file map at view time and shows download buttons, plus lets you
upload a scan straight from the browser.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

from core import (
    Item,
    build_items,
    load_config,
    missing_required,
    owner_group,
    required_docs_for,
)


# Vibrant, semantic status palette (overdue → far).
URGENCY_META = {
    "overdue":  {"label": "Overdue",   "color": "#e11d48", "rank": 0},
    "critical": {"label": "Urgent",    "color": "#f97316", "rank": 1},
    "warning":  {"label": "Upcoming",  "color": "#eab308", "rank": 2},
    "ok":       {"label": "Scheduled", "color": "#22c55e", "rank": 3},
    "far":      {"label": "Later",     "color": "#64748b", "rank": 4},
}

# Each document type gets its own colour so the page reads at a glance.
DOC_COLORS = {
    "Insurance":        "#2563eb",
    "PUC":              "#16a34a",
    "Fitness":          "#9333ea",
    "Permit":           "#db2777",
    "Registration (RC)":"#0891b2",
    "Road Tax":         "#d97706",
    "General Service":  "#475569",
}
DEFAULT_DOC_COLOR = "#475569"


def _fmt_days(days: int) -> str:
    if days < 0:
        return f"{abs(days)}d overdue"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days}d"


def _item_to_json(i: Item) -> dict:
    return {
        "key": f"{i.vehicle_id}|{i.type}",
        "vehicle_id": i.vehicle_id,
        "vehicle_name": i.vehicle_name,
        "category": i.category,
        "type": i.type,
        "type_color": DOC_COLORS.get(i.type, DEFAULT_DOC_COLOR),
        "expiry_date": i.expiry_date.isoformat(),
        "expiry_display": i.expiry_date.strftime("%d %b %Y"),
        "days_left": i.days_left,
        "days_display": _fmt_days(i.days_left),
        "urgency": i.urgency,
        "urgency_label": URGENCY_META[i.urgency]["label"],
        "urgency_color": URGENCY_META[i.urgency]["color"],
        "provider": i.provider,
        "amount": i.amount,
        "file_link": i.file_link,
        "extra": i.extra,
    }


def _vehicle_issues(vehicle: dict, v_items: list[Item]) -> list[dict]:
    """Automated data-quality review of one vehicle's record. Each issue is
    {level: error|warn|info, text}. Mirrors the manual review so the flags stay
    visible on the dashboard instead of living only in a chat."""
    issues: list[dict] = []
    reg = (vehicle.get("registration_number") or "").strip()
    owner = (vehicle.get("owner") or "").strip()
    name = (vehicle.get("name") or "").strip()
    note = (vehicle.get("notes") or "").strip()
    docs = [i for i in v_items if i.category == "document"]

    if not reg or re.search(r"x{2,}", reg, re.I):
        issues.append({"level": "error", "text": "Registration looks like a placeholder — needs the real number"})
    if not docs:
        issues.append({"level": "error", "text": "No documents on record at all"})
    if not owner or "tbd" in owner.lower() or "[" in owner:
        issues.append({"level": "warn", "text": "Owner not finalised"})
    if any(i.urgency == "overdue" for i in v_items) and re.search(r"soon|expiring", note, re.I):
        issues.append({"level": "warn", "text": 'Note says "expiring soon" but a paper is already overdue — note is stale'})
    if re.match(r"^(motor car|commercial vehicle|vehicle)\b", name, re.I) or name.lower() == "school bus":
        issues.append({"level": "info", "text": "Generic name — replace with the actual make/model"})
    ins = [i for i in docs if i.type == "Insurance"]
    if ins and all(i.amount is None for i in ins):
        issues.append({"level": "info", "text": "Insurance premium amount missing"})
    return issues


def build_dashboard(output_path: str | Path = "docs/index.html") -> None:
    config = load_config()
    items = build_items(config)
    vehicles = config.get("vehicles", [])

    # ---------- Vehicle cards (with compliance) ---------- #
    vehicles_data = []
    missing_report = []
    review_report = []
    missing_required_total = 0
    issues_total = 0
    for v in vehicles:
        v_items = [i for i in items if i.vehicle_id == v["id"]]
        present_types = {i.type for i in v_items if i.category == "document"}
        required = required_docs_for(v.get("type", ""))
        missing = missing_required(present_types, v.get("type", ""))
        missing_required_total += len(missing)
        present_required = [d for d in required if d in present_types]
        compliance_pct = round(100 * len(present_required) / len(required)) if required else 100
        grp = owner_group(v.get("owner", ""))
        issues = _vehicle_issues(v, v_items)
        issues_total += len(issues)
        vehicles_data.append({
            "issues": issues,
            "id": v["id"],
            "name": v["name"],
            "registration_number": v.get("registration_number", ""),
            "type": v.get("type", ""),
            "owner": v.get("owner", ""),
            "owner_group": grp,
            "notes": v.get("notes", ""),
            "items": [_item_to_json(i) for i in v_items],
            "required": required,
            "present_types": sorted(present_types),
            "missing": missing,
            "compliance_pct": compliance_pct,
            "worst_urgency_rank": min(
                (URGENCY_META[i.urgency]["rank"] for i in v_items),
                default=4,
            ),
        })
        if missing:
            missing_report.append({
                "vehicle_name": v["name"],
                "registration_number": v.get("registration_number", ""),
                "owner_group": grp,
                "vehicle_type": v.get("type", ""),
                "missing": missing,
            })
        if issues:
            review_report.append({
                "vehicle_name": v["name"],
                "registration_number": v.get("registration_number", ""),
                "owner_group": grp,
                "issues": issues,
            })

    # ---------- Stats ---------- #
    stats = {
        "vehicles": len(vehicles),
        "total_items": len(items),
        "overdue": sum(1 for i in items if i.urgency == "overdue"),
        "critical": sum(1 for i in items if i.urgency == "critical"),
        "warning": sum(1 for i in items if i.urgency == "warning"),
        "ok": sum(1 for i in items if i.urgency in ("ok", "far")),
        "missing_required": missing_required_total,
        "annual_spend": sum(
            (i.amount or 0) for i in items
            if i.category == "document" and i.amount
        ),
    }

    status_counts = {k: sum(1 for i in items if i.urgency == k)
                     for k in ("overdue", "critical", "warning", "ok", "far")}

    # ---------- Timeline (next 12 months) ---------- #
    timeline = [_item_to_json(i) for i in items if 0 <= i.days_left <= 365]

    # ---------- Spend by type ---------- #
    spend_by_type: dict[str, float] = {}
    for i in items:
        if i.amount:
            spend_by_type[i.type] = spend_by_type.get(i.type, 0) + i.amount

    payload = {
        "generated_at": date.today().isoformat(),
        "generated_display": date.today().strftime("%A, %d %B %Y"),
        "doc_api_url": os.environ.get("DOC_API_URL", "").strip(),
        "doc_api_token": os.environ.get("DOC_API_TOKEN", "").strip(),
        "doc_colors": DOC_COLORS,
        "stats": stats,
        "status_counts": status_counts,
        "timeline": timeline,
        "spend_by_type": spend_by_type,
        "vehicles": vehicles_data,
        "missing_report": missing_report,
        "review_report": review_report,
        "issues_total": issues_total,
        "all_items": [_item_to_json(i) for i in items],
    }

    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(payload, indent=2))
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    print(f"✅ Dashboard built at {output_path} ({len(vehicles)} vehicles, {len(items)} items)")


# =========================================================================== #
# HTML template — vibrant, single-file, no build step
# =========================================================================== #

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>The Garage — Fleet Papers</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0b1020;
    --bg-2: #11172e;
    --card: #161d38;
    --card-2: #1b2342;
    --ink: #f3f5ff;
    --ink-soft: #c2c8e6;
    --ink-muted: #8390bd;
    --line: #28315a;
    --brand-1: #6366f1;   /* indigo */
    --brand-2: #ec4899;   /* pink   */
    --brand-3: #06b6d4;   /* cyan   */
    --good: #22c55e;
    --warn: #eab308;
    --bad: #e11d48;
    --shadow: 0 1px 2px rgba(0,0,0,.4), 0 18px 40px -12px rgba(0,0,0,.55);
    --grad-hero: linear-gradient(115deg,#6366f1 0%,#a855f7 38%,#ec4899 70%,#f97316 100%);
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    background:
      radial-gradient(1200px 600px at 12% -8%, rgba(99,102,241,.22), transparent 60%),
      radial-gradient(1000px 500px at 100% 0%, rgba(236,72,153,.16), transparent 55%),
      var(--bg);
    color: var(--ink);
    font-family: "Inter", -apple-system, system-ui, sans-serif;
    font-size: 15px; line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }
  a { color: inherit; }
  .wrap { max-width: 1320px; margin: 0 auto; padding: 32px 28px 90px; }
  @media (max-width: 640px) { .wrap { padding: 20px 16px 64px; } }

  /* Hero ---------------------------------------------------------------- */
  .hero {
    position: relative; overflow: hidden;
    border-radius: 22px; padding: 34px 34px 30px;
    background: var(--grad-hero);
    box-shadow: var(--shadow);
    margin-bottom: 26px;
  }
  .hero::after {
    content:""; position:absolute; inset:0;
    background: radial-gradient(600px 300px at 85% 120%, rgba(255,255,255,.25), transparent 60%);
    pointer-events:none;
  }
  .hero-top { display:flex; justify-content:space-between; align-items:flex-start; gap:18px; flex-wrap:wrap; position:relative; z-index:1; }
  .hero .eyebrow {
    font-family:"JetBrains Mono",monospace; font-size:11px; letter-spacing:.22em;
    text-transform:uppercase; color:rgba(255,255,255,.85); margin-bottom:8px;
  }
  .hero h1 {
    font-family:"Space Grotesk",sans-serif; font-weight:700;
    font-size: clamp(34px, 6vw, 58px); line-height:.98; letter-spacing:-.02em;
    margin:0; color:#fff; text-shadow:0 2px 20px rgba(0,0,0,.18);
  }
  .hero .date { font-family:"JetBrains Mono",monospace; font-size:13px; color:#fff; text-align:right; }
  .hero .date small { display:block; color:rgba(255,255,255,.8); font-size:11px; letter-spacing:.1em; text-transform:uppercase; margin-top:4px; }

  /* Toolbar ------------------------------------------------------------- */
  .toolbar { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:22px; position:relative; z-index:1; }
  .search {
    flex:1 1 280px; display:flex; align-items:center; gap:8px;
    background:rgba(255,255,255,.16); border:1px solid rgba(255,255,255,.28);
    border-radius:12px; padding:10px 14px; backdrop-filter: blur(6px);
  }
  .search input { flex:1; background:transparent; border:none; outline:none; color:#fff; font-size:14px; }
  .search input::placeholder { color:rgba(255,255,255,.75); }
  .btn {
    border:1px solid rgba(255,255,255,.32); background:rgba(255,255,255,.16);
    color:#fff; border-radius:12px; padding:10px 16px; font-size:13px; font-weight:600;
    cursor:pointer; display:inline-flex; align-items:center; gap:7px; backdrop-filter: blur(6px);
    transition: transform .12s ease, background .15s;
  }
  .btn:hover { background:rgba(255,255,255,.28); transform:translateY(-1px); }

  /* KPI strip ----------------------------------------------------------- */
  .kpis { display:grid; grid-template-columns:repeat(7,1fr); gap:12px; margin-bottom:28px; }
  @media (max-width:1100px){ .kpis{ grid-template-columns:repeat(4,1fr);} }
  @media (max-width:640px){ .kpis{ grid-template-columns:repeat(2,1fr);} }
  .kpi {
    background:var(--card); border:1px solid var(--line); border-radius:16px;
    padding:16px 16px 15px; position:relative; overflow:hidden; box-shadow:var(--shadow);
  }
  .kpi::before { content:""; position:absolute; left:0; top:0; height:100%; width:4px; background:var(--accent,#6366f1); }
  .kpi .k-label { font-family:"JetBrains Mono",monospace; font-size:10px; letter-spacing:.13em; text-transform:uppercase; color:var(--ink-muted); margin-bottom:8px; }
  .kpi .k-value { font-family:"Space Grotesk",sans-serif; font-size:30px; font-weight:700; line-height:1; }
  .kpi .k-sub { font-size:11px; color:var(--ink-muted); margin-top:6px; }

  /* Banner -------------------------------------------------------------- */
  .banner {
    border-radius:16px; padding:18px 22px; margin-bottom:26px; color:#fff;
    background:linear-gradient(100deg,#e11d48,#f97316); box-shadow:var(--shadow);
    display:flex; gap:18px; align-items:center; justify-content:space-between; flex-wrap:wrap;
  }
  .banner h3 { margin:0 0 2px; font-family:"Space Grotesk",sans-serif; font-size:18px; }
  .banner .b-list { font-size:13.5px; opacity:.95; }
  .banner .b-list b { font-weight:700; }

  /* Sections ------------------------------------------------------------ */
  .section { margin-bottom:34px; }
  .section-head { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:16px; gap:12px; flex-wrap:wrap; }
  .section-head h2 { font-family:"Space Grotesk",sans-serif; font-weight:600; font-size:22px; margin:0; letter-spacing:-.01em; }
  .section-head .meta { font-family:"JetBrains Mono",monospace; font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:var(--ink-muted); }

  /* Charts -------------------------------------------------------------- */
  .charts { display:grid; grid-template-columns:1.5fr 1fr 1fr; gap:16px; }
  @media (max-width:980px){ .charts{ grid-template-columns:1fr;} }
  .chart-card { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:18px 18px 14px; box-shadow:var(--shadow); }
  .chart-card h3 { font-family:"Space Grotesk",sans-serif; font-size:15px; margin:0 0 2px; }
  .chart-card .sub { font-family:"JetBrains Mono",monospace; font-size:10px; letter-spacing:.12em; text-transform:uppercase; color:var(--ink-muted); margin-bottom:14px; }
  .chart-wrap { height:240px; position:relative; }

  /* Compliance gaps ----------------------------------------------------- */
  .gaps-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:14px; }
  .gap-card { background:var(--card); border:1px solid var(--line); border-left:4px solid var(--bad); border-radius:14px; padding:16px 18px; box-shadow:var(--shadow); }
  .gap-card .g-name { font-weight:600; }
  .gap-card .g-reg { font-family:"JetBrains Mono",monospace; font-size:12px; color:var(--ink-muted); margin:2px 0 10px; }
  .issue-card { border-left-color:var(--warn); }
  .issue-line { display:flex; gap:8px; align-items:flex-start; font-size:13px; padding:5px 0; }
  .issue-dot { width:8px; height:8px; border-radius:50%; flex:none; margin-top:6px; }
  .lvl-error { background:var(--bad); } .lvl-warn { background:var(--warn); } .lvl-info { background:var(--brand-3); }
  .issue-badges { margin-top:10px; display:flex; flex-wrap:wrap; gap:6px; }
  .issue-badge { font-size:10.5px; padding:3px 8px; border-radius:999px; border:1px solid var(--line); color:var(--ink-soft); display:inline-flex; gap:5px; align-items:center; }

  /* Fleet filter pills -------------------------------------------------- */
  .fleet-tabs, .tabs { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:18px; }
  .pill-btn {
    font-family:"JetBrains Mono",monospace; font-size:11px; letter-spacing:.08em; text-transform:uppercase;
    padding:8px 14px; border-radius:999px; border:1px solid var(--line); background:var(--card);
    color:var(--ink-soft); cursor:pointer; transition:all .15s;
  }
  .pill-btn:hover { border-color:var(--brand-1); color:#fff; }
  .pill-btn.active { background:linear-gradient(100deg,var(--brand-1),var(--brand-2)); color:#fff; border-color:transparent; }

  /* Vehicle cards ------------------------------------------------------- */
  .fleet-group { margin-bottom:30px; }
  .fleet-group h3.fleet-title { font-family:"Space Grotesk",sans-serif; font-size:16px; margin:0 0 14px; display:flex; align-items:center; gap:10px; }
  .fleet-title .dot { width:10px; height:10px; border-radius:50%; }
  .vehicles-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(330px,1fr)); gap:16px; }
  .vehicle-card { background:var(--card); border:1px solid var(--line); border-radius:18px; padding:20px; box-shadow:var(--shadow); position:relative; transition:transform .15s ease, border-color .15s; }
  .vehicle-card:hover { transform:translateY(-3px); border-color:var(--brand-1); }
  .vehicle-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }
  .vehicle-name { font-family:"Space Grotesk",sans-serif; font-weight:600; font-size:18px; line-height:1.2; }
  .vehicle-reg { font-family:"JetBrains Mono",monospace; font-size:12px; color:var(--ink-muted); margin:3px 0 0; letter-spacing:.04em; }
  .vehicle-type-chip { font-family:"JetBrains Mono",monospace; font-size:9.5px; letter-spacing:.1em; text-transform:uppercase; color:var(--ink-soft); border:1px solid var(--line); border-radius:999px; padding:4px 9px; white-space:nowrap; }

  /* Compliance ring */
  .ring { --pct:0; width:46px; height:46px; border-radius:50%; flex:none;
    background: conic-gradient(var(--ring-c) calc(var(--pct)*1%), rgba(255,255,255,.08) 0);
    display:grid; place-items:center; position:relative; }
  .ring::after { content:""; position:absolute; inset:5px; background:var(--card); border-radius:50%; }
  .ring span { position:relative; z-index:1; font-family:"JetBrains Mono",monospace; font-size:11px; font-weight:600; }

  .veh-note { font-size:12px; color:var(--ink-muted); margin:12px 0 0; font-style:italic; }
  .missing-row { margin-top:12px; display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
  .missing-label { font-size:11px; color:var(--bad); font-weight:600; text-transform:uppercase; letter-spacing:.06em; }

  .doc-list { list-style:none; padding:0; margin:14px 0 0; }
  .doc-item { display:grid; grid-template-columns:1fr auto; gap:8px 12px; padding:11px 0; border-top:1px solid var(--line); align-items:center; }
  .doc-item:first-child { border-top:none; }
  .doc-left { display:flex; flex-direction:column; gap:4px; min-width:0; }
  .doc-type { display:inline-flex; align-items:center; gap:7px; font-weight:600; font-size:13.5px; }
  .doc-type .swatch { width:9px; height:9px; border-radius:3px; flex:none; }
  .doc-exp { font-family:"JetBrains Mono",monospace; font-size:11px; color:var(--ink-muted); }
  .doc-right { display:flex; align-items:center; gap:8px; }
  .status-pill { font-family:"JetBrains Mono",monospace; font-size:10px; letter-spacing:.06em; text-transform:uppercase; padding:4px 9px; border-radius:999px; font-weight:600; color:#fff; white-space:nowrap; }
  .file-btn {
    border:1px solid var(--line); background:var(--card-2); color:var(--ink-soft);
    border-radius:9px; padding:5px 10px; font-size:11px; font-weight:600; cursor:pointer;
    display:inline-flex; align-items:center; gap:5px; white-space:nowrap; transition:all .14s;
  }
  .file-btn:hover { border-color:var(--brand-3); color:#fff; }
  .file-btn.has-file { border-color:var(--good); color:#bbf7d0; }
  .file-btn.uploading { opacity:.6; pointer-events:none; }
  .file-btn.disabled { opacity:.5; cursor:not-allowed; }

  /* Table --------------------------------------------------------------- */
  .table-wrap { overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:16px; box-shadow:var(--shadow); }
  table.tbl { width:100%; border-collapse:collapse; font-size:13.5px; min-width:760px; }
  table.tbl thead { background:linear-gradient(100deg,var(--brand-1),var(--brand-2)); }
  table.tbl th { text-align:left; padding:13px 16px; font-family:"JetBrains Mono",monospace; font-size:10px; letter-spacing:.13em; text-transform:uppercase; color:#fff; font-weight:600; }
  table.tbl td { padding:12px 16px; border-top:1px solid var(--line); vertical-align:middle; }
  table.tbl tr:hover td { background:rgba(99,102,241,.08); }
  .td-veh { font-weight:600; }
  .td-mono { font-family:"JetBrains Mono",monospace; font-size:12px; color:var(--ink-muted); }

  footer { margin-top:50px; padding-top:22px; border-top:1px solid var(--line); font-family:"JetBrains Mono",monospace; font-size:11px; color:var(--ink-muted); display:flex; justify-content:space-between; flex-wrap:wrap; gap:10px; }

  .empty { text-align:center; padding:40px; color:var(--ink-muted); }
  .hidden { display:none !important; }

  /* Print --------------------------------------------------------------- */
  @media print {
    body { background:#fff; color:#000; }
    .toolbar, .file-btn, .fleet-tabs, .tabs, .btn, .search { display:none !important; }
    .hero { background:#222 !important; -webkit-print-color-adjust:exact; print-color-adjust:exact; }
    .kpi, .vehicle-card, .chart-card, .gap-card, .table-wrap { box-shadow:none; border:1px solid #ccc; }
    .vehicle-card { break-inside:avoid; }
  }

  .fade-in { animation: fadeIn .5s ease both; }
  @keyframes fadeIn { from{opacity:0; transform:translateY(10px);} to{opacity:1; transform:none;} }
</style>
</head>
<body>
<div class="wrap">

  <!-- Hero -->
  <header class="hero fade-in">
    <div class="hero-top">
      <div>
        <div class="eyebrow">Personal &amp; Business Fleet Register</div>
        <h1>The Garage</h1>
      </div>
      <div class="date">
        <div id="today"></div>
        <small>Auto-refreshed daily</small>
      </div>
    </div>
    <div class="toolbar">
      <div class="search">
        <span>🔎</span>
        <input id="search" type="search" placeholder="Search vehicle, registration, document…" autocomplete="off" />
      </div>
      <button class="btn" id="btn-ics" title="Download a calendar of every renewal">📅 Renewal calendar</button>
      <button class="btn" id="btn-print" title="Print or save as PDF">🖨️ Print</button>
    </div>
  </header>

  <!-- KPIs -->
  <div class="kpis fade-in" id="kpis"></div>

  <!-- Action banner -->
  <div id="banner-slot"></div>

  <!-- Charts -->
  <div class="section fade-in">
    <div class="section-head"><h2>At a glance</h2><div class="meta">Live snapshot</div></div>
    <div class="charts">
      <div class="chart-card"><h3>Expiry timeline</h3><div class="sub">Renewals due each month · next 12 months</div><div class="chart-wrap"><canvas id="c-timeline"></canvas></div></div>
      <div class="chart-card"><h3>Status mix</h3><div class="sub">All tracked papers</div><div class="chart-wrap"><canvas id="c-status"></canvas></div></div>
      <div class="chart-card"><h3>Annual spend</h3><div class="sub">By document type</div><div class="chart-wrap"><canvas id="c-spend"></canvas></div></div>
    </div>
  </div>

  <!-- Compliance gaps -->
  <div class="section fade-in" id="gaps-section">
    <div class="section-head"><h2>Compliance gaps</h2><div class="meta" id="gaps-meta"></div></div>
    <div class="gaps-grid" id="gaps-grid"></div>
  </div>

  <!-- Data review (automated record check) -->
  <div class="section fade-in" id="review-section">
    <div class="section-head"><h2>Data review</h2><div class="meta" id="review-meta"></div></div>
    <div class="gaps-grid" id="review-grid"></div>
  </div>

  <!-- Fleets -->
  <div class="section">
    <div class="section-head"><h2>The fleet</h2><div class="meta" id="fleet-count"></div></div>
    <div class="fleet-tabs" id="fleet-tabs"></div>
    <div id="fleets"></div>
  </div>

  <!-- Everything table -->
  <div class="section">
    <div class="section-head"><h2>Every paper, sorted</h2><div class="meta">Filter &amp; export</div></div>
    <div class="tabs" id="status-tabs">
      <button class="pill-btn active" data-filter="all">All</button>
      <button class="pill-btn" data-filter="overdue">Overdue</button>
      <button class="pill-btn" data-filter="critical">Urgent</button>
      <button class="pill-btn" data-filter="warning">Upcoming</button>
      <button class="pill-btn" data-filter="document">Documents</button>
      <button class="pill-btn" data-filter="service">Services</button>
    </div>
    <div class="table-wrap">
      <table class="tbl">
        <thead><tr>
          <th>Vehicle</th><th>Document</th><th>Fleet</th>
          <th>Expires</th><th>When</th><th>Amount</th><th>Status</th><th>File</th>
        </tr></thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
  </div>

  <footer>
    <div>Built from your fleet sheet · Deployed via GitHub Pages</div>
    <div id="generated-at"></div>
  </footer>
</div>

<!-- hidden file input reused for all uploads -->
<input type="file" id="file-input" class="hidden" accept="image/*,application/pdf" />

<script>
const DATA = __DATA__;
const FLEET_DOTS = { "GJMS School":"#6366f1", "G.B. Automobiles":"#06b6d4", "Family & Personal":"#ec4899" };

// File map: key "vehicleId|DocType" -> {url, name}. Seeded from any sheet links.
const fileMap = {};
DATA.all_items.forEach(i => { if (i.file_link) fileMap[i.key] = { url:i.file_link, name:"document" }; });

document.getElementById('today').textContent = DATA.generated_display;
document.getElementById('generated-at').textContent = 'Generated ' + DATA.generated_at;

/* ---------- KPIs ---------- */
function formatINR(n){
  n=Number(n)||0;
  if(n>=1e7) return '₹'+(n/1e7).toFixed(2).replace(/\.00$/,'')+' Cr';
  if(n>=1e5) return '₹'+(n/1e5).toFixed(2).replace(/\.00$/,'')+' L';
  return '₹'+n.toLocaleString('en-IN');
}
(function(){
  const s = DATA.stats;
  const cards = [
    { label:'Vehicles', value:s.vehicles, accent:'#6366f1' },
    { label:'Papers', value:s.total_items, accent:'#06b6d4' },
    { label:'Overdue', value:s.overdue, accent:'#e11d48', alert:s.overdue>0 },
    { label:'Urgent ≤7d', value:s.critical, accent:'#f97316', alert:s.critical>0 },
    { label:'Upcoming ≤30d', value:s.warning, accent:'#eab308' },
    { label:'Missing papers', value:s.missing_required, accent:'#db2777', alert:s.missing_required>0, sub:'legally required' },
    { label:'Annual ₹', value:formatINR(s.annual_spend), accent:'#22c55e', sub:'recurring' },
  ];
  document.getElementById('kpis').innerHTML = cards.map(c => `
    <div class="kpi" style="--accent:${c.accent}">
      <div class="k-label">${c.label}</div>
      <div class="k-value" style="${c.alert?`color:${c.accent}`:''}">${c.value}</div>
      ${c.sub?`<div class="k-sub">${c.sub}</div>`:''}
    </div>`).join('');
})();

/* ---------- Action banner ---------- */
(function(){
  const urgent = DATA.all_items.filter(i => i.urgency==='overdue' || i.urgency==='critical')
                               .sort((a,b)=>a.days_left-b.days_left);
  if (!urgent.length) return;
  const lines = urgent.slice(0,6).map(i =>
    `<b>${i.vehicle_name}</b> — ${i.type} <span style="opacity:.9">(${i.days_display})</span>`).join(' &nbsp;·&nbsp; ');
  document.getElementById('banner-slot').innerHTML = `
    <div class="banner fade-in">
      <div>
        <h3>⚠️ ${urgent.length} paper${urgent.length>1?'s':''} need action now</h3>
        <div class="b-list">${lines}</div>
      </div>
    </div>`;
})();

/* ---------- Charts ---------- */
(function(){
  const months=[]; const now=new Date();
  for(let i=0;i<12;i++){ const d=new Date(now.getFullYear(),now.getMonth()+i,1);
    months.push({key:d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0'),
      label:d.toLocaleString('en-GB',{month:'short',year:'2-digit'}),count:0}); }
  DATA.timeline.forEach(it=>{ const m=months.find(x=>x.key===it.expiry_date.substring(0,7)); if(m)m.count++; });
  new Chart(document.getElementById('c-timeline'),{type:'bar',
    data:{labels:months.map(m=>m.label),datasets:[{data:months.map(m=>m.count),
      backgroundColor:months.map(m=>m.count>2?'#ec4899':m.count>0?'#6366f1':'#28315a'),borderRadius:6,borderSkipped:false}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},
      tooltip:{callbacks:{label:c=>c.parsed.y+' renewal(s)'}}},
      scales:{x:{grid:{display:false},ticks:{color:'#8390bd',font:{family:'JetBrains Mono',size:10}}},
        y:{beginAtZero:true,ticks:{stepSize:1,color:'#8390bd',font:{family:'JetBrains Mono',size:10}},grid:{color:'rgba(255,255,255,.06)'}}}}});

  const sc=DATA.status_counts; const SC=[['Overdue',sc.overdue,'#e11d48'],['Urgent',sc.critical,'#f97316'],
    ['Upcoming',sc.warning,'#eab308'],['Scheduled',sc.ok,'#22c55e'],['Later',sc.far,'#64748b']].filter(x=>x[1]>0);
  new Chart(document.getElementById('c-status'),{type:'doughnut',
    data:{labels:SC.map(x=>x[0]),datasets:[{data:SC.map(x=>x[1]),backgroundColor:SC.map(x=>x[2]),borderColor:'#161d38',borderWidth:3}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'60%',
      plugins:{legend:{position:'bottom',labels:{color:'#c2c8e6',font:{family:'Inter',size:11},boxWidth:10,padding:10}}}}});

  const sp=Object.entries(DATA.spend_by_type).sort((a,b)=>b[1]-a[1]);
  if(!sp.length){ document.getElementById('c-spend').parentElement.innerHTML='<div class="empty">No amounts recorded yet</div>'; }
  else { new Chart(document.getElementById('c-spend'),{type:'doughnut',
    data:{labels:sp.map(e=>e[0]),datasets:[{data:sp.map(e=>e[1]),
      backgroundColor:sp.map(e=>DATA.doc_colors[e[0]]||'#475569'),borderColor:'#161d38',borderWidth:3}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'60%',
      plugins:{legend:{position:'bottom',labels:{color:'#c2c8e6',font:{family:'Inter',size:11},boxWidth:10,padding:10}},
        tooltip:{callbacks:{label:c=>c.label+': ₹'+c.parsed.toLocaleString('en-IN')}}}}}); }
})();

/* ---------- Compliance gaps ---------- */
(function(){
  const g=DATA.missing_report;
  document.getElementById('gaps-meta').textContent = g.length ? g.length+' vehicle(s) with gaps' : 'all clear';
  if(!g.length){ document.getElementById('gaps-grid').innerHTML='<div class="empty">🎉 Every vehicle has all its legally-required papers on record.</div>'; return; }
  document.getElementById('gaps-grid').innerHTML = g.map(v=>`
    <div class="gap-card">
      <div class="g-name">${v.vehicle_name}</div>
      <div class="g-reg">${v.registration_number||'—'} · ${v.owner_group}</div>
      <div class="missing-row">
        <span class="missing-label">Missing</span>
        ${v.missing.map(m=>`<span class="status-pill" style="background:${DATA.doc_colors[m]||'#db2777'}">${m}</span>`).join('')}
      </div>
    </div>`).join('');
})();

/* ---------- Data review section ---------- */
(function(){
  const r=DATA.review_report||[];
  const meta=document.getElementById('review-meta');
  meta.textContent = r.length ? (DATA.issues_total+' issue(s) across '+r.length+' vehicle(s)') : 'no issues found';
  if(!r.length){ document.getElementById('review-grid').innerHTML='<div class="empty">✅ No data-quality issues detected in the records.</div>'; return; }
  document.getElementById('review-grid').innerHTML = r.map(v=>`
    <div class="gap-card issue-card">
      <div class="g-name">${v.vehicle_name}</div>
      <div class="g-reg">${v.registration_number||'—'} · ${v.owner_group}</div>
      ${v.issues.map(it=>`<div class="issue-line"><span class="issue-dot lvl-${it.level}"></span><span>${it.text}</span></div>`).join('')}
    </div>`).join('');
})();

/* ---------- File button ---------- */
function fileBtnHtml(it){
  const f = fileMap[it.key];
  if (f) return `<a class="file-btn has-file" href="${f.url}" target="_blank" rel="noopener" title="Download / view">⬇ File</a>`;
  if (!DATA.doc_api_url) return `<span class="file-btn disabled" title="Document storage not connected yet">⬆ Upload</span>`;
  return `<button class="file-btn" data-up="${it.key}" data-vid="${it.vehicle_id}" data-dtype="${it.type}" title="Upload a scan">⬆ Upload</button>`;
}

/* ---------- Fleets (grouped vehicle cards) ---------- */
let fleetFilter = 'all';
function renderFleets(){
  const q = (document.getElementById('search').value||'').toLowerCase().trim();
  const groups = {};
  DATA.vehicles.forEach(v=>{ (groups[v.owner_group]=groups[v.owner_group]||[]).push(v); });
  const order = ['GJMS School','G.B. Automobiles','Family & Personal'];
  const host = document.getElementById('fleets'); host.innerHTML='';
  let shown=0;
  order.filter(g=>groups[g]).forEach(g=>{
    if (fleetFilter!=='all' && fleetFilter!==g) return;
    let vs = groups[g];
    if (q) vs = vs.filter(v => (v.name+' '+v.registration_number+' '+v.owner+' '+v.items.map(i=>i.type).join(' ')).toLowerCase().includes(q));
    if (!vs.length) return;
    shown += vs.length;
    const cards = vs.map(v=>{
      const ringC = v.compliance_pct>=100?'#22c55e':v.compliance_pct>=50?'#eab308':'#e11d48';
      const docs = v.items.map(it=>`
        <li class="doc-item">
          <div class="doc-left">
            <span class="doc-type"><span class="swatch" style="background:${it.type_color}"></span>${it.type}${it.provider?` <span style="color:var(--ink-muted);font-weight:400;font-size:12px">· ${it.provider}</span>`:''}</span>
            <span class="doc-exp">${it.expiry_display} · ${it.days_display}${it.amount?` · ₹${Number(it.amount).toLocaleString('en-IN')}`:''}</span>
          </div>
          <div class="doc-right">
            <span class="status-pill" style="background:${it.urgency_color}">${it.urgency_label}</span>
            ${fileBtnHtml(it)}
          </div>
        </li>`).join('');
      const missing = v.missing.length ? `
        <div class="missing-row"><span class="missing-label">Missing</span>
          ${v.missing.map(m=>`<span class="status-pill" style="background:${DATA.doc_colors[m]||'#db2777'}">${m}</span>`).join('')}
        </div>` : '';
      const issues = (v.issues&&v.issues.length) ? `
        <div class="issue-badges">
          ${v.issues.map(it=>`<span class="issue-badge"><span class="issue-dot lvl-${it.level}"></span>${it.text}</span>`).join('')}
        </div>` : '';
      return `
        <div class="vehicle-card fade-in">
          <div class="vehicle-head">
            <div style="min-width:0">
              <div class="vehicle-name">${v.name}</div>
              <div class="vehicle-reg">${v.registration_number||'—'}</div>
            </div>
            <div style="display:flex;flex-direction:column;align-items:center;gap:8px">
              <div class="ring" style="--pct:${v.compliance_pct};--ring-c:${ringC}"><span>${v.compliance_pct}%</span></div>
              <span class="vehicle-type-chip">${v.type}</span>
            </div>
          </div>
          ${missing}
          ${issues}
          <ul class="doc-list">${docs || '<li class="doc-item" style="color:var(--ink-muted)">No papers on record yet.</li>'}</ul>
          ${v.notes?`<div class="veh-note">📝 ${v.notes}</div>`:''}
        </div>`;
    }).join('');
    host.insertAdjacentHTML('beforeend', `
      <div class="fleet-group">
        <h3 class="fleet-title"><span class="dot" style="background:${FLEET_DOTS[g]||'#6366f1'}"></span>${g} <span style="color:var(--ink-muted);font-weight:400">· ${vs.length}</span></h3>
        <div class="vehicles-grid">${cards}</div>
      </div>`);
  });
  if (!shown) host.innerHTML='<div class="empty">No vehicles match your search.</div>';
}

/* ---------- Fleet tabs ---------- */
(function(){
  const groups = [...new Set(DATA.vehicles.map(v=>v.owner_group))];
  const order = ['GJMS School','G.B. Automobiles','Family & Personal'].filter(g=>groups.includes(g));
  document.getElementById('fleet-count').textContent = DATA.vehicles.length+' vehicles · '+order.length+' fleets';
  const tabs = ['all',...order];
  document.getElementById('fleet-tabs').innerHTML = tabs.map((t,i)=>
    `<button class="pill-btn ${i===0?'active':''}" data-fleet="${t}">${t==='all'?'All fleets':t}</button>`).join('');
  document.querySelectorAll('#fleet-tabs .pill-btn').forEach(b=>b.addEventListener('click',()=>{
    document.querySelectorAll('#fleet-tabs .pill-btn').forEach(x=>x.classList.remove('active'));
    b.classList.add('active'); fleetFilter=b.dataset.fleet; renderFleets();
  }));
})();

/* ---------- Table ---------- */
let statusFilter='all';
function renderTable(){
  const q=(document.getElementById('search').value||'').toLowerCase().trim();
  let rows=DATA.all_items;
  if(statusFilter==='document'||statusFilter==='service') rows=rows.filter(r=>r.category===statusFilter);
  else if(statusFilter!=='all') rows=rows.filter(r=>r.urgency===statusFilter);
  if(q) rows=rows.filter(r=>(r.vehicle_name+' '+r.type+' '+(r.provider||'')).toLowerCase().includes(q));
  const tb=document.getElementById('tbody');
  if(!rows.length){ tb.innerHTML='<tr><td colspan="8" class="empty">Nothing here.</td></tr>'; return; }
  const grp = {}; DATA.vehicles.forEach(v=>grp[v.id]=v.owner_group);
  tb.innerHTML=rows.map(i=>`
    <tr>
      <td class="td-veh">${i.vehicle_name}</td>
      <td><span class="doc-type"><span class="swatch" style="background:${i.type_color}"></span>${i.type}</span></td>
      <td class="td-mono">${grp[i.vehicle_id]||''}</td>
      <td class="td-mono">${i.expiry_display}</td>
      <td class="td-mono">${i.days_display}</td>
      <td class="td-mono">${i.amount?'₹'+Number(i.amount).toLocaleString('en-IN'):'—'}</td>
      <td><span class="status-pill" style="background:${i.urgency_color}">${i.urgency_label}</span></td>
      <td>${fileBtnHtml(i)}</td>
    </tr>`).join('');
}
document.querySelectorAll('#status-tabs .pill-btn').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('#status-tabs .pill-btn').forEach(x=>x.classList.remove('active'));
  b.classList.add('active'); statusFilter=b.dataset.filter; renderTable();
}));

/* ---------- Search ---------- */
document.getElementById('search').addEventListener('input',()=>{ renderFleets(); renderTable(); });

/* ---------- Upload (Apps Script) ---------- */
let pendingUpload=null;
const fileInput=document.getElementById('file-input');
document.addEventListener('click',e=>{
  const btn=e.target.closest('[data-up]'); if(!btn) return;
  pendingUpload={key:btn.dataset.up,vid:btn.dataset.vid,dtype:btn.dataset.dtype,btn};
  fileInput.value=''; fileInput.click();
});
fileInput.addEventListener('change',async()=>{
  const file=fileInput.files[0]; if(!file||!pendingUpload) return;
  const {key,vid,dtype,btn}=pendingUpload;
  if(file.size > 12*1024*1024){ alert('That file is '+(file.size/1048576).toFixed(1)+' MB — please upload a scan under 12 MB.'); pendingUpload=null; return; }
  btn.classList.add('uploading'); btn.textContent='… uploading';
  try{
    const dataBase64=await new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(String(r.result).split(',')[1]);r.onerror=rej;r.readAsDataURL(file);});
    const resp=await fetch(DATA.doc_api_url,{method:'POST',headers:{'Content-Type':'text/plain;charset=utf-8'},
      body:JSON.stringify({action:'upload',token:DATA.doc_api_token,vehicle_id:vid,doc_type:dtype,filename:file.name,mimeType:file.type,dataBase64})});
    const j=await resp.json();
    if(j.ok){ fileMap[key]={url:j.url,name:j.name||file.name}; renderFleets(); renderTable(); }
    else { alert('Upload failed: '+(j.error||'unknown error')); btn.classList.remove('uploading'); btn.textContent='⬆ Upload'; }
  }catch(err){ alert('Upload error: '+err.message); btn.classList.remove('uploading'); btn.textContent='⬆ Upload'; }
  pendingUpload=null;
});

/* ---------- Load existing files from the API ---------- */
async function loadFiles(){
  if(!DATA.doc_api_url) return;
  try{
    const r=await fetch(DATA.doc_api_url+(DATA.doc_api_url.includes('?')?'&':'?')+'action=files');
    const j=await r.json();
    if(j&&j.files){ Object.assign(fileMap,j.files); renderFleets(); renderTable(); }
  }catch(e){ /* non-fatal: dashboard still works without the file overlay */ }
}

/* ---------- Renewal calendar (.ics) ---------- */
document.getElementById('btn-ics').addEventListener('click',()=>{
  const pad=n=>String(n).padStart(2,'0');
  const fmt=d=>d.getFullYear()+pad(d.getMonth()+1)+pad(d.getDate());
  const lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//The Garage//Fleet Papers//EN','CALSCALE:GREGORIAN'];
  DATA.all_items.forEach(i=>{
    const d=new Date(i.expiry_date+'T00:00:00');
    const dt=fmt(d); const end=fmt(new Date(d.getTime()+86400000));
    lines.push('BEGIN:VEVENT',
      'UID:'+i.key.replace(/[^a-z0-9]/gi,'')+'@garage',
      'DTSTART;VALUE=DATE:'+dt,'DTEND;VALUE=DATE:'+end,
      'SUMMARY:'+(i.type+' — '+i.vehicle_name+(i.days_left<0?' (OVERDUE)':'')),
      'DESCRIPTION:'+(i.provider?('Provider '+i.provider+'. '):'')+'Expires '+i.expiry_display,
      'BEGIN:VALARM','TRIGGER:-P7D','ACTION:DISPLAY','DESCRIPTION:Renewal due in 7 days','END:VALARM',
      'END:VEVENT');
  });
  lines.push('END:VCALENDAR');
  const blob=new Blob([lines.join('\r\n')],{type:'text/calendar'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='fleet-renewals.ics'; a.click();
});
document.getElementById('btn-print').addEventListener('click',()=>window.print());

/* ---------- Boot ---------- */
renderFleets(); renderTable(); loadFiles();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build_dashboard()
