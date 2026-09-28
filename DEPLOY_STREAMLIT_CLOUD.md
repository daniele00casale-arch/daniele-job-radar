# Deploying to Streamlit Community Cloud — exact, no-code steps

**I cannot do this step for you.** Deploying requires your own GitHub account and your own
Streamlit Community Cloud account (Streamlit Cloud deploys by reading a repository from your
GitHub), and I don't have credentials or access to either. Nothing here ever asks you to paste a
password or token into chat — both platforms authenticate through their own official login
screens, in your own browser. If you'd rather not do even this, use `job_radar_fallback.html`
(Option B in `README_MOBILE_FIRST.md`) instead — zero deployment required.

Everything below can be done from a phone browser. It takes about 5 minutes the first time.

---

## Step 1 — Create a GitHub account (skip if you already have one)

1. Go to [github.com](https://github.com) → **Sign up**.
2. Follow the prompts (email, username, password). GitHub is free for this.

## Step 2 — Create a new repository and upload the project files

1. Once logged in, tap the **+** icon (top right) → **New repository**.
2. Name it something like `daniele-job-radar`. Leave it **Public** (Streamlit Community Cloud's
   free tier deploys public repos) or **Private** if your plan allows it. Do **not** tick
   "Add a README" — we already have one.
3. Tap **Create repository**.
4. On the new (empty) repository page, tap **uploading an existing file** (a blue link in the
   middle of the page).
5. From your phone's file picker, select **every file and folder from this project** (unzip the
   ZIP first if you downloaded it as one) — including the hidden `.streamlit` folder and
   `requirements.txt`. Most phone browsers let you multi-select files to drag in.
   - If your phone's uploader won't let you upload the `.streamlit` folder as a folder, create it
     manually instead: on the repo page, tap **Add file → Create new file**, type
     `.streamlit/config.toml` as the filename (the slash creates the folder automatically), then
     paste in the contents of that file from this project.
6. Scroll down, add a short commit message like "initial upload", and tap **Commit changes**.

Your repository now contains `app.py`, `connectors.py`, `ats_connectors.py`, `scoring.py`, `db.py`,
`email_parser.py`, `gmail_connector.py`, `config.yaml`, `requirements.txt`,
`.streamlit/config.toml`, and the rest.

## Step 3 — Create a Streamlit Community Cloud account

1. Go to [share.streamlit.io](https://share.streamlit.io).
2. Tap **Sign up** (or **Continue with GitHub**) and log in with the **same GitHub account** from
   Step 1. This is where the two platforms link — through GitHub's own official OAuth screen, not
   through anything you type here.
3. Approve the permission screen GitHub shows you (this lets Streamlit Cloud read your
   repositories so it can deploy from them — it does not give it your password).

## Step 4 — Deploy

1. On the Streamlit Cloud dashboard, tap **New app** (sometimes labelled **Create app**).
2. Choose **"From existing repo"** (or similar wording).
3. Pick:
   - **Repository:** the `daniele-job-radar` repo you just created
   - **Branch:** `main` (the default)
   - **Main file path:** `app.py`
4. Tap **Deploy**.
5. Wait 1-3 minutes while it installs `requirements.txt` and starts the app. You'll see build logs
   scroll by — that's normal.
6. When it's done, you get a URL like `https://daniele-job-radar.streamlit.app`. That's your
   dashboard, live on the internet, reachable from any phone or computer, no installation needed
   on the visiting device.

## Step 5 (optional) — Turn on Adzuna or the Gmail connector

Only if you want these optional sources active on the deployed version:

1. On the Streamlit Cloud app's page, tap the **⋮** menu → **Settings** → **Secrets**.
2. Paste in, in this format (this is Streamlit Cloud's own secure secrets storage — it is not
   visible in your public repo, and it's the same idea as the `.env` file used when running
   locally):
   ```
   ADZUNA_APP_ID = "your-app-id"
   ADZUNA_APP_KEY = "your-app-key"
   ADZUNA_COUNTRY = "it"
   ```
3. Save. The app restarts automatically and picks up the new values.

The Gmail connector additionally needs a `credentials.json` OAuth file and a first-time interactive
login (see `gmail_connector.py`) — this is genuinely more involved and, as noted in
`test_report.md`, has not been tested end to end in this build. Adzuna is the simpler of the two
optional sources to turn on.

## Updating the app later

Whenever you want to change something (e.g. edit `config.yaml` to tune the scoring), edit the
file directly on GitHub's website (tap the file → pencil icon → edit → commit) — Streamlit Cloud
detects the change and redeploys automatically within a minute or two. No re-upload of the whole
project needed.

## If deployment fails

The build log on Streamlit Cloud will show the exact error. The most common one for this project
would be a missing package in `requirements.txt` — everything this app needs is already listed
there, so this shouldn't come up, but if it does, the error message names the missing package and
you add it to `requirements.txt` on GitHub the same way as any other edit.
