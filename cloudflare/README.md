# Host the gated dashboard on Cloudflare Pages

This puts the dashboard behind one **shared ID + password** and turns on
**upload/download** of document scans (stored in Cloudflare KV). Your data
pipeline and the reminder email stay on GitHub Actions — only the *hosting +
login + uploads* move here. ~15 minutes, one time.

## What you get
- `https://garage-fleet.pages.dev` (or your domain) asking for an ID/password.
- Team members enter the shared login once; they can then **view and upload**
  scans on any paper.
- Files live in Cloudflare KV; links also flow into the dashboard.

---

## 1. Create the KV namespace (file storage)
Cloudflare dashboard → **Workers & Pages → KV → Create namespace** → name it
`garage-docs`. (No credit card needed.)

## 2. Create the Pages project (Git integration)
1. **Workers & Pages → Create → Pages → Connect to Git** → pick the
   `vehicle-reminders` repo.
2. Build settings:
   - **Framework preset:** None
   - **Build command:** `pip install -r requirements.txt && python scripts/build_dashboard.py`
   - **Build output directory:** `docs`
3. **Save and Deploy** (the first build may warn about missing env vars — that's
   fine, we add them next).

## 3. Bind KV + set variables
In the new Pages project → **Settings**:

**Functions → KV namespace bindings → Add binding**
| Variable name | KV namespace |
|---|---|
| `DOCS` | `garage-docs` |

**Variables and Secrets** (Production) — add:
| Name | Value | Type |
|---|---|---|
| `AUTH_USER` | the shared username you want | Secret |
| `AUTH_PASS` | the shared password you want | Secret |
| `DOC_API_URL` | `/api/files` | Plaintext |
| `SHEET_CSV_URL` | your published Google Sheet CSV link | Secret |

Then **Deployments → Retry deployment** so the build picks up the variables.

> Keep `AUTH_USER` / `AUTH_PASS` ASCII (plain letters/numbers). They gate the
> whole site, including uploads.

## 4. Daily refresh (keeps "days left" current)
Pages → **Settings → Builds & deployments → Deploy hooks → Add deploy hook**
(branch `main`). Copy the URL, then in **GitHub → repo Settings → Secrets and
variables → Actions → Variables**, add:
| Name | Value |
|---|---|
| `CF_DEPLOY_HOOK` | the deploy-hook URL |

The daily GitHub Actions run will now ping it so Cloudflare rebuilds with fresh
dates. (`.github/workflows/reminders.yml` already has this step.)

## 5. Point the reminder email at the new site
GitHub repo **Variables** → set `DASHBOARD_URL` to your Pages URL
(e.g. `https://garage-fleet.pages.dev`). The daily email button now opens the
gated dashboard.

## 6. Turn off the old public site
The old GitHub Pages site is unauthenticated. Once Cloudflare works:
**repo Settings → Pages → Source → None** (or delete the `deploy-pages` job).

---

## How it works
- `functions/_middleware.js` — checks the shared ID/password on every request
  (the browser's native login prompt). Nothing is served without it.
- `functions/api/files.js` — the locker API, backed by the `DOCS` KV namespace:
  - `GET /api/files` → list of uploaded files
  - `GET /api/files?get=<key>` → streams a file
  - `POST /api/files` → upload / delete
- The dashboard calls `/api/files` (same origin), so the shared login also
  protects uploads — no separate token needed.

## Notes & limits
- KV stores each scan as base64; **max ~12 MB per file** (the upload button
  enforces this). Plenty for PDFs/photos of documents.
- To rotate the password: change `AUTH_PASS` and redeploy.
- `wrangler.toml` in the repo root mirrors this config if you prefer
  `wrangler pages deploy` over Git integration.
- This replaces the Google Apps Script option in `apps-script/` — you only need
  one. Cloudflare is the chosen path; `apps-script/` is kept as an alternative.
