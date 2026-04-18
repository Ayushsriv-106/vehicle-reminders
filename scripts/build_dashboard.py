"""Builds docs/index.html — a static dashboard deployed to GitHub Pages."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from core import Item, build_items, load_config


URGENCY_META = {
    "overdue":  {"label": "Overdue",  "color": "#c1121f", "rank": 0},
    "critical": {"label": "Urgent",   "color": "#e85d04", "rank": 1},
    "warning":  {"label": "Upcoming", "color": "#d4a017", "rank": 2},
    "ok":       {"label": "Scheduled","color": "#588157", "rank": 3},
    "far":      {"label": "Later",    "color": "#6b7280", "rank": 4},
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
    return {
        "vehicle_id": i.vehicle_id,
        "vehicle_name": i.vehicle_name,
        "category": i.category,
        "type": i.type,
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


def build_dashboard(output_path: str | Path = "docs/index.html") -> None:
    config = load_config()
    items = build_items(config)
    vehicles = config.get("vehicles", [])

    # ---------- Stats ---------- #
    stats = {
        "total_items": len(items),
        "overdue": sum(1 for i in items if i.urgency == "overdue"),
        "critical": sum(1 for i in items if i.urgency == "critical"),
        "warning": sum(1 for i in items if i.urgency == "warning"),
        "ok": sum(1 for i in items if i.urgency in ("ok", "far")),
        "vehicles": len(vehicles),
        "annual_spend": sum(
            (i.amount or 0) for i in items
            if i.category == "document" and i.amount
        ),
    }

    # ---------- Upcoming timeline (next 12 months) ---------- #
    timeline = []
    today = date.today()
    for i in items:
        if 0 <= i.days_left <= 365:
            timeline.append(_item_to_json(i))

    # ---------- Spend by category ---------- #
    spend_by_type: dict[str, float] = {}
    for i in items:
        if i.amount:
            spend_by_type[i.type] = spend_by_type.get(i.type, 0) + i.amount

    # ---------- Vehicle cards ---------- #
    vehicles_data = []
    for v in vehicles:
        v_items = [i for i in items if i.vehicle_id == v["id"]]
        vehicles_data.append({
            "id": v["id"],
            "name": v["name"],
            "registration_number": v.get("registration_number", ""),
            "type": v.get("type", ""),
            "owner": v.get("owner", ""),
            "purchase_date": str(v.get("purchase_date", "")),
            "notes": v.get("notes", ""),
            "items": [_item_to_json(i) for i in v_items],
            "worst_urgency_rank": min(
                (URGENCY_META[i.urgency]["rank"] for i in v_items),
                default=4
            ),
        })

    personal_items = [_item_to_json(i) for i in items if i.category == "personal"]
    all_items = [_item_to_json(i) for i in items]

    payload = {
        "generated_at": date.today().isoformat(),
        "generated_display": date.today().strftime("%A, %d %B %Y"),
        "stats": stats,
        "timeline": timeline,
        "spend_by_type": spend_by_type,
        "vehicles": vehicles_data,
        "personal": personal_items,
        "all_items": all_items,
    }

    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(payload, indent=2))
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    print(f"✅ Dashboard built at {output_path}")


# =========================================================================== #
# HTML template — editorial/refined aesthetic, single-file, no build step
# =========================================================================== #

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Garage — Vehicle Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,800&family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #f5f1ea;
    --bg-card: #faf7f1;
    --ink: #1a1814;
    --ink-soft: #4a4640;
    --ink-muted: #8a857d;
    --line: #d9d2c5;
    --accent: #c1121f;
    --accent-2: #0a3d2e;
    --gold: #b68a3c;
    --shadow: 0 1px 2px rgba(26,24,20,.04), 0 8px 24px rgba(26,24,20,.06);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #17140f;
      --bg-card: #1f1b15;
      --ink: #f5f1ea;
      --ink-soft: #c9c2b5;
      --ink-muted: #8a857d;
      --line: #35302a;
      --shadow: 0 1px 2px rgba(0,0,0,.3), 0 8px 24px rgba(0,0,0,.4);
    }
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--ink);
    font-family: "Inter", -apple-system, sans-serif;
    font-size: 15px;
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
    background-image:
      radial-gradient(circle at 20% 10%, rgba(193,18,31,.03), transparent 40%),
      radial-gradient(circle at 80% 60%, rgba(10,61,46,.04), transparent 50%);
  }
  .wrap { max-width: 1280px; margin: 0 auto; padding: 48px 32px 80px; }
  @media (max-width: 640px) { .wrap { padding: 28px 20px 60px; } }

  /* Masthead ---------------------------------------------------------- */
  .masthead {
    border-bottom: 2px solid var(--ink);
    padding-bottom: 20px;
    margin-bottom: 40px;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    gap: 24px;
    flex-wrap: wrap;
  }
  .masthead-left .eyebrow {
    font-family: "JetBrains Mono", monospace;
    font-size: 11px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--ink-muted);
    margin-bottom: 6px;
  }
  .masthead h1 {
    font-family: "Fraunces", serif;
    font-weight: 800;
    font-size: clamp(40px, 7vw, 72px);
    line-height: 0.95;
    letter-spacing: -0.03em;
    margin: 0;
    font-variation-settings: "opsz" 144;
  }
  .masthead h1 em {
    font-style: italic;
    font-weight: 400;
    color: var(--accent);
  }
  .masthead-right {
    text-align: right;
    font-family: "JetBrains Mono", monospace;
    font-size: 12px;
    color: var(--ink-soft);
  }
  .masthead-right .date {
    font-size: 14px;
    color: var(--ink);
    margin-bottom: 4px;
  }

  /* Stat strip -------------------------------------------------------- */
  .stats {
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 0;
    border-top: 1px solid var(--line);
    border-bottom: 1px solid var(--line);
    margin-bottom: 56px;
  }
  @media (max-width: 900px) { .stats { grid-template-columns: repeat(3, 1fr); } }
  @media (max-width: 520px) { .stats { grid-template-columns: repeat(2, 1fr); } }
  .stat {
    padding: 20px 16px;
    border-right: 1px solid var(--line);
  }
  .stat:last-child { border-right: none; }
  @media (max-width: 900px) {
    .stat:nth-child(3n) { border-right: none; }
    .stat { border-bottom: 1px solid var(--line); }
    .stat:nth-last-child(-n+3) { border-bottom: none; }
  }
  .stat-label {
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--ink-muted);
    margin-bottom: 8px;
  }
  .stat-value {
    font-family: "Fraunces", serif;
    font-size: 36px;
    font-weight: 600;
    line-height: 1;
    font-variation-settings: "opsz" 144;
  }
  .stat-value.alert { color: var(--accent); }
  .stat-value.warn { color: #e85d04; }
  .stat-value.ok { color: var(--accent-2); }

  /* Section headers --------------------------------------------------- */
  .section { margin-bottom: 56px; }
  .section-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 24px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--line);
  }
  .section-head h2 {
    font-family: "Fraunces", serif;
    font-weight: 600;
    font-size: 28px;
    letter-spacing: -0.01em;
    margin: 0;
  }
  .section-head .meta {
    font-family: "JetBrains Mono", monospace;
    font-size: 11px;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--ink-muted);
  }

  /* Alert banner ------------------------------------------------------ */
  .alert-banner {
    background: var(--accent);
    color: #fff;
    padding: 20px 28px;
    border-radius: 2px;
    margin-bottom: 32px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 20px;
    flex-wrap: wrap;
  }
  .alert-banner .alert-text {
    font-family: "Fraunces", serif;
    font-size: 20px;
    font-weight: 600;
  }
  .alert-banner .alert-sub {
    font-family: "JetBrains Mono", monospace;
    font-size: 11px;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    opacity: 0.85;
    margin-top: 2px;
  }

  /* Charts row -------------------------------------------------------- */
  .charts-row {
    display: grid;
    grid-template-columns: 1.6fr 1fr;
    gap: 24px;
  }
  @media (max-width: 900px) { .charts-row { grid-template-columns: 1fr; } }
  .chart-card {
    background: var(--bg-card);
    border: 1px solid var(--line);
    padding: 24px;
    box-shadow: var(--shadow);
  }
  .chart-card h3 {
    font-family: "Fraunces", serif;
    font-size: 18px;
    font-weight: 600;
    margin: 0 0 4px;
  }
  .chart-card .sub {
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--ink-muted);
    margin-bottom: 20px;
  }
  .chart-wrap { height: 280px; position: relative; }

  /* Vehicle cards ----------------------------------------------------- */
  .vehicles-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    gap: 20px;
  }
  .vehicle-card {
    background: var(--bg-card);
    border: 1px solid var(--line);
    padding: 28px;
    position: relative;
    box-shadow: var(--shadow);
    transition: transform .2s ease;
  }
  .vehicle-card:hover { transform: translateY(-2px); }
  .vehicle-card::before {
    content: "";
    position: absolute;
    top: 0; left: 0; width: 4px; height: 100%;
    background: var(--accent-2);
  }
  .vehicle-card.urgency-0::before { background: var(--accent); }
  .vehicle-card.urgency-1::before { background: #e85d04; }
  .vehicle-card.urgency-2::before { background: var(--gold); }

  .vehicle-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
    margin-bottom: 4px;
  }
  .vehicle-name {
    font-family: "Fraunces", serif;
    font-size: 22px;
    font-weight: 600;
    letter-spacing: -0.01em;
    line-height: 1.2;
  }
  .vehicle-type {
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--ink-muted);
    border: 1px solid var(--line);
    padding: 4px 8px;
    white-space: nowrap;
  }
  .vehicle-reg {
    font-family: "JetBrains Mono", monospace;
    font-size: 13px;
    color: var(--ink-soft);
    margin-bottom: 20px;
    letter-spacing: 0.05em;
  }
  .vehicle-items { list-style: none; padding: 0; margin: 0; }
  .vehicle-item {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 8px;
    padding: 10px 0;
    border-top: 1px dashed var(--line);
    align-items: center;
    font-size: 14px;
  }
  .vehicle-item:first-child { border-top: none; padding-top: 0; }
  .vi-left { display: flex; flex-direction: column; gap: 2px; }
  .vi-type { font-weight: 500; }
  .vi-expiry {
    font-family: "JetBrains Mono", monospace;
    font-size: 11px;
    color: var(--ink-muted);
  }
  .vi-right { display: flex; align-items: center; gap: 10px; }
  .pill {
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 4px 8px;
    border-radius: 999px;
    white-space: nowrap;
    font-weight: 600;
  }
  .pill.u-overdue { background: var(--accent); color: #fff; }
  .pill.u-critical { background: #e85d04; color: #fff; }
  .pill.u-warning { background: var(--gold); color: #fff; }
  .pill.u-ok { background: var(--accent-2); color: #fff; }
  .pill.u-far { background: var(--line); color: var(--ink-soft); }
  .file-link {
    color: var(--ink-soft);
    text-decoration: none;
    font-size: 16px;
    opacity: 0.6;
    transition: opacity .15s;
  }
  .file-link:hover { opacity: 1; color: var(--accent-2); }

  /* Timeline table ---------------------------------------------------- */
  .table-wrap { overflow-x: auto; background: var(--bg-card); border: 1px solid var(--line); box-shadow: var(--shadow); }
  table.timeline {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
    min-width: 720px;
  }
  table.timeline thead {
    background: var(--ink);
    color: var(--bg);
  }
  table.timeline th {
    text-align: left;
    padding: 14px 18px;
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    font-weight: 400;
  }
  table.timeline td {
    padding: 14px 18px;
    border-top: 1px solid var(--line);
    vertical-align: middle;
  }
  table.timeline tr:hover td { background: rgba(182,138,60,.06); }
  .td-vehicle { font-weight: 500; }
  .td-date {
    font-family: "JetBrains Mono", monospace;
    font-size: 13px;
  }
  .td-days {
    font-family: "JetBrains Mono", monospace;
    font-size: 12px;
    color: var(--ink-muted);
  }

  /* Filter tabs ------------------------------------------------------- */
  .tabs {
    display: flex;
    gap: 4px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }
  .tab {
    font-family: "JetBrains Mono", monospace;
    font-size: 11px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 8px 14px;
    border: 1px solid var(--line);
    background: var(--bg-card);
    color: var(--ink-soft);
    cursor: pointer;
    transition: all .15s;
  }
  .tab:hover { border-color: var(--ink); }
  .tab.active {
    background: var(--ink);
    color: var(--bg);
    border-color: var(--ink);
  }

  /* Footer ------------------------------------------------------------ */
  footer {
    margin-top: 64px;
    padding-top: 24px;
    border-top: 1px solid var(--line);
    font-family: "JetBrains Mono", monospace;
    font-size: 11px;
    color: var(--ink-muted);
    letter-spacing: 0.05em;
    display: flex;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
  }

  /* Fade-in animation ------------------------------------------------- */
  .fade-in { animation: fadeIn .6s ease both; }
  .fade-in:nth-child(1) { animation-delay: .05s; }
  .fade-in:nth-child(2) { animation-delay: .10s; }
  .fade-in:nth-child(3) { animation-delay: .15s; }
  .fade-in:nth-child(4) { animation-delay: .20s; }
  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: none; }
  }
</style>
</head>
<body>
<div class="wrap">

  <!-- Masthead -->
  <header class="masthead fade-in">
    <div class="masthead-left">
      <div class="eyebrow">Vol. I · Personal Fleet Register</div>
      <h1>The <em>Garage</em></h1>
    </div>
    <div class="masthead-right">
      <div class="date" id="today"></div>
      <div>Auto-refreshed daily · 00:00 IST</div>
    </div>
  </header>

  <!-- Stats -->
  <div class="stats fade-in">
    <div class="stat"><div class="stat-label">Vehicles</div><div class="stat-value" id="s-vehicles">—</div></div>
    <div class="stat"><div class="stat-label">Tracked</div><div class="stat-value" id="s-tracked">—</div></div>
    <div class="stat"><div class="stat-label">Overdue</div><div class="stat-value alert" id="s-overdue">—</div></div>
    <div class="stat"><div class="stat-label">Urgent</div><div class="stat-value warn" id="s-urgent">—</div></div>
    <div class="stat"><div class="stat-label">Upcoming</div><div class="stat-value" id="s-upcoming">—</div></div>
    <div class="stat"><div class="stat-label">Annual ₹</div><div class="stat-value" id="s-spend">—</div></div>
  </div>

  <!-- Alert banner (only shown if overdue/urgent exist) -->
  <div id="alert-banner-slot"></div>

  <!-- Charts -->
  <div class="section fade-in">
    <div class="section-head">
      <h2>At a glance</h2>
      <div class="meta">Next 12 months</div>
    </div>
    <div class="charts-row">
      <div class="chart-card">
        <h3>Expiry timeline</h3>
        <div class="sub">Count of items expiring each month</div>
        <div class="chart-wrap"><canvas id="chart-timeline"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>Recurring spend</h3>
        <div class="sub">Annualised, by document type</div>
        <div class="chart-wrap"><canvas id="chart-spend"></canvas></div>
      </div>
    </div>
  </div>

  <!-- Vehicles -->
  <div class="section">
    <div class="section-head">
      <h2>The fleet</h2>
      <div class="meta" id="fleet-count"></div>
    </div>
    <div class="vehicles-grid" id="vehicles-grid"></div>
  </div>

  <!-- Personal docs -->
  <div class="section" id="personal-section" style="display:none;">
    <div class="section-head">
      <h2>Personal documents</h2>
      <div class="meta">Licences &amp; KYC</div>
    </div>
    <div class="table-wrap">
      <table class="timeline">
        <thead><tr><th>Document</th><th>Owner</th><th>Expires</th><th>Status</th><th>File</th></tr></thead>
        <tbody id="personal-tbody"></tbody>
      </table>
    </div>
  </div>

  <!-- All items table -->
  <div class="section">
    <div class="section-head">
      <h2>Everything, sorted</h2>
      <div class="meta">Filter</div>
    </div>
    <div class="tabs" id="tabs">
      <button class="tab active" data-filter="all">All</button>
      <button class="tab" data-filter="overdue">Overdue</button>
      <button class="tab" data-filter="critical">Urgent</button>
      <button class="tab" data-filter="warning">Upcoming</button>
      <button class="tab" data-filter="document">Documents</button>
      <button class="tab" data-filter="service">Services</button>
    </div>
    <div class="table-wrap">
      <table class="timeline">
        <thead><tr>
          <th>Vehicle</th><th>Item</th><th>Category</th>
          <th>Expires</th><th>When</th><th>Amount</th>
          <th>Status</th><th>File</th>
        </tr></thead>
        <tbody id="all-tbody"></tbody>
      </table>
    </div>
  </div>

  <footer>
    <div>Built from <code>data/vehicles.yaml</code> · Deployed via GitHub Pages</div>
    <div id="generated-at"></div>
  </footer>
</div>

<script>
const DATA = __DATA__;

// ---- Header
document.getElementById('today').textContent = DATA.generated_display;
document.getElementById('generated-at').textContent = 'Generated ' + DATA.generated_at;

// ---- Stats
const s = DATA.stats;
document.getElementById('s-vehicles').textContent = s.vehicles;
document.getElementById('s-tracked').textContent = s.total_items;
document.getElementById('s-overdue').textContent = s.overdue;
document.getElementById('s-urgent').textContent = s.critical;
document.getElementById('s-upcoming').textContent = s.warning;
document.getElementById('s-spend').textContent = '₹' + (s.annual_spend).toLocaleString('en-IN');

// ---- Alert banner
if (s.overdue + s.critical > 0) {
  const msg = [];
  if (s.overdue) msg.push(s.overdue + ' overdue');
  if (s.critical) msg.push(s.critical + ' urgent (≤7d)');
  document.getElementById('alert-banner-slot').innerHTML = `
    <div class="alert-banner fade-in">
      <div>
        <div class="alert-text">Action required</div>
        <div class="alert-sub">${msg.join(' · ')}</div>
      </div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:12px;letter-spacing:.1em;">See below ↓</div>
    </div>`;
}

// ---- Timeline chart: count per month for next 12 months
(function() {
  const months = [];
  const now = new Date();
  for (let i = 0; i < 12; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() + i, 1);
    months.push({
      key: d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0'),
      label: d.toLocaleString('en-GB', { month: 'short', year: '2-digit' }),
      count: 0,
    });
  }
  DATA.timeline.forEach(item => {
    const k = item.expiry_date.substring(0, 7);
    const m = months.find(x => x.key === k);
    if (m) m.count++;
  });
  new Chart(document.getElementById('chart-timeline'), {
    type: 'bar',
    data: {
      labels: months.map(m => m.label),
      datasets: [{
        data: months.map(m => m.count),
        backgroundColor: months.map(m => m.count > 2 ? '#c1121f' : m.count > 0 ? '#b68a3c' : '#d9d2c5'),
        borderRadius: 2,
        borderSkipped: false,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => c.parsed.y + ' item(s)' } } },
      scales: {
        x: { grid: { display: false }, ticks: { font: { family: 'JetBrains Mono', size: 10 } } },
        y: { beginAtZero: true, ticks: { stepSize: 1, font: { family: 'JetBrains Mono', size: 10 } }, grid: { color: 'rgba(0,0,0,.05)' } },
      }
    }
  });
})();

// ---- Spend chart
(function() {
  const entries = Object.entries(DATA.spend_by_type).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) {
    document.getElementById('chart-spend').parentElement.innerHTML =
      '<div style="color:var(--ink-muted);font-size:13px;padding:40px 0;text-align:center;">No amounts recorded yet</div>';
    return;
  }
  const palette = ['#c1121f', '#e85d04', '#b68a3c', '#0a3d2e', '#4a4640', '#8a857d'];
  new Chart(document.getElementById('chart-spend'), {
    type: 'doughnut',
    data: {
      labels: entries.map(e => e[0]),
      datasets: [{
        data: entries.map(e => e[1]),
        backgroundColor: entries.map((_, i) => palette[i % palette.length]),
        borderColor: 'transparent',
        borderWidth: 2,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '62%',
      plugins: {
        legend: { position: 'bottom', labels: { font: { family: 'Inter', size: 12 }, boxWidth: 10, padding: 12 } },
        tooltip: { callbacks: { label: c => c.label + ': ₹' + c.parsed.toLocaleString('en-IN') } }
      }
    }
  });
})();

// ---- Vehicle cards
(function() {
  const grid = document.getElementById('vehicles-grid');
  document.getElementById('fleet-count').textContent = DATA.vehicles.length + ' vehicle' + (DATA.vehicles.length !== 1 ? 's' : '');
  DATA.vehicles.forEach(v => {
    const itemsHtml = v.items.map(i => `
      <li class="vehicle-item">
        <div class="vi-left">
          <div class="vi-type">${i.type}</div>
          <div class="vi-expiry">${i.expiry_display} · ${i.days_display}</div>
        </div>
        <div class="vi-right">
          <span class="pill u-${i.urgency}">${i.urgency_label}</span>
          ${i.file_link ? `<a class="file-link" href="${i.file_link}" target="_blank" title="Open file">📄</a>` : ''}
        </div>
      </li>`).join('');
    grid.insertAdjacentHTML('beforeend', `
      <div class="vehicle-card urgency-${v.worst_urgency_rank} fade-in">
        <div class="vehicle-head">
          <div class="vehicle-name">${v.name}</div>
          <div class="vehicle-type">${v.type}</div>
        </div>
        <div class="vehicle-reg">${v.registration_number}</div>
        <ul class="vehicle-items">${itemsHtml}</ul>
      </div>`);
  });
})();

// ---- Personal docs
(function() {
  if (DATA.personal.length === 0) return;
  document.getElementById('personal-section').style.display = '';
  const tbody = document.getElementById('personal-tbody');
  DATA.personal.forEach(i => {
    tbody.insertAdjacentHTML('beforeend', `
      <tr>
        <td class="td-vehicle">${i.type}</td>
        <td>${i.vehicle_name}</td>
        <td class="td-date">${i.expiry_display}<div class="td-days">${i.days_display}</div></td>
        <td><span class="pill u-${i.urgency}">${i.urgency_label}</span></td>
        <td>${i.file_link ? `<a class="file-link" href="${i.file_link}" target="_blank">📄</a>` : '—'}</td>
      </tr>`);
  });
})();

// ---- All items table + filtering
(function() {
  const tbody = document.getElementById('all-tbody');
  function render(filter) {
    let rows = DATA.all_items;
    if (filter === 'document' || filter === 'service') {
      rows = rows.filter(r => r.category === filter);
    } else if (filter !== 'all') {
      rows = rows.filter(r => r.urgency === filter);
    }
    if (rows.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:40px;color:var(--ink-muted);">Nothing to show here.</td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map(i => `
      <tr>
        <td class="td-vehicle">${i.vehicle_name}</td>
        <td>${i.type}${i.provider ? ` <span style="color:var(--ink-muted);font-size:12px;">· ${i.provider}</span>` : ''}</td>
        <td style="color:var(--ink-muted);font-size:12px;text-transform:capitalize;">${i.category}</td>
        <td class="td-date">${i.expiry_display}</td>
        <td class="td-days">${i.days_display}</td>
        <td class="td-date">${i.amount ? '₹' + Number(i.amount).toLocaleString('en-IN') : '—'}</td>
        <td><span class="pill u-${i.urgency}">${i.urgency_label}</span></td>
        <td>${i.file_link ? `<a class="file-link" href="${i.file_link}" target="_blank">📄</a>` : '—'}</td>
      </tr>`).join('');
  }
  render('all');
  document.querySelectorAll('#tabs .tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('#tabs .tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      render(tab.dataset.filter);
    });
  });
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build_dashboard()
