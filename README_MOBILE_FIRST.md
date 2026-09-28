FASTEST WAY TO USE THIS APP FROM YOUR PHONE

You don't need to touch Python, a terminal, or a virtual environment. Two options, fastest first.

## Option A — Put it online in ~5 minutes (recommended, works from your phone browser)

I could not deploy this for you directly: I don't have access to your GitHub account or your
Streamlit Community Cloud account, and I never ask for passwords or tokens in chat. What I *did*
do is prepare every file so the deploy itself is just clicking buttons on two websites. Full exact
steps (with what each screen looks like) are in **`DEPLOY_STREAMLIT_CLOUD.md`** — the short version:

1. On [github.com](https://github.com), create a new repository and drag-and-drop every file from
   this project into it (GitHub's web uploader works fine from a phone browser).
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with that same GitHub account,
   click "New app", pick your repository, and set the main file to `app.py`.
3. Click "Deploy". A minute or two later you get a public link (`https://your-app.streamlit.app`)
   that opens the dashboard on your phone, or anyone's, like any website.

Nobody needs a password from you for this — GitHub and Streamlit Cloud authenticate each other
through their own account linking, not through anything you type into a chat.

## Option B — Open the single HTML file, no deployment at all

Open **`job_radar_fallback.html`** directly from your phone (download it, then open it with your
browser — or email it to yourself and tap it). It runs entirely inside that one page: no install,
no server, nothing to deploy. It has the same Diamond/Gold/Silver logic as the full app.

**Honest limit:** a couple of the job sources (mainly Remotive, sometimes others) don't allow a
web page to call them directly from a phone/desktop browser for security reasons on their end
(this is called a CORS restriction, and it's on their server, not something this project can turn
off). When that happens, the page tells you plainly which source didn't respond and still shows
you everything the other sources returned. For guaranteed access to all 4 sources every time, use
Option A or Option C.

## Option C — Run it on a Windows PC (if you have one nearby)

Double-click **`start_job_radar.bat`**. First time only, it installs everything itself (needs
Python — the script tells you exactly how to get it if it's missing, no technical knowledge
needed). After that, it opens the dashboard in your normal browser every time you double-click it.

---

## What this app actually does

It pulls job listings from 4 free public sources — Himalayas, Arbeitnow, Remotive, and We Work
Remotely — and optionally two more if you set them up later (Adzuna, and a Gmail connector for
LinkedIn/Indeed alert emails — both are advanced/optional, see below). It then sorts every listing
into one of these buckets, and never fudges a hard rule to make something look better than it is:

- 💎 **Diamond** — genuinely worldwide remote (explicit evidence, not just the word "remote"),
  junior/entry-level (max 1 year, 2 only if explicitly "preferred"), paid ≥ €40,000/year.
- 🥇 **Gold** — based in/near Ticino or reachable from Milan, junior/entry-level, paid.
- 🥈 **Silver** — remote from Italy or Europe (Italy explicitly eligible), junior/entry-level, paid ≥ €40,000/year (or ≥90% compatibility if salary isn't published).
- 🎓 **Strategic Internships** — only the internships that are actually worth your time.
- ⏱️ **High-Value Part-Time** — real part-time roles with a stated hourly rate ≥ €/$25 and guaranteed hours.
- Plus dedicated views for **New Today**, **Watchlist Companies**, **Salary Not Disclosed**,
  **Remote Arrangement to Verify**, and your own **Applied / Interviewing / Rejected / Archived**
  pipeline, plus **Filtered Out with Reasons** so you can see exactly why something didn't make it.

Every card shows: title, company, location restrictions, salary (or "Salary not disclosed" — never
a made-up number), contract type, experience required, compatibility score with the reason behind
it, and the original application link. You can save a job, mark it applied/interviewing/
rejected/archived, add a note, copy a one-line summary, or export everything to CSV — all from
your phone.

## The 4 mandatory rules that are ALWAYS on (you can't turn these off, on purpose)

- Paid roles only — no unpaid, volunteer, equity-only or commission-only listings.
- A high compatibility score never overrides a hard rule: a 95%-matching senior role is still excluded from Diamond/Gold if it needs 5+ years.
- "Remote" alone never counts as worldwide — the description has to say so explicitly (or list a country restriction, which excludes it).
- Nothing missing is ever invented. If salary isn't published, you'll see "Salary not disclosed" — never a guessed number.

## Files in this project

| File | What it's for |
|---|---|
| `app.py`, `connectors.py`, `scoring.py`, `db.py`, `email_parser.py` | The Streamlit dashboard itself |
| `gmail_connector.py` | Optional, advanced, **untested in this build** — see the file's own docstring before using it |
| `config.yaml` | Your candidate profile, scoring weights, tier rules — edit this to tune the app |
| `requirements.txt` | What Streamlit Cloud (or your own machine) installs automatically |
| `start_job_radar.bat` | Windows one-click launcher |
| `job_radar_fallback.html` | The no-install single-page version |
| `DEPLOY_STREAMLIT_CLOUD.md` | Exact phone-friendly deployment steps |
| `test_report.md` | Exactly what was tested, how, and what's still unverified — no function is claimed to work without this |
| `.env.example` | Copy to `.env` to turn on the optional Adzuna/Gmail connectors |

## Turning on the optional sources (Adzuna, Gmail) — later, not required

Both are off by default and the app works fully without them. Adzuna needs a free API key from
adzuna.com/developer. The Gmail connector needs a Google Cloud OAuth setup and has **not been
tested end-to-end** in this build (no test Gmail account was available) — read the top of
`gmail_connector.py` before relying on it. Neither ever asks for your email password: Adzuna uses
an API key you paste into `.env`, and Gmail uses Google's own sign-in screen, never a password
typed anywhere in this project's files or in chat.

## If something looks wrong

Check `test_report.md` first — it lists exactly what was verified and what wasn't in this build.
If a job seems miscategorised, open it and read the "Condizioni obbligatorie riscontrate" /
"Motivi" lines on its card: the app always explains its own reasoning, so you can see exactly
which rule put it where it is.
