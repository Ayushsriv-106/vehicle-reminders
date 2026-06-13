"""Builds docs/index.html — a clean, professional, single-file fleet-documents
dashboard deployed to Cloudflare Pages.

Design goals (rebuilt 2026-06-13):
  * Light, neutral, business look. Colour is used ONLY to signal status
    (red = overdue, amber = expiring, green = valid, grey = neutral) — never
    decoration. No gradients, no rainbow per-document colours.
  * Validation front-and-centre: missing legally-required papers and data-quality
    issues are surfaced prominently.
  * A ready-to-post WhatsApp reminder for the "Car papers" group is auto-composed
    on every build, with one-tap Share + Copy.

The page is self-contained (no build step). Document scans are an overlay served
by the Cloudflare Function at DOC_API_URL (/api/files), behind the shared login.
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
    compose_whatsapp_reminder,
    load_config,
    missing_required,
    owner_group,
    required_docs_for,
)


# Functional status palette — tinted background, readable text, subtle border.
URGENCY_META = {
    "overdue":  {"label": "Overdue",   "rank": 0, "fg": "#b42318", "bg": "#fef3f2", "bd": "#fecdca"},
    "critical": {"label": "Urgent",    "rank": 1, "fg": "#b54708", "bg": "#fff6ed", "bd": "#fdd9b5"},
    "warning":  {"label": "Due soon",  "rank": 2, "fg": "#a16207", "bg": "#fefce8", "bd": "#fde68a"},
    "ok":       {"label": "Valid",     "rank": 3, "fg": "#067647", "bg": "#ecfdf3", "bd": "#abefc6"},
    "far":      {"label": "Valid",     "rank": 4, "fg": "#475467", "bg": "#f2f4f7", "bd": "#e4e7ec"},
}


def _fmt_days(days: int) -> str:
    if days < 0:
        return f"{abs(days)}d overdue"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days}d"


def _item_to_json(i: Item) -> dict:
    m = URGENCY_META[i.urgency]
    return {
        "key": f"{i.vehicle_id}|{i.type}",
        "vehicle_id": i.vehicle_id,
        "vehicle_name": i.vehicle_name,
        "category": i.category,
        "type": i.type,
        "expiry_date": i.expiry_date.isoformat(),
        "expiry_display": i.expiry_date.strftime("%d %b %Y"),
        "days_left": i.days_left,
        "days_display": _fmt_days(i.days_left),
        "urgency": i.urgency,
        "urgency_label": m["label"],
        "u_fg": m["fg"], "u_bg": m["bg"], "u_bd": m["bd"],
        "provider": i.provider,
        "amount": i.amount,
        "file_link": i.file_link,
        "extra": i.extra,
    }


def _vehicle_issues(vehicle: dict, v_items: list[Item], reg_counts: dict[str, int]) -> list[dict]:
    """Automated data-quality review of one vehicle's record. Each issue is
    {level: error|warn|info, text}."""
    issues: list[dict] = []
    reg = (vehicle.get("registration_number") or "").strip()
    owner = (vehicle.get("owner") or "").strip()
    name = (vehicle.get("name") or "").strip()
    note = (vehicle.get("notes") or "").strip()
    docs = [i for i in v_items if i.category == "document"]

    if not reg or re.search(r"x{2,}", reg, re.I):
        issues.append({"level": "error", "text": "Registration looks like a placeholder — needs the real number"})
    elif reg_counts.get(reg.upper().replace(" ", ""), 0) > 1:
        issues.append({"level": "error", "text": f"Registration {reg} is recorded on more than one vehicle — check for a duplicate"})
    if not docs:
        issues.append({"level": "error", "text": "No documents on record at all"})
    if any(i.type == "Insurance" and i.days_left < 0 for i in docs):
        issues.append({"level": "error", "text": "Insurance has lapsed — vehicle may be running uninsured"})
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

    # Registration frequency for duplicate detection.
    reg_counts: dict[str, int] = {}
    for v in vehicles:
        r = (v.get("registration_number") or "").strip().upper().replace(" ", "")
        if r and not re.search(r"X{2,}", r):
            reg_counts[r] = reg_counts.get(r, 0) + 1

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
        issues = _vehicle_issues(v, v_items, reg_counts)
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
                "id": v["id"],
                "vehicle_name": v["name"],
                "registration_number": v.get("registration_number", ""),
                "owner_group": grp,
                "vehicle_type": v.get("type", ""),
                "missing": missing,
                "has_any": bool(present_types),
            })
        if issues:
            review_report.append({
                "vehicle_name": v["name"],
                "registration_number": v.get("registration_number", ""),
                "owner_group": grp,
                "issues": issues,
            })

    # Most-broken first in the gaps list.
    missing_report.sort(key=lambda m: (m["has_any"], -len(m["missing"])))

    stats = {
        "vehicles": len(vehicles),
        "total_items": len(items),
        "overdue": sum(1 for i in items if i.urgency == "overdue"),
        "critical": sum(1 for i in items if i.urgency == "critical"),
        "warning": sum(1 for i in items if i.urgency == "warning"),
        "ok": sum(1 for i in items if i.urgency in ("ok", "far")),
        "missing_required": missing_required_total,
        "data_issues": issues_total,
        "annual_spend": sum(
            (i.amount or 0) for i in items
            if i.category == "document" and i.amount
        ),
    }

    status_counts = {k: sum(1 for i in items if i.urgency == k)
                     for k in ("overdue", "critical", "warning", "ok", "far")}

    timeline = [_item_to_json(i) for i in items if 0 <= i.days_left <= 365]

    spend_by_type: dict[str, float] = {}
    for i in items:
        if i.amount:
            spend_by_type[i.type] = spend_by_type.get(i.type, 0) + i.amount

    dashboard_url = os.environ.get("DASHBOARD_URL", "").strip() or "https://garage-fleet.pages.dev/"
    whatsapp_message = compose_whatsapp_reminder(config, items, dashboard_url=dashboard_url)

    payload = {
        "generated_at": date.today().isoformat(),
        "generated_display": date.today().strftime("%A, %d %B %Y"),
        "doc_api_url": os.environ.get("DOC_API_URL", "").strip(),
        "doc_api_token": os.environ.get("DOC_API_TOKEN", "").strip(),
        "dashboard_url": dashboard_url,
        "whatsapp_message": whatsapp_message,
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
    print(f"Dashboard built at {output_path} ({len(vehicles)} vehicles, {len(items)} items)")


# =========================================================================== #
# HTML template — clean, light, professional, single-file
# =========================================================================== #

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Fleet Document Register</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #f4f5f7;
    --surface: #ffffff;
    --surface-2: #f8f9fb;
    --ink: #101828;
    --ink-2: #344054;
    --muted: #667085;
    --line: #e4e7ec;
    --line-strong: #d0d5dd;
    --accent: #3538cd;        /* single brand accent — indigo */
    --accent-soft: #eef0fb;
    --red: #b42318; --red-bg:#fef3f2; --red-bd:#fecdca;
    --org: #b54708; --org-bg:#fff6ed; --org-bd:#fdd9b5;
    --amb: #a16207; --amb-bg:#fefce8; --amb-bd:#fde68a;
    --grn: #067647; --grn-bg:#ecfdf3; --grn-bd:#abefc6;
    --gry: #475467; --gry-bg:#f2f4f7; --gry-bd:#e4e7ec;
    --shadow: 0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06);
    --shadow-md: 0 1px 2px rgba(16,24,40,.04), 0 4px 12px -4px rgba(16,24,40,.10);
  }
  * { box-sizing: border-box; }
  html, body { margin:0; padding:0; }
  body {
    background: var(--bg); color: var(--ink);
    font-family: "Inter", -apple-system, system-ui, sans-serif;
    font-size: 14px; line-height: 1.5; -webkit-font-smoothing: antialiased;
  }
  a { color: var(--accent); text-decoration: none; }
  .mono { font-family: "IBM Plex Mono", ui-monospace, monospace; }
  .wrap { max-width: 1240px; margin: 0 auto; padding: 0 24px 80px; }
  @media (max-width:640px){ .wrap{ padding:0 14px 56px; } }

  /* Topbar -------------------------------------------------------------- */
  .topbar { background: var(--surface); border-bottom: 1px solid var(--line); margin-bottom: 24px; }
  .topbar-in { max-width:1240px; margin:0 auto; padding:18px 24px; display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; }
  @media (max-width:640px){ .topbar-in{ padding:14px; } }
  .brand { display:flex; align-items:center; gap:12px; }
  .brand .mark { width:34px; height:34px; border-radius:8px; background:var(--accent); color:#fff; display:grid; place-items:center; font-weight:700; font-size:16px; flex:none; }
  .brand h1 { font-size:17px; font-weight:600; margin:0; letter-spacing:-.01em; }
  .brand .sub { font-size:12px; color:var(--muted); margin-top:1px; }
  .topbar .date { font-size:12px; color:var(--muted); text-align:right; }
  .topbar .date b { color:var(--ink-2); font-weight:600; }

  /* Toolbar ------------------------------------------------------------- */
  .toolbar { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-bottom:22px; }
  .search { flex:1 1 260px; display:flex; align-items:center; gap:8px; background:var(--surface); border:1px solid var(--line-strong); border-radius:9px; padding:9px 12px; box-shadow:var(--shadow); }
  .search svg { flex:none; color:var(--muted); }
  .search input { flex:1; background:transparent; border:none; outline:none; color:var(--ink); font-size:14px; }
  .btn { border:1px solid var(--line-strong); background:var(--surface); color:var(--ink-2); border-radius:9px; padding:9px 14px; font-size:13px; font-weight:600; cursor:pointer; display:inline-flex; align-items:center; gap:7px; box-shadow:var(--shadow); transition:background .12s, border-color .12s; }
  .btn:hover { background:var(--surface-2); border-color:var(--muted); }
  .btn.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
  .btn.primary:hover { background:#2a2da8; }
  .btn.wa { background:#1ea463; border-color:#1ea463; color:#fff; }
  .btn.wa:hover { background:#17854f; }

  /* KPI strip ----------------------------------------------------------- */
  .kpis { display:grid; grid-template-columns:repeat(6,1fr); gap:12px; margin-bottom:24px; }
  @media (max-width:1000px){ .kpis{ grid-template-columns:repeat(3,1fr);} }
  @media (max-width:560px){ .kpis{ grid-template-columns:repeat(2,1fr);} }
  .kpi { background:var(--surface); border:1px solid var(--line); border-radius:11px; padding:14px 15px; box-shadow:var(--shadow); }
  .kpi .k-label { font-size:11px; font-weight:600; letter-spacing:.02em; text-transform:uppercase; color:var(--muted); margin-bottom:7px; }
  .kpi .k-value { font-size:26px; font-weight:700; line-height:1; letter-spacing:-.02em; }
  .kpi .k-sub { font-size:11px; color:var(--muted); margin-top:5px; }
  .kpi.alert { border-color:var(--red-bd); background:var(--red-bg); }
  .kpi.alert .k-value { color:var(--red); }

  /* Cards / sections ---------------------------------------------------- */
  .card { background:var(--surface); border:1px solid var(--line); border-radius:12px; box-shadow:var(--shadow); }
  .section { margin-bottom:28px; }
  .section-head { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:13px; gap:12px; flex-wrap:wrap; }
  .section-head h2 { font-size:16px; font-weight:600; margin:0; letter-spacing:-.01em; }
  .section-head .meta { font-size:12px; color:var(--muted); }

  /* WhatsApp reminder card --------------------------------------------- */
  .wa-card { padding:18px 20px; border-left:4px solid #1ea463; }
  .wa-head { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-bottom:12px; }
  .wa-head h2 { font-size:16px; font-weight:600; margin:0; display:flex; align-items:center; gap:9px; }
  .wa-head .pill-note { font-size:11.5px; color:var(--muted); }
  .wa-actions { display:flex; gap:8px; flex-wrap:wrap; }
  .wa-msg { background:var(--surface-2); border:1px solid var(--line); border-radius:9px; padding:14px 16px; font-size:13px; line-height:1.55; white-space:pre-wrap; color:var(--ink-2); max-height:300px; overflow:auto; }
  .wa-msg b { color:var(--ink); }

  /* Charts -------------------------------------------------------------- */
  .charts { display:grid; grid-template-columns:1.6fr 1fr 1fr; gap:14px; }
  @media (max-width:920px){ .charts{ grid-template-columns:1fr;} }
  .chart-card { padding:16px 16px 12px; }
  .chart-card h3 { font-size:13.5px; font-weight:600; margin:0 0 2px; }
  .chart-card .sub { font-size:11px; color:var(--muted); margin-bottom:12px; }
  .chart-wrap { height:210px; position:relative; }

  /* Gaps / review ------------------------------------------------------- */
  .gaps-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(290px,1fr)); gap:12px; }
  .gap-card { background:var(--surface); border:1px solid var(--line); border-left:3px solid var(--red); border-radius:10px; padding:14px 16px; box-shadow:var(--shadow); }
  .gap-card.warn-card { border-left-color:var(--amb); }
  .gap-card .g-name { font-weight:600; font-size:14px; }
  .gap-card .g-reg { font-size:12px; color:var(--muted); margin:2px 0 9px; }
  .issue-line { display:flex; gap:8px; align-items:flex-start; font-size:12.5px; padding:4px 0; color:var(--ink-2); }
  .issue-dot { width:7px; height:7px; border-radius:50%; flex:none; margin-top:6px; }
  .lvl-error{ background:var(--red);} .lvl-warn{ background:var(--amb);} .lvl-info{ background:var(--muted);}

  /* Pills / tabs -------------------------------------------------------- */
  .tabs { display:flex; gap:7px; flex-wrap:wrap; margin-bottom:15px; }
  .pill-btn { font-size:12.5px; font-weight:500; padding:7px 13px; border-radius:8px; border:1px solid var(--line-strong); background:var(--surface); color:var(--ink-2); cursor:pointer; transition:all .12s; }
  .pill-btn:hover { border-color:var(--muted); }
  .pill-btn.active { background:var(--accent); border-color:var(--accent); color:#fff; }

  /* Status pill (functional colour) ------------------------------------ */
  .status-pill { font-size:11px; font-weight:600; padding:3px 9px; border-radius:6px; white-space:nowrap; border:1px solid transparent; }
  .doc-pill { font-size:11px; font-weight:600; padding:2px 8px; border-radius:6px; background:var(--accent-soft); color:var(--accent); white-space:nowrap; }

  /* Fleet groups + vehicle cards --------------------------------------- */
  .fleet-group { margin-bottom:26px; }
  .fleet-title { font-size:13px; font-weight:600; margin:0 0 12px; display:flex; align-items:center; gap:9px; color:var(--ink-2); text-transform:uppercase; letter-spacing:.03em; }
  .fleet-title .dot { width:8px; height:8px; border-radius:50%; }
  .fleet-title .n { color:var(--muted); font-weight:500; }
  .vehicles-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:14px; }
  .vehicle-card { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:17px 18px; box-shadow:var(--shadow); transition:box-shadow .14s, border-color .14s; }
  .vehicle-card:hover { box-shadow:var(--shadow-md); border-color:var(--line-strong); }
  .vehicle-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }
  .vehicle-name { font-weight:600; font-size:15px; line-height:1.25; }
  .vehicle-reg { font-size:12px; color:var(--muted); margin-top:2px; }
  .vehicle-type-chip { font-size:10.5px; font-weight:500; color:var(--muted); border:1px solid var(--line); border-radius:6px; padding:3px 8px; white-space:nowrap; }

  .ring { --pct:0; width:42px; height:42px; border-radius:50%; flex:none;
    background: conic-gradient(var(--ring-c) calc(var(--pct)*1%), var(--line) 0);
    display:grid; place-items:center; position:relative; }
  .ring::after { content:""; position:absolute; inset:4px; background:var(--surface); border-radius:50%; }
  .ring span { position:relative; z-index:1; font-size:10.5px; font-weight:700; }

  .veh-note { font-size:12px; color:var(--muted); margin:11px 0 0; }
  .missing-row { margin-top:11px; display:flex; flex-wrap:wrap; gap:6px; align-items:center; padding:9px 10px; background:var(--red-bg); border:1px solid var(--red-bd); border-radius:8px; }
  .missing-label { font-size:11px; color:var(--red); font-weight:700; text-transform:uppercase; letter-spacing:.03em; }
  .missing-hint { font-size:10.5px; color:var(--muted); width:100%; margin-top:2px; }
  .miss-pill { font-size:11px; font-weight:600; padding:3px 9px; border-radius:6px; background:#fff; color:var(--red); border:1px solid var(--red-bd); display:inline-flex; align-items:center; gap:4px; }
  /* Blinking red = "missing, please upload". Click to upload its scan.
     Solid red + opacity pulse (compositor-only, cheap even with many on screen). */
  .miss-pill.need { cursor:pointer; background:#d92d20; color:#fff; border-color:#d92d20; }
  button.miss-pill.need { font-family:inherit; }
  .miss-pill.need:not(.uploading) { animation: blinkRed 1.2s ease-in-out infinite; }
  .miss-pill.need:hover { animation:none; opacity:1; background:#b42318; border-color:#b42318; }
  .miss-pill.done { background:var(--grn-bg); color:var(--grn); border-color:var(--grn-bd); cursor:default; animation:none; text-decoration:none; }
  .miss-pill.uploading { opacity:.7; pointer-events:none; animation:none; }
  @keyframes blinkRed { 0%,100% { opacity:1; } 50% { opacity:.4; } }
  @media (prefers-reduced-motion: reduce) {
    .miss-pill.need:not(.uploading) { animation:none; opacity:1; }
  }
  .issue-badges { margin-top:9px; display:flex; flex-wrap:wrap; gap:6px; }
  .issue-badge { font-size:10.5px; padding:3px 8px; border-radius:6px; border:1px solid var(--line); color:var(--ink-2); background:var(--surface-2); display:inline-flex; gap:5px; align-items:center; }

  .doc-list { list-style:none; padding:0; margin:13px 0 0; }
  .doc-item { display:grid; grid-template-columns:1fr auto; gap:6px 12px; padding:10px 0; border-top:1px solid var(--line); align-items:center; }
  .doc-item:first-child { border-top:none; }
  .doc-left { display:flex; flex-direction:column; gap:3px; min-width:0; }
  .doc-type { font-weight:600; font-size:13px; }
  .doc-type .prov { color:var(--muted); font-weight:400; font-size:12px; }
  .doc-exp { font-size:11.5px; color:var(--muted); }
  .doc-right { display:flex; align-items:center; gap:8px; }
  .file-btn { border:1px solid var(--line-strong); background:var(--surface); color:var(--ink-2); border-radius:7px; padding:4px 9px; font-size:11px; font-weight:600; cursor:pointer; display:inline-flex; align-items:center; gap:5px; white-space:nowrap; transition:all .12s; }
  .file-btn:hover { border-color:var(--accent); color:var(--accent); }
  .file-btn.has-file { border-color:var(--grn-bd); color:var(--grn); background:var(--grn-bg); }
  .file-btn.has-file:hover { border-color:var(--grn); color:var(--grn); }
  .file-btn.dl { color:var(--ink-2); background:var(--surface); border-color:var(--line-strong); }
  .file-btn.dl:hover { border-color:var(--accent); color:var(--accent); }
  .file-btn.uploading { opacity:.6; pointer-events:none; }
  .file-btn.disabled { opacity:.5; cursor:not-allowed; }
  .file-acts { display:inline-flex; gap:6px; }
  .miss-dl { font-size:11px; font-weight:700; color:var(--grn); background:var(--grn-bg); border:1px solid var(--grn-bd); border-radius:6px; padding:3px 7px; text-decoration:none; line-height:1; }
  .miss-dl:hover { background:var(--grn); color:#fff; border-color:var(--grn); }
  .miss-done-group { display:inline-flex; gap:4px; align-items:center; }

  /* Table --------------------------------------------------------------- */
  .table-wrap { overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:12px; box-shadow:var(--shadow); }
  table.tbl { width:100%; border-collapse:collapse; font-size:13px; min-width:740px; }
  table.tbl thead { background:var(--surface-2); }
  table.tbl th { text-align:left; padding:11px 16px; font-size:11px; letter-spacing:.03em; text-transform:uppercase; color:var(--muted); font-weight:600; border-bottom:1px solid var(--line); }
  table.tbl td { padding:11px 16px; border-top:1px solid var(--line); vertical-align:middle; }
  table.tbl tr:hover td { background:var(--surface-2); }
  .td-veh { font-weight:600; }
  .td-mut { color:var(--muted); }

  footer { margin-top:46px; padding-top:20px; border-top:1px solid var(--line); font-size:12px; color:var(--muted); display:flex; justify-content:space-between; flex-wrap:wrap; gap:10px; }
  .empty { text-align:center; padding:34px; color:var(--muted); }
  .hidden { display:none !important; }

  @media print {
    body { background:#fff; }
    .toolbar,.file-btn,.tabs,.btn,.search,.wa-actions { display:none !important; }
    .card,.kpi,.vehicle-card,.gap-card,.table-wrap { box-shadow:none; }
    .vehicle-card { break-inside:avoid; }
  }
</style>
</head>
<body>

<div class="topbar">
  <div class="topbar-in">
    <div class="brand">
      <div class="mark">F</div>
      <div>
        <h1>Fleet Document Register</h1>
        <div class="sub">Insurance · PUC · Fitness · Permit · RC · Road Tax</div>
      </div>
    </div>
    <div class="date">
      <div><b id="today"></b></div>
      <div>Auto-refreshed daily</div>
    </div>
  </div>
</div>

<div class="wrap">

  <div class="toolbar">
    <div class="search">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
      <input id="search" type="search" placeholder="Search vehicle, registration, document…" autocomplete="off" />
    </div>
    <button class="btn" id="btn-ics" title="Download a calendar of every renewal">Renewal calendar</button>
    <button class="btn" id="btn-print" title="Print or save as PDF">Print</button>
  </div>

  <div class="kpis" id="kpis"></div>

  <!-- WhatsApp reminder -->
  <div class="section" id="wa-section">
    <div class="card wa-card">
      <div class="wa-head">
        <h2>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="#1ea463"><path d="M12 2a10 10 0 0 0-8.6 15l-1.4 5 5.1-1.3A10 10 0 1 0 12 2zm0 18a8 8 0 0 1-4.1-1.1l-.3-.2-3 .8.8-2.9-.2-.3A8 8 0 1 1 12 20zm4.4-5.6c-.2-.1-1.4-.7-1.6-.8s-.4-.1-.5.1-.6.8-.8 1-.3.2-.5.1a6.5 6.5 0 0 1-3.2-2.8c-.2-.4.2-.4.6-1.2a.5.5 0 0 0 0-.5l-.8-1.8c-.2-.5-.4-.4-.5-.4h-.5a.9.9 0 0 0-.7.3 2.8 2.8 0 0 0-.9 2.1 4.9 4.9 0 0 0 1 2.6 11 11 0 0 0 4.3 3.8c1.6.7 2.2.7 3 .6a2.5 2.5 0 0 0 1.6-1.1 2 2 0 0 0 .1-1.1c0-.1-.2-.2-.4-.3z"/></svg>
          WhatsApp reminder
        </h2>
        <div class="wa-actions">
          <button class="btn wa" id="btn-wa-share">Share to WhatsApp</button>
          <button class="btn" id="btn-wa-copy">Copy</button>
        </div>
      </div>
      <div class="pill-note" style="margin-bottom:10px">Auto-built from today's data. Tap <b>Share</b> → pick the <b>Car papers</b> group → Send.</div>
      <div class="wa-msg mono" id="wa-msg"></div>
    </div>
  </div>

  <!-- Charts -->
  <div class="section">
    <div class="section-head"><h2>At a glance</h2><div class="meta">Live snapshot</div></div>
    <div class="charts">
      <div class="card chart-card"><h3>Renewal timeline</h3><div class="sub">Papers due each month · next 12 months</div><div class="chart-wrap"><canvas id="c-timeline"></canvas></div></div>
      <div class="card chart-card"><h3>Status mix</h3><div class="sub">All tracked papers</div><div class="chart-wrap"><canvas id="c-status"></canvas></div></div>
      <div class="card chart-card"><h3>Annual spend</h3><div class="sub">By document type</div><div class="chart-wrap"><canvas id="c-spend"></canvas></div></div>
    </div>
  </div>

  <!-- Missing documents -->
  <div class="section" id="gaps-section">
    <div class="section-head"><h2>Missing documents</h2><div class="meta" id="gaps-meta"></div></div>
    <div class="gaps-grid" id="gaps-grid"></div>
  </div>

  <!-- Data review -->
  <div class="section" id="review-section">
    <div class="section-head"><h2>Data review</h2><div class="meta" id="review-meta"></div></div>
    <div class="gaps-grid" id="review-grid"></div>
  </div>

  <!-- Fleets -->
  <div class="section">
    <div class="section-head"><h2>The fleet</h2><div class="meta" id="fleet-count"></div></div>
    <div class="tabs" id="fleet-tabs"></div>
    <div id="fleets"></div>
  </div>

  <!-- Everything table -->
  <div class="section">
    <div class="section-head"><h2>Every paper</h2><div class="meta">Filter &amp; export</div></div>
    <div class="tabs" id="status-tabs">
      <button class="pill-btn active" data-filter="all">All</button>
      <button class="pill-btn" data-filter="overdue">Overdue</button>
      <button class="pill-btn" data-filter="critical">Urgent</button>
      <button class="pill-btn" data-filter="warning">Due soon</button>
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
    <div>Built from your fleet sheet · Deployed on Cloudflare Pages</div>
    <div id="generated-at" class="mono"></div>
  </footer>
</div>

<input type="file" id="file-input" class="hidden" accept="image/*,application/pdf" />

<script>
const DATA = __DATA__;
const FLEET_DOTS = { "GJMS School":"#3538cd", "G.B. Automobiles":"#0e7090", "Family & Personal":"#667085" };

const fileMap = {};
DATA.all_items.forEach(i => { if (i.file_link) fileMap[i.key] = { url:i.file_link, name:"document" }; });

document.getElementById('today').textContent = DATA.generated_display;
document.getElementById('generated-at').textContent = 'Generated ' + DATA.generated_at;

function formatINR(n){
  n=Number(n)||0;
  if(n>=1e7) return '₹'+(n/1e7).toFixed(2).replace(/\.00$/,'')+' Cr';
  if(n>=1e5) return '₹'+(n/1e5).toFixed(2).replace(/\.00$/,'')+' L';
  return '₹'+n.toLocaleString('en-IN');
}

/* ---------- KPIs ---------- */
(function(){
  const s = DATA.stats;
  const cards = [
    { label:'Vehicles', value:s.vehicles },
    { label:'Papers tracked', value:s.total_items },
    { label:'Overdue', value:s.overdue, alert:s.overdue>0 },
    { label:'Urgent ≤7d', value:s.critical, alert:s.critical>0 },
    { label:'Missing papers', value:s.missing_required, alert:s.missing_required>0, sub:'legally required' },
    { label:'Annual cost', value:formatINR(s.annual_spend), sub:'recorded premiums' },
  ];
  document.getElementById('kpis').innerHTML = cards.map(c => `
    <div class="kpi ${c.alert?'alert':''}">
      <div class="k-label">${c.label}</div>
      <div class="k-value">${c.value}</div>
      ${c.sub?`<div class="k-sub">${c.sub}</div>`:''}
    </div>`).join('');
})();

/* ---------- WhatsApp reminder ---------- */
(function(){
  const msg = (DATA.whatsapp_message||'').trim();
  const sec = document.getElementById('wa-section');
  if(!msg){ sec.querySelector('.wa-msg').textContent='Nothing to report — every paper is valid and nothing is missing. 🎉';
            document.getElementById('btn-wa-share').classList.add('hidden');
            document.getElementById('btn-wa-copy').classList.add('hidden'); return; }
  // Render with light markdown (*bold*) -> <b>
  const html = msg.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/\*(.+?)\*/g,'<b>$1</b>');
  document.getElementById('wa-msg').innerHTML = html;
  document.getElementById('btn-wa-share').addEventListener('click',()=>{
    window.open('https://wa.me/?text='+encodeURIComponent(msg),'_blank');
  });
  document.getElementById('btn-wa-copy').addEventListener('click',async(e)=>{
    try{ await navigator.clipboard.writeText(msg); e.target.textContent='Copied ✓'; setTimeout(()=>e.target.textContent='Copy',1500); }
    catch(err){ alert('Copy failed — select the text manually.'); }
  });
})();

/* ---------- Charts ---------- */
(function(){
  const months=[]; const now=new Date();
  for(let i=0;i<12;i++){ const d=new Date(now.getFullYear(),now.getMonth()+i,1);
    months.push({key:d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0'),
      label:d.toLocaleString('en-GB',{month:'short',year:'2-digit'}),count:0}); }
  DATA.timeline.forEach(it=>{ const m=months.find(x=>x.key===it.expiry_date.substring(0,7)); if(m)m.count++; });
  const gridC='#eef0f3', tickC='#667085', font={family:'Inter',size:10};
  new Chart(document.getElementById('c-timeline'),{type:'bar',
    data:{labels:months.map(m=>m.label),datasets:[{data:months.map(m=>m.count),
      backgroundColor:'#3538cd',borderRadius:4,borderSkipped:false,maxBarThickness:26}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},
      tooltip:{callbacks:{label:c=>c.parsed.y+' renewal(s)'}}},
      scales:{x:{grid:{display:false},ticks:{color:tickC,font}},
        y:{beginAtZero:true,ticks:{stepSize:1,color:tickC,font},grid:{color:gridC}}}}});

  const sc=DATA.status_counts; const SC=[['Overdue',sc.overdue,'#d92d20'],['Urgent',sc.critical,'#f79009'],
    ['Due soon',sc.warning,'#eab308'],['Valid',sc.ok+sc.far,'#12b76a']].filter(x=>x[1]>0);
  new Chart(document.getElementById('c-status'),{type:'doughnut',
    data:{labels:SC.map(x=>x[0]),datasets:[{data:SC.map(x=>x[1]),backgroundColor:SC.map(x=>x[2]),borderColor:'#fff',borderWidth:2}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'62%',
      plugins:{legend:{position:'bottom',labels:{color:'#475467',font:{family:'Inter',size:11},boxWidth:9,padding:9,usePointStyle:true}}}}});

  const sp=Object.entries(DATA.spend_by_type).sort((a,b)=>b[1]-a[1]);
  const SHADES=['#3538cd','#5b5ee0','#8284ec','#aab0f4','#0e7090','#3a9ab5'];
  if(!sp.length){ document.getElementById('c-spend').parentElement.innerHTML='<div class="empty">No amounts recorded yet</div>'; }
  else { new Chart(document.getElementById('c-spend'),{type:'doughnut',
    data:{labels:sp.map(e=>e[0]),datasets:[{data:sp.map(e=>e[1]),
      backgroundColor:sp.map((e,i)=>SHADES[i%SHADES.length]),borderColor:'#fff',borderWidth:2}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'62%',
      plugins:{legend:{position:'bottom',labels:{color:'#475467',font:{family:'Inter',size:11},boxWidth:9,padding:9,usePointStyle:true}},
        tooltip:{callbacks:{label:c=>c.label+': ₹'+c.parsed.toLocaleString('en-IN')}}}}}); }
})();

/* ---------- Missing documents ---------- */
function renderGaps(){
  const g=DATA.missing_report;
  document.getElementById('gaps-meta').textContent = g.length ? g.length+' vehicle(s) with missing papers — tap a blinking item to upload' : 'all clear';
  if(!g.length){ document.getElementById('gaps-grid').innerHTML='<div class="empty">Every vehicle has all its legally-required papers on record.</div>'; return; }
  document.getElementById('gaps-grid').innerHTML = g.map(v=>`
    <div class="gap-card">
      <div class="g-name">${v.vehicle_name}</div>
      <div class="g-reg">${v.registration_number||'—'} · ${v.owner_group}${v.has_any?'':' · <b style="color:var(--red)">no documents at all</b>'}</div>
      <div class="missing-row">
        <span class="missing-label">Missing</span>
        ${v.missing.map(m=>missPillHtml(v.id,m)).join('')}
      </div>
    </div>`).join('');
}

/* ---------- Data review ---------- */
(function(){
  const r=DATA.review_report||[];
  document.getElementById('review-meta').textContent = r.length ? (DATA.issues_total+' issue(s) across '+r.length+' vehicle(s)') : 'no issues found';
  if(!r.length){ document.getElementById('review-grid').innerHTML='<div class="empty">No data-quality issues detected in the records.</div>'; return; }
  document.getElementById('review-grid').innerHTML = r.map(v=>{
    const worst = v.issues.some(i=>i.level==='error') ? '' : 'warn-card';
    return `
    <div class="gap-card ${worst}">
      <div class="g-name">${v.vehicle_name}</div>
      <div class="g-reg">${v.registration_number||'—'} · ${v.owner_group}</div>
      ${v.issues.map(it=>`<div class="issue-line"><span class="issue-dot lvl-${it.level}"></span><span>${it.text}</span></div>`).join('')}
    </div>`;}).join('');
})();

/* ---------- File buttons (view + download) ---------- */
function dlUrl(url){ return url + (url.includes('?') ? '&' : '?') + 'dl=1'; }

function fileBtnHtml(it){
  const f = fileMap[it.key];
  if (f) return `<span class="file-acts">`+
    `<a class="file-btn has-file" href="${f.url}" target="_blank" rel="noopener" title="View ${it.type} scan">View</a>`+
    `<a class="file-btn dl" href="${dlUrl(f.url)}" download title="Download ${it.type} scan">Download</a>`+
    `</span>`;
  if (!DATA.doc_api_url) return `<span class="file-btn disabled" title="Document storage not connected yet">Upload</span>`;
  return `<button class="file-btn" data-up="${it.key}" data-vid="${it.vehicle_id}" data-dtype="${it.type}" title="Upload a scan">Upload</button>`;
}

/* A missing required paper: blinks red until a scan is uploaded for it.
   Click = upload that document's scan (stored under vehicleId|DocType).
   Once uploaded it turns green and offers View + Download. */
function missPillHtml(vid, dtype){
  const key = vid + '|' + dtype;
  const f = fileMap[key];
  if (f) return `<span class="miss-done-group">`+
    `<a class="miss-pill done" href="${f.url}" target="_blank" rel="noopener" title="View ${dtype} scan">✓ ${dtype}</a>`+
    `<a class="miss-dl" href="${dlUrl(f.url)}" download title="Download ${dtype} scan">↓</a>`+
    `</span>`;
  if (DATA.doc_api_url) return `<button class="miss-pill need" data-up="${key}" data-vid="${vid}" data-dtype="${dtype}" title="Missing — tap to upload the ${dtype} scan">⬆ ${dtype}</button>`;
  return `<span class="miss-pill need" title="${dtype} missing">${dtype}</span>`;
}

/* ---------- Fleets ---------- */
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
      const ringC = v.compliance_pct>=100?'#12b76a':v.compliance_pct>=50?'#eab308':'#d92d20';
      const docs = v.items.map(it=>`
        <li class="doc-item">
          <div class="doc-left">
            <span class="doc-type">${it.type}${it.provider?` <span class="prov">· ${it.provider}</span>`:''}</span>
            <span class="doc-exp">${it.expiry_display} · ${it.days_display}${it.amount?` · ₹${Number(it.amount).toLocaleString('en-IN')}`:''}</span>
          </div>
          <div class="doc-right">
            <span class="status-pill" style="color:${it.u_fg};background:${it.u_bg};border-color:${it.u_bd}">${it.urgency_label}</span>
            ${fileBtnHtml(it)}
          </div>
        </li>`).join('');
      const missing = v.missing.length ? `
        <div class="missing-row"><span class="missing-label">Missing</span>
          ${v.missing.map(m=>missPillHtml(v.id,m)).join('')}
          ${DATA.doc_api_url?'<span class="missing-hint">Blinking red = needed. Tap one to upload its scan.</span>':''}
        </div>` : '';
      const issues = (v.issues&&v.issues.length) ? `
        <div class="issue-badges">
          ${v.issues.map(it=>`<span class="issue-badge"><span class="issue-dot lvl-${it.level}"></span>${it.text}</span>`).join('')}
        </div>` : '';
      return `
        <div class="vehicle-card">
          <div class="vehicle-head">
            <div style="min-width:0">
              <div class="vehicle-name">${v.name}</div>
              <div class="vehicle-reg">${v.registration_number||'—'}</div>
            </div>
            <div style="display:flex;flex-direction:column;align-items:center;gap:7px">
              <div class="ring" style="--pct:${v.compliance_pct};--ring-c:${ringC}" title="${v.compliance_pct}% of required papers on record"><span style="color:${ringC}">${v.compliance_pct}%</span></div>
              <span class="vehicle-type-chip">${v.type}</span>
            </div>
          </div>
          ${missing}
          ${issues}
          <ul class="doc-list">${docs || '<li class="doc-item" style="color:var(--muted)">No papers on record yet.</li>'}</ul>
          ${v.notes?`<div class="veh-note">📝 ${v.notes}</div>`:''}
        </div>`;
    }).join('');
    host.insertAdjacentHTML('beforeend', `
      <div class="fleet-group">
        <h3 class="fleet-title"><span class="dot" style="background:${FLEET_DOTS[g]||'#667085'}"></span>${g} <span class="n">· ${vs.length}</span></h3>
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
      <td><span class="doc-pill">${i.type}</span></td>
      <td class="td-mut">${grp[i.vehicle_id]||''}</td>
      <td class="td-mut">${i.expiry_display}</td>
      <td class="td-mut">${i.days_display}</td>
      <td class="td-mut">${i.amount?'₹'+Number(i.amount).toLocaleString('en-IN'):'—'}</td>
      <td><span class="status-pill" style="color:${i.u_fg};background:${i.u_bg};border-color:${i.u_bd}">${i.urgency_label}</span></td>
      <td>${fileBtnHtml(i)}</td>
    </tr>`).join('');
}
document.querySelectorAll('#status-tabs .pill-btn').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('#status-tabs .pill-btn').forEach(x=>x.classList.remove('active'));
  b.classList.add('active'); statusFilter=b.dataset.filter; renderTable();
}));

document.getElementById('search').addEventListener('input',()=>{ renderFleets(); renderTable(); });

/* ---------- Upload ---------- */
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
    if(j.ok){ fileMap[key]={url:j.url,name:j.name||file.name}; }
    else { alert('Upload failed: '+(j.error||'unknown error')); }
  }catch(err){ alert('Upload error: '+err.message); }
  pendingUpload=null;
  renderAll();   // restores button/pill state from fileMap (blink → ✓ on success)
});

async function loadFiles(){
  if(!DATA.doc_api_url) return;
  try{
    const r=await fetch(DATA.doc_api_url+(DATA.doc_api_url.includes('?')?'&':'?')+'action=files');
    const j=await r.json();
    if(j&&j.files){ Object.assign(fileMap,j.files); renderAll(); }
  }catch(e){ /* non-fatal */ }
}

function renderAll(){ renderFleets(); renderTable(); renderGaps(); }

/* ---------- Renewal calendar (.ics) ---------- */
document.getElementById('btn-ics').addEventListener('click',()=>{
  const pad=n=>String(n).padStart(2,'0');
  const fmt=d=>d.getFullYear()+pad(d.getMonth()+1)+pad(d.getDate());
  const lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Fleet Register//EN','CALSCALE:GREGORIAN'];
  DATA.all_items.forEach(i=>{
    const d=new Date(i.expiry_date+'T00:00:00');
    const dt=fmt(d); const end=fmt(new Date(d.getTime()+86400000));
    lines.push('BEGIN:VEVENT',
      'UID:'+i.key.replace(/[^a-z0-9]/gi,'')+'@fleet',
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
renderAll(); loadFiles();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build_dashboard()
