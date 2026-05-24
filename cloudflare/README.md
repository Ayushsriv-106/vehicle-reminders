# Gated dashboard on Cloudflare Pages (auto-deployed from GitHub)

The dashboard is hosted on **Cloudflare Pages**, behind one **shared ID + password**,
with **upload/download** of document scans stored in Cloudflare **KV**.

**You do NOT click through the Cloudflare Pages UI.** GitHub Actions builds the
site (reusing the `SHEET_CSV_URL` already in the repo) and deploys it to Cloudflare
with `wrangler` on every push and once a day. You just provide a token + a few
secrets, one time.

## One-time setup (~5 minutes)

Already done for you: the KV namespace **`garage-docs`**
(`id f1d8fa7f5b3542bdaccc25fe7d183a6f`) exists and is referenced in
[`wrangler.toml`](../wrangler.toml). Account ID is `49e5cf64cedbc22dec20ee3684269970`.

### 1. Create a Cloudflare API token
Cloudflare dashboard → **My Profile → API Tokens → Create Token → Create Custom Token**:
- **Permissions** (add both rows):
  - `Account` · `Cloudflare Pages` · **Edit**
  - `Account` · `Workers KV Storage` · **Edit**
- **Account Resources**: Include → your account.
- Create, then **copy the token** (shown once).

### 2. Add GitHub repo secrets + a variable
Repo → **Settings → Secrets and variables → Actions**.

**Secrets** (New repository secret):
| Name | Value |
|------|-------|
| `CLOUDFLARE_API_TOKEN` | the token from step 1 |
| `AUTH_USER` | the shared username (e.g. `fleet`) |
| `AUTH_PASS` | the shared password (e.g. `Garage-Reoti-7K9m`) |

**Variables** (the Variables tab — not secret):
| Name | Value |
|------|-------|
| `CLOUDFLARE_ACCOUNT_ID` | `49e5cf64cedbc22dec20ee3684269970` |

### 3. Run it
**Actions → Vehicle Reminders → Run workflow** (or just push any commit). The job:
builds the dashboard → creates the `garage-fleet` Pages project (first run) →
sets the `AUTH_USER`/`AUTH_PASS` login → deploys assets + the Functions, with the
`DOCS` KV binding from `wrangler.toml`.

Your site goes live at **`https://garage-fleet.pages.dev`** and asks for the
ID/password. Log in → view the fleet, upload/download scans on any paper.

### 4. Lock down the old public copy
The previous GitHub Pages site is unauthenticated. Disable it:
**repo Settings → Pages → Build and deployment → Source → None**.
(The email now links to the Cloudflare site by default.)

## How it works
- `functions/_middleware.js` — gates every request with the shared ID/password.
- `functions/api/files.js` — upload/download/list, backed by the `DOCS` KV namespace.
- The dashboard calls `/api/files` (same origin), so the login also protects uploads.
- `.github/workflows/reminders.yml` builds with `DOC_API_URL=/api/files` and deploys
  via `wrangler pages deploy` on push + daily cron.

## Notes
- Each scan is stored as base64 in KV; **max ~12 MB per file** (enforced in the UI).
- Rotate the password: change the `AUTH_PASS` secret and re-run the workflow.
- Custom domain: add it in the Pages project, then set the `DASHBOARD_URL` repo
  variable so the email links to it.
- If the `DOCS` KV binding ever doesn't apply, bind it once in the Pages project
  (Settings → Bindings → KV → `DOCS` → `garage-docs`); the workflow keeps it after.
