# Document locker — Apps Script setup

This connects the dashboard's **Upload / Download** buttons to Google Drive.
Scans are stored in a Drive folder, indexed in a `DocFiles` tab of your fleet
sheet, and the link is written back into the matching `*_file` column so it also
flows into the daily rebuild. One-time setup, ~5 minutes.

## 1. Create the web app
1. Open your **fleet Google Sheet** → **Extensions → Apps Script**.
2. Delete the default `Code.gs` contents and paste in everything from
   [`Code.gs`](Code.gs).
3. At the top, change `TOKEN` to any long random string (e.g. a password-manager
   value). Remember it for step 3.
4. **Save** (disk icon).

## 2. Deploy
1. Click **Deploy → New deployment**.
2. Gear icon → **Web app**.
3. Set **Execute as: Me**, **Who has access: Anyone**.
4. **Deploy** → authorize when prompted (it needs Drive + Sheets access; this is
   your own script acting on your own files).
5. Copy the **Web app URL** — it ends in `/exec`.

## 3. Point the dashboard at it
In the GitHub repo **Settings → Secrets and variables → Actions → Variables**,
add two **repository variables**:

| Name | Value |
|------|-------|
| `DOC_API_URL` | the `/exec` URL from step 2 |
| `DOC_API_TOKEN` | the same `TOKEN` string from step 1 |

Then trigger a rebuild: **Actions → Vehicle Reminders → Run workflow**, or push
any commit. The dashboard now shows working Upload buttons.

## 4. Use it
- **Upload**: on any paper, click **⬆ Upload**, pick a PDF/photo. It saves to
  Drive and the button turns into **⬇ File**.
- **Download / view**: click **⬇ File** to open the scan.
- Files live in Drive under **"Vehicle Documents (The Garage)"**, one subfolder
  per vehicle. You can also drop files there manually.

## Security notes
- The dashboard is a public page, so the `DOC_API_URL` and `DOC_API_TOKEN` are
  visible in its source. The token only deters drive-by bots, not a determined
  viewer. Uploaded files are shared as **"anyone with the link"** (needed so the
  download button works without a Google login).
- If you want this private, password-gate the GitHub Pages site (e.g. via
  Cloudflare Access in front of it) — the API already refuses uploads without
  the token.
- To rotate the token: change `TOKEN`, redeploy (**Deploy → Manage deployments →
  edit → new version**), and update the `DOC_API_TOKEN` variable.
