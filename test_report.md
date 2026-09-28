# Test Report — Daniele Job Radar

This report lists every function/area that was tested, how, and the result. Per the project's
own rule, nothing below is claimed to work unless it was actually exercised in this environment.
Two things could **not** be tested end-to-end here and are called out explicitly rather than
glossed over: **live network calls to the 4 core APIs** (this sandbox's outbound network is
restricted to package registries — see "Network limitation" below) and the **Gmail/Adzuna
optional connectors** (no credentials were provided).

## Network limitation (affects "live" testing of connectors)

This sandbox's shell/Python network access goes through an egress allowlist that blocks
`himalayas.app`, `arbeitnow.com`, `remotive.com` and `weworkremotely.com` (confirmed: `curl` to
all four returns `403` at the proxy, "policy denial"). To still test the connectors faithfully:

1. The `WebFetch` tool (a separate network path) **was** able to reach `himalayas.app`,
   `arbeitnow.com` and `weworkremotely.com` directly and returned real, live JSON/XML — used to
   confirm the exact current schema of each API.
2. `remotive.com`/`remotive.io` refused `WebFetch` via `robots.txt` (confirmed:
   `ROBOTS_DISALLOWED`) — its live schema could **not** be re-confirmed on this run. The connector
   follows Remotive's public documented schema, which is unchanged since the previous review of
   this project.
3. Every connector was then unit-tested against **fixture data captured verbatim from those real
   API responses** (see `/tmp` test fixtures referenced in the session), with `requests.get` and
   `feedparser.parse` monkey-patched to serve those fixtures instead of hitting the network.

This means: parsing/mapping logic for all 4 connectors is verified against real response shapes.
The one thing NOT verified on this run is whether Remotive's schema has changed since the schema
was last confirmed, and whether any of the 4 live services are reachable/rate-limiting right now
from wherever you actually run the app.

## Results

