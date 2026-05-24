# vehicle-reminders

Automated vehicle document reminders — a live dashboard plus a deliberately quiet email nudge.

**Dashboard:** https://ayushsriv-106.github.io/vehicle-reminders/
The dashboard is the source of truth. It rebuilds and redeploys every day and always shows the full picture — every vehicle, every document, overdue items in red.

It includes:
- **Fleet grouping** by owner (GJMS School / G.B. Automobiles / Family & Personal), with search and per-fleet / per-status filters.
- **Compliance rings + gap flags** — each vehicle shows how many of its *legally required* papers are on record (cars: Insurance/PUC/RC; commercial: + Fitness/Permit/Road Tax), and a "Compliance gaps" section lists every missing paper.
- **Data review** — an automated record check flags placeholder registrations, missing owners, stale notes, generic names and missing premium amounts, colour-coded by severity.
- **Document locker** — upload a scan to any paper and download it later.
- **Renewal calendar (.ics)** export and a print/PDF view.

## Hosting & team access

Two ways to host it:

1. **GitHub Pages** (public, read-only) — the default; the workflow deploys here.
2. **Cloudflare Pages** (recommended for teams) — puts the whole dashboard behind a **shared ID + password** and enables **upload/download** of scans, stored in Cloudflare KV. Set-up: [cloudflare/README.md](cloudflare/README.md). The Cloudflare Functions live in [`functions/`](functions/).

Either way the data pipeline and reminder email stay on GitHub Actions.

## How reminders work

Data lives in a Google Sheet (published as CSV, wired in via the `SHEET_CSV_URL` secret). A GitHub Actions job runs daily, rebuilds the dashboard, and sends **at most one summary email** — but only on a handful of days around each expiry, so it never turns into daily spam:

- **Before expiry:** `reminder_days` — emails on 14, 7, 3, 1 and 0 days before.
- **After expiry:** `overdue_reminder_days` — a short ramp of nudges on 1, 3, 7, 14 and 30 days overdue.
- **Chronically overdue:** `overdue_monthly_after_days` — past this many days overdue (30), a low-frequency "still overdue" heartbeat fires every 30 days (60, 90, 120 …) so a real lapse is never forgotten.

Nothing is ever emailed daily. On days when no item is in any of those windows, no email is sent at all. To make chronic items go *fully silent* (dashboard only) instead of the monthly heartbeat, set `overdue_monthly_after_days` to `null`.

Tune the cadence in the `settings` block — either the Google Sheet defaults (`scripts/sheet_loader.py` → `DEFAULT_SETTINGS`) or the `data/vehicles.yaml` fallback.

## Layout

| Path | Purpose |
|------|---------|
| `scripts/core.py` | Data model + reminder-selection logic (`items_needing_email`) |
| `scripts/send_reminders.py` | Builds and sends the summary email |
| `scripts/build_dashboard.py` | Builds `docs/index.html` (deployed to GitHub Pages) |
| `scripts/sheet_loader.py` | Fetches the Google Sheet CSV → config |
| `scripts/test_core.py` | Tests for the reminder-selection rules |
| `data/vehicles.yaml` | Fallback data + default settings (sheet wins when configured) |
| `.github/workflows/reminders.yml` | Daily cron, dashboard build, email, Pages deploy |
| `functions/_middleware.js` | Cloudflare shared ID/password gate |
| `functions/api/files.js` | Cloudflare upload/download/list API (KV-backed) |
| `cloudflare/README.md` | Cloudflare Pages hosting + login setup (recommended) |
| `apps-script/` | Alternative locker backend (Google Drive) if not using Cloudflare |

## Run locally

```bash
pip install -r requirements.txt

# Run the tests
python scripts/test_core.py

# Build the dashboard from the YAML fallback (no sheet needed)
python scripts/build_dashboard.py   # writes docs/index.html
```

`docs/` is generated and git-ignored — CI rebuilds it from the live sheet on every run.

## Secrets / variables

Set in the repo's Actions secrets:

- `SHEET_CSV_URL` — published Google Sheet CSV link
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO` — mail delivery
- `DASHBOARD_URL` *(optional variable)* — link used in the email button; falls back to the GitHub Pages URL if unset.
- `DOC_API_URL`, `DOC_API_TOKEN` *(optional variables)* — the Apps Script web-app URL + token for the document locker. Without them, Upload buttons are shown disabled. See [apps-script/README.md](apps-script/README.md).
