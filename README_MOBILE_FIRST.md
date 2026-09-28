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

It pulls job listings from 6 free public sources with zero setup — Himalayas, Arbeitnow,
Remotive, We Work Remotely, The Muse, and Remote OK — plus direct connectors to 3 watchlist
companies' own career pages (Canonical, GitLab, Camunda), and optionally more if you set them up
later: Adzuna, Jooble, more watchlist companies, and a Gmail connector for LinkedIn/Indeed alert
emails (all advanced/optional — see `CONNECTOR_SETUP.md`, `COMPANY_WATCHLIST_SETUP.md`,
`GMAIL_OAUTH_SETUP.md`). It then sorts every listing into one of these buckets, and never fudges
a hard rule to make something look better than it is — but it also no longer silently drops a
strong role just because ONE fact (salary, or remote scope) wasn't published: that's now a
**Potential** version of the same tier, clearly labelled, instead of disappearing:

- 💎 **Diamond** / 💎 **Potential Diamond** — genuinely worldwide remote (explicit evidence, not
  just the word "remote"), junior/entry-level (max 1 year, 2 only if explicitly "preferred"),
  paid ≥ €40,000/year. Potential Diamond = every condition met except salary and/or remote scope
  weren't explicitly confirmed either way.
- 🥇 **Gold** / 🥇 **Potential Gold** — based in/near Ticino or reachable from Milan,
  junior/entry-level, paid. Potential Gold = same, but salary wasn't published.
- 🥈 **Silver** / 🥈 **Potential Silver** — remote from Italy or Europe (Italy explicitly
  eligible), junior/entry-level, paid ≥ €40,000/year (or ≥90% compatibility if salary isn't published).
- 🎓 **Strategic Internships** — only the internships that are actually worth your time.
- ⏱️ **High-Value Part-Time** — real part-time roles with a stated hourly rate ≥ €/$25 and guaranteed hours.
- Plus dedicated views for **New Today**, **Company Watchlist**, **Watchlist Matches Not
  Qualified**, **Salary Not Disclosed**, **Remote Scope to Verify**, **Experience to Verify**,
  your own **Applied / Interviewing / Rejected / Archived** pipeline, **Filtered Out with
  Reasons**, **Connector Status** (which sources worked, failed, or aren't configured — this is
  the first place to check if you see fewer positions than expected), **Parsing Failures**, and a
  full **Diagnostic Report** (every collected job with the fields it had, the fields it was
  missing, and exactly which rule accepted or rejected it).

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
| `app.py`, `connectors.py`, `ats_connectors.py`, `scoring.py`, `db.py`, `email_parser.py` | The Streamlit dashboard itself |
| `gmail_connector.py` | Optional, advanced, **untested end-to-end in this build** — see `GMAIL_OAUTH_SETUP.md` before using it |
| `config.yaml` | Your candidate profile, scoring weights, tier rules, watchlist + ATS wiring — edit this to tune the app |
| `requirements.txt` | What Streamlit Cloud (or your own machine) installs automatically |
| `start_job_radar.bat` | Windows one-click launcher |
| `job_radar_fallback.html` | The no-install single-page version (same Diamond/Gold/Silver + Potential logic) |
| `DEPLOY_STREAMLIT_CLOUD.md` | Exact phone-friendly deployment steps |
| `CONNECTOR_SETUP.md` | How to turn on Adzuna/Jooble |
| `COMPANY_WATCHLIST_SETUP.md` | How to wire up more watchlist companies' direct career-page connectors |
| `GMAIL_OAUTH_SETUP.md` | Full Gmail/LinkedIn/Indeed connector setup |
| `test_report.md`, `connector_test_report.md` | Exactly what was tested, how, and what's still unverified — no function is claimed to work without this |
| `.env.example` | Copy to `.env` to turn on the optional Adzuna/Jooble/Gmail connectors |

## Turning on the optional sources — later, not required

Everything core works with zero setup. See `CONNECTOR_SETUP.md` for Adzuna/Jooble,
`COMPANY_WATCHLIST_SETUP.md` for more direct company connectors, and `GMAIL_OAUTH_SETUP.md` for
the Gmail/LinkedIn/Indeed connector (the most involved one, and **not tested end-to-end** in this
build — no test Gmail account was available). None of these ever ask for your email password:
API keys go into `.env` or Streamlit Cloud's Secrets panel, and Gmail uses Google's own sign-in
screen, never a password typed anywhere in this project's files or in chat.

## Diagnosing "I see too few positions"

Open the **Connector Status** section first — it shows every source (aggregator and direct
company connector) as one of: OK, zero results, failed, not configured, or unsupported/needs
manual configuration. Zero results is never silently treated as proof a connector works. Then
check **Diagnostic Report** for a full breakdown of every collected job — including a summary of
the most common exclusion reasons (salary missing, seniority mismatch, remote scope unclear,
etc.) — and **Filtered Out with Reasons** / **Watchlist Matches, Not Qualified** to see exactly
why specific jobs didn't make it into Diamond/Gold/Silver. A high compatibility score is
deliberately never allowed to override a hard requirement (paid-only, junior-only, genuinely
worldwide, etc.) — that's a rule from the spec, not a bug — but a job missing just ONE fact
(salary or remote scope) now shows up as **Potential Diamond/Gold/Silver** instead of vanishing.

## If something looks wrong

Check `test_report.md` first — it lists exactly what was verified and what wasn't in this build.
If a job seems miscategorised, open it and read the "Condizioni obbligatorie riscontrate" /
"Motivi" lines on its card: the app always explains its own reasoning, so you can see exactly
which rule put it where it is.