| # | Area | Method | Result |
|---|---|---|---|
| 1 | Himalayas connector | Live schema fetch (WebFetch) + fixture unit test | **PASS** — seniority list→string coercion, worldwide from `locationRestrictions`, salary from `minSalary`/`maxSalary`/`currency`, all correct |
| 2 | Arbeitnow connector | Live schema fetch (WebFetch) + fixture unit test | **PASS** — `remote`+worldwide-text combination, seniority extracted from `job_types`, salary regex fallback |
| 3 | Remotive connector | Fixture unit test only (schema NOT re-confirmed live — `robots.txt` blocks fetch tools) | **PASS on fixture** / schema currency **UNVERIFIED live** on this run |
| 4 | We Work Remotely RSS parsing | Live schema fetch (WebFetch) + fixture unit test | **PASS** — `<region>` tag used as authoritative worldwide signal, company/title split, salary regex from description |
| 5 | Adzuna connector (optional) | Code review + "not configured" path tested | **PASS** for the not-configured guard (raises clear error, doesn't crash or silently return nothing). **Live API call UNVERIFIED — no Adzuna credentials available in this environment.** |
| 6 | Gmail connector (optional) | Code review + "not configured" path tested | **PASS** for the not-configured guard. **Everything past that point is UNVERIFIED** — no Google Cloud OAuth client or Gmail account available here. Treat as untested until you run it once yourself. |
| 7 | Duplicate detection | Unit test: same job (company+title+url) seen via two different runs gets the same `job_id` and only 1 DB row | **PASS** |
| 8 | Experience extraction | Unit tests: "minimum 1 year... 2 years preferred" → 1 (mandatory wins over preferred); "5+ years required" → 5, not preferred; "no experience required" → 0 | **PASS** — also fixed a real bug during testing (see Bugs Found) where a salary figure like "120,000/year" was mis-parsed as "0 years experience" |
| 9 | Compensation parsing | Unit tests: EUR range, CHF with EU-style thousands separator ("60.000"), bare hourly rate without guaranteed hours (correctly NOT annualised), hourly rate WITH guaranteed hours (correctly annualised/guaranteed), missing salary → "Salary not disclosed" | **PASS** |
| 10 | Diamond classification | Unit test: genuinely-worldwide + junior + ≥€40k + product role → DIAMOND; same but "remote" word alone with "must be based in the United States" → correctly NOT Diamond; high salary + worldwide but 7+ years required → correctly excluded (hard cap never overridden by score) | **PASS** |
| 11 | Gold classification | Unit test: Lugano office job, junior, business analysis → GOLD; missing salary still classified (labelled, not excluded) | **PASS** |
| 12 | Silver classification | Unit test: remote from Italy/Europe, junior, ≥€40k → SILVER | **PASS** |
| 13 | Hard exclusions (never overridden by score) | Unit test: unpaid/equity-only role excluded regardless of any other attribute | **PASS** |
| 14 | Strategic Internship category | Unit test: well-structured, paid, relevant internship at a recognised company → STRATEGIC_INTERNSHIP; generic/unclear internship → correctly NOT classified | **PASS** |
| 15 | High-Value Part-Time category | Unit test: 20h/week, $30/hour contractor, business-analytics role → HIGH_VALUE_PART_TIME | **PASS** |
| 16 | Watchlist company handling | Unit test: a watchlist company (GitLab) with no explicit worldwide evidence is flagged "requires confirmation", NOT auto-assumed fully remote | **PASS** |
| 17 | SQLite persistence (`db.py`) | Unit tests: insert, re-insert same job (dedup, same id), status transition to "applied" sets `application_date`, notes persist, invalid status rejected | **PASS** |
| 18 | CSV export | Code path exercised in the live Streamlit smoke test (button renders, `pandas.DataFrame.to_csv` produces bytes); the HTML fallback's `exportCsv()` was exercised via Playwright | **PASS** |
| 19 | Mobile-responsive rendering | Streamlit app booted headless, driven with a Playwright browser at a 390×844 (iPhone-class) viewport; refreshed positions, rendered a Diamond card, switched sections via the dropdown, confirmed `scrollWidth === clientWidth` (no forced horizontal scroll) | **PASS** |
| 20 | HTML fallback JS engine | The fallback's `assess()` function was run in-browser (Playwright) against the exact same 6 fixture jobs used for the Python `scoring.assess()` tests — **identical classification on every fixture** (Diamond/Gold/Silver/hard-exclusion/High-Value Part-Time) | **PASS** |
| 21 | Windows launcher (`start_job_radar.bat`) | Reviewed line-by-line for correctness (Python detection via `py`/`python`, venv creation, pip install, clear Italian error messages). **Cannot be executed on this Linux sandbox — there is no Windows environment available here.** | **UNVERIFIED (cannot run .bat outside Windows) — syntax and logic reviewed, not execution-tested** |
| 22 | Streamlit startup | App booted via `streamlit run app.py --server.headless true`, returned HTTP 200, no exceptions in server log, no browser console/page errors across two full sessions | **PASS** |
| 23 | GitHub-ready structure / Streamlit Cloud deploy | Files reviewed against Streamlit Community Cloud's requirements (root-level `app.py`, `requirements.txt`, `.streamlit/config.toml`). **Not deployed** — no GitHub or Streamlit Cloud account access from this environment (see below). | **N/A — deployment itself untested; files reviewed for correctness** |

## Bugs found and fixed during this round of testing

1. **False "0 years experience" match from salary figures.** The normalized text used for
   keyword matching strips punctuation, so "€120,000/year" became "...120 000 year...", and the
   experience regex matched "000" immediately followed by "year" as "0 years of experience" —
   silently overriding a real "7+ years required" elsewhere in the same text. Fixed by parsing
   experience and compensation from a separate, lightly-cleaned "raw" text that keeps digits,
   commas, currency symbols and slashes intact.
2. **Structured `salary` field from connectors was never read by the scoring engine.** Himalayas
   returns `minSalary`/`maxSalary` as structured numbers, which `connectors.py` already formats
   into a `job["salary"]` string — but `scoring.py` only re-parsed salary from free-text
   descriptions, so jobs whose only salary info was in the structured field were reported as
   "Salary not disclosed" even when the source clearly published a number. Fixed by including the
   `salary` field in the text scoring reads.
3. **Tier role-keyword lists didn't include common title phrasing.** The Diamond/Gold/Silver
   `role_keywords` lists in `config.yaml` used broader category phrases ("product management")
   that didn't match the literal candidate-preferred title "Product Manager" — so a job titled
   exactly "Junior Product Manager" could fail every tier's role check. Fixed by unioning each
   tier's keyword list with the candidate's own `target_titles` list.
4. **High-Value Part-Time hours regex only matched a range ("15-25 hours"), not a single stated
   value ("20 hours per week")**, and the money/hours regexes were being run against the
   punctuation-stripped text (same root cause as bug #1), so a currency symbol like "$" was
   already gone by the time the regex ran. Both fixed.
5. **`is_watchlisted` was silently dropped from the result dict on every "filtered out" code
   path**, so a job from a watchlist company that got hard-excluded lost that flag entirely
   instead of surfacing it. Fixed — every return path now carries `is_watchlisted`.

All five were caught by the automated test suite in this same session (not found "by inspection"
and left unverified) and confirmed fixed by re-running the suite afterward.

## What remains genuinely unverified

- **Adzuna live behaviour** — no `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` were available in this session.
  The connector follows Adzuna's public documented schema and fails with a clear message when not
  configured, but has never actually called the live endpoint.
- **Gmail connector, end to end** — this needs a real Google Cloud OAuth client and a real Gmail
  login; neither exists in this sandbox. Only the "not configured → clear error" guard was tested.
  Treat this connector as a documented starting point, not a proven feature, until you run it once
  yourself.
- **`start_job_radar.bat` on an actual Windows machine** — reviewed for correctness, not executed
  (this environment has no Windows to run it on).
- **Streamlit Community Cloud deployment itself** — this environment has no GitHub or Streamlit
  Cloud account access (see `DEPLOY_STREAMLIT_CLOUD.md` for why, and the exact steps to do it
  yourself in about 5 minutes from your phone).
- **Remotive's exact current schema** — blocked by that site's `robots.txt` for the fetch tool
  available in this session; the connector follows the documented public schema, unchanged since
  the previous review, but wasn't re-confirmed live on this run.
