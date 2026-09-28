# Gmail connector setup (LinkedIn / Indeed job alerts)

**Status: written against Google's official Gmail API, but NOT tested end-to-end in this
build** (no real Google Cloud project or Gmail login was available in the sandbox this was
built in). Read `connector_test_report.md` before relying on it. Everything below is the exact
setup process either way — it's genuinely more involved than the other connectors, and it's
entirely optional. The rest of the app works fully without it.

Your Gmail **password is never used anywhere in this project**. Google's own OAuth consent
screen (a page on accounts.google.com, not this app) is what you log into.

## Why this exists

LinkedIn and Indeed don't have a public job-search API you're allowed to use, and this project
explicitly refuses to scrape their logged-in pages. The one sanctioned path is: you already get
"new jobs matching your search" alert emails from both — point a dedicated Gmail label at them,
and let this app read (never send, never delete) just those labelled emails through Google's own
official Gmail API.

## Option 1 — Personal use (recommended, ~10 minutes, once)

1. **Create a Google Cloud project.** Go to [console.cloud.google.com](https://console.cloud.google.com) → create a new project (any name, e.g. "job-radar-personal").
2. **Enable the Gmail API.** In the project, go to "APIs & Services" → "Library" → search "Gmail API" → Enable.
3. **Configure the OAuth consent screen.** "APIs & Services" → "OAuth consent screen" → User type **External** → App name "Job Radar (personal)" → your own email as support/developer contact → Save.
   - Under "Test users", add your own Gmail address. This keeps the app in "Testing" mode, which is fine for personal use and doesn't require Google's app-verification review.
4. **Create OAuth credentials.** "APIs & Services" → "Credentials" → "Create Credentials" → "OAuth client ID" → Application type **Desktop app** → name it anything → Create.
5. **Download the JSON.** Click the download icon next to the credential you just created → save the file as `credentials.json` in this project's folder.
6. **Create two Gmail labels** in your own Gmail (Settings → Labels → "Create new label"):
   - `JOB-ALERTS/LinkedIn`
   - `JOB-ALERTS/Indeed`
7. **Create two Gmail filters** (Settings → Filters and Blocked Addresses → "Create a new filter") that apply those labels automatically:
   - From contains `jobalerts-noreply@linkedin.com` → apply label `JOB-ALERTS/LinkedIn`
   - From contains `indeedapply@indeed.com` (or `alert@indeed.com`, check your own inbox for the exact sender) → apply label `JOB-ALERTS/Indeed`
8. **Turn the connector on.** In `.env` (or Streamlit Cloud Secrets):
   ```
   ENABLE_GMAIL_CONNECTOR=1
   GMAIL_CREDENTIALS_JSON=credentials.json
   ```
9. **First run.** The first time the app tries to fetch Gmail, it opens a browser window asking you to log in with your Google account and approve **read-only** access ("View your email messages and settings"). Approve it. A `token.json` is saved locally so you won't be asked again.

## Option 2 — If you want a second person to test it ("test user")

Same steps as Option 1, but add their Gmail address under "Test users" in step 3 too (up to 100
test users are allowed without Google's review). They each get their own `token.json` when they
log in on their own machine — never share a token.json between people.

## What this connector will and won't do

- Reads only messages under the two labels above. It never reads your whole inbox.
- Never applies, removes, or modifies any Gmail label itself (read-only scope can't do that) —
  instead it remembers which message IDs it already processed in the local `job_radar.db` file,
  so the same email is never re-imported.
- Never deletes your email, and never touches any message outside those two labels.
- Splits each alert email into one record per individual job listing it can find a distinct job
  link for. If it can't confidently tell jobs apart in a given email's layout, it shows
  "Unable to extract individual jobs from this LinkedIn/Indeed alert format" instead of
  guessing or importing the whole email as one fake "job".

## Revoking access / deleting data

- **Disconnect Gmail** button (in the app's "Filtri e fonti" panel) deletes the local
  `token.json` — after that, this app can't read your Gmail again until you log in once more.
- **Delete dati email importati** button clears the local list of "already processed" message
  IDs (it never stored the email content itself, only IDs).
- To fully revoke this app's access to your Google account: go to
  [myaccount.google.com/permissions](https://myaccount.google.com/permissions), find the app
  name you chose in step 3, and click "Remove access".
- Delete `credentials.json` and `token.json` from the project folder to remove all local traces.

## If it stops working

- "non configurato" → `ENABLE_GMAIL_CONNECTOR` isn't `1`, or `credentials.json` is missing.
- Browser doesn't open for login → you're likely running this on a server (e.g. Streamlit Cloud)
  where `flow.run_local_server()` can't open a local browser. The Gmail connector is designed for
  **local** use (Option C in `README_MOBILE_FIRST.md`) for this reason — generate `token.json`
  once on your own computer, then you could copy it into Streamlit Cloud's secrets if you really
  want the deployed version to use it too, but this was not tested in this build.
- "etichetta ... non trovata" → the label name in Gmail doesn't exactly match
  `JOB-ALERTS/LinkedIn` / `JOB-ALERTS/Indeed` (case-insensitive, but the slash matters).
