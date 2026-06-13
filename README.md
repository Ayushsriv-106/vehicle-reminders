# vehicle-reminders

Fleet document register — a clean, professional live dashboard plus a hands-free, ready-to-post WhatsApp reminder.

**Dashboard (live, gated):** https://garage-fleet.pages.dev/
The dashboard is the source of truth. It rebuilds and redeploys every day and always shows the full picture — every vehicle, every document, with a calm, business-like light UI where **colour is only used to signal status** (red = overdue, amber = due soon, green = valid).

It includes:
- **WhatsApp reminder** — the dashboard auto-composes the exact Hindi/Hinglish message for the "Car papers" group (overdue + due-soon + missing papers) with one-tap **Share to WhatsApp** and **Copy**. The same message is emailed to you each morning, ready to post (see below).
- **Fleet grouping** by owner (GJMS School / G.B. Automobiles / Family & Personal), with search and per-fleet / per-status filters.
- **Compliance rings + missing-document flags** — each vehicle shows how many of its *legally required* papers are on record (cars: Insurance/PUC/RC; commercial: + Fitness/Permit/Road Tax), and a "Missing documents" section lists every gap, worst first.
- **Data review** — an automated record check flags placeholder/duplicate registrations, lapsed insurance, missing owners, stale notes, generic names and missing premium amounts, by severity.
- **Document locker** — upload a scan to any paper and download it later.
- **Renewal calendar (.ics)** export and a print/PDF view.

## Hosting & team access

The dashboard is hosted on **Cloudflare Pages**, behind a **shared ID + password**,
with working **upload/download** of scans (stored in Cloudflare KV). GitHub Actions
builds it and deploys via `wrangler` on every push + daily — no Cloudflare UI
click-through. One-time setup (an API token + a few secrets): [cloudflare/README.md](cloudflare/README.md).
The login + upload Functions live in [`functions/`](functions/).

## Hands-free WhatsApp reminders

WhatsApp does not let any app/API post into a *group* — that final Send is always one human tap. So "hands-free" means the system does everything *up to* that tap:

1. The daily GitHub Actions job rebuilds the dashboard and runs `scripts/send_reminders.py`.
2. That script composes the ready-to-post "Car papers" message (overdue → due-soon → missing papers, in Hinglish) and **emails it to you** with a big **Share to WhatsApp** button.
3. You tap the button → WhatsApp opens with the message pre-filled → pick the **Car papers** group → Send.

It is deliberately **quiet** — it does *not* email every day (the 45 missing papers would otherwise nag forever):

- **Before expiry:** `reminder_days` — fires on 14, 7, 3, 1 and 0 days before.
- **After expiry:** `overdue_reminder_days` — a short ramp on 1, 3, 7, 14 and 30 days overdue.
- **Chronically overdue:** `overdue_monthly_after_days` — past 30 days overdue, a monthly "still overdue" heartbeat (60, 90, 120 …).
- **Missing papers:** a single weekly nudge (Mondays) so chronic gaps surface without daily spam.

On any other day nothing is sent. The dashboard always shows the full picture and has the same Share/Copy buttons for posting on demand. Tune the cadence in the `settings` block (`scripts/sheet_loader.py` → `DEFAULT_SETTINGS`, or the `data/vehicles.yaml` fallback).

## Layout

| Path | Purpose |
|------|---------|
| `scripts/core.py` | Data model + reminder-selection logic (`items_needing_email`) |
| `scripts/send_reminders.py` | Builds the WhatsApp message + emails it to you ready-to-post |
| `scripts/build_dashboard.py` | Builds `docs/index.html` (clean light UI, deployed to Cloudflare Pages) |
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
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM` — mail delivery for the WhatsApp-ready reminder
- `WA_REMINDER_TO` *(optional)* — who receives the ready-to-post email (defaults to the owner's address). Single recipient by design.

For the Cloudflare deploy (see [cloudflare/README.md](cloudflare/README.md)):
- `CLOUDFLARE_API_TOKEN` *(secret)*, `AUTH_USER` *(secret)*, `AUTH_PASS` *(secret)* — deploy token + the shared login.
- `CLOUDFLARE_ACCOUNT_ID` *(variable)* — enables the deploy step.
- `DASHBOARD_URL` *(optional variable)* — link used in the email button; defaults to the Cloudflare site.
