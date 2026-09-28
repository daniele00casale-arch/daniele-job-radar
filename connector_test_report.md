# Connector Test Report — one row per source, per the project's own testing rule

Rule followed throughout: a connector is never claimed to work unless a live request or a
realistic fixture test actually passed. Where a live test couldn't be completed, this states the
connector, the exact reason, what WAS tested, what remains unverified, and whether a fallback
exists.

## Aggregator sources (no per-company setup)

| Connector | Live schema check | Fixture unit test | Verdict |
|---|---|---|---|
| Himalayas | ✅ WebFetch, `himalayas.app/jobs/api/search` | ✅ | **PASS** (confirmed in a previous round, unchanged) |
| Arbeitnow | ✅ WebFetch, `www.arbeitnow.com/api/job-board-api` | ✅ | **PASS** (confirmed in a previous round, unchanged) |
| Remotive | ❌ blocked by `robots.txt` for the fetch tool | ✅ against documented schema | **PASS on fixture / schema unverified live** (unchanged) |
| We Work Remotely (RSS) | ✅ WebFetch, live RSS feeds | ✅ | **PASS** (confirmed in a previous round, unchanged) |
| **The Muse** (new) | ✅ WebFetch, `themuse.com/api/public/jobs` — confirmed real shape: `{page, page_count, total, results:[{id, name, contents, publication_date, locations:[{name}], categories:[{name}], levels:[{name}], company:{name}, refs:{landing_page}}]}` | ✅ | **PASS** |
| **Remote OK** (new) | ✅ WebFetch, `remoteok.com/api?tags=product` — confirmed real shape: JSON array, first item is a legend/disclaimer object with no `id`, followed by `{id, slug, epoch, date, company, position, tags, description, location, apply_url, salary_min, salary_max, url}` | ✅ (explicitly tests that the legend item is skipped) | **PASS** |
| Adzuna (optional) | Not re-tested this round (unchanged) | ✅ not-configured guard only | **PASS for the guard; live call still UNVERIFIED — no credentials** |
| **Jooble** (new, optional) | Not tested live — no credentials available | ✅ not-configured guard + fixture parse, against Jooble's own documented response schema | **PASS on fixture / guard; live call UNVERIFIED — no credentials** |

## Direct company/ATS connectors (spec section 5)

| Connector | Live schema check | Fixture unit test | Verdict |
|---|---|---|---|
| **Greenhouse** | ✅ WebFetch against TWO real, currently-hiring companies: `api.greenhouse.io/v1/boards/canonical/jobs` (100+ real postings, e.g. "Accountant") and `api.greenhouse.io/v1/boards/gitlab/jobs` (180+ real postings, e.g. "Account Executive - Italy") | ✅ | **PASS** — wired into `config.yaml`'s `ats_directory` for Canonical and GitLab |
| **Lever** | ✅ WebFetch against Lever's own official public demo board (`api.lever.co/v0/postings/leverdemo`, from Lever's own GitHub-published API docs) — confirmed real shape: JSON array of `{text, categories:{team,location,commitment,allLocations}, workplaceType, hostedUrl, applyUrl, createdAt, descriptionPlain, salaryRange}` | ✅ | **PASS** — implemented and unit-tested; not yet wired to a specific watchlist company (no watchlist company's Lever token was confirmed — see `COMPANY_WATCHLIST_SETUP.md`) |
| **Ashby** | ✅ WebFetch against TWO real companies: `api.ashbyhq.com/posting-api/job-board/ramp` (8 real postings, confirmed shape) and `api.ashbyhq.com/posting-api/job-board/camunda` (6 real postings, e.g. "Principal Product Manager - Time to First Production") | ✅ | **PASS** — wired into `config.yaml`'s `ats_directory` for Camunda |
| Workable | No universal unauthenticated cross-company endpoint confirmed | Only the "unsupported, labelled" path | **NOT IMPLEMENTED AGAINST A REAL COMPANY** — returns `UNSUPPORTED OR REQUIRES MANUAL CONFIGURATION` honestly, per spec, rather than guessing |
| SmartRecruiters | Public Posting API exists but requires a per-company `company_id` opted in by that company; none confirmed for any watchlist company | Only the "unsupported, labelled" path | **NOT IMPLEMENTED AGAINST A REAL COMPANY** — same honest label |
| Workday | Tenant-specific, changes per deployment, would need browser automation to discover reliably (explicitly out of scope) | Only the "unsupported, labelled" path | **`PUBLIC WORKDAY CONNECTOR UNAVAILABLE`** (the exact spec-required label) |
| Teamtailor | Per-company endpoint, none confirmed for any watchlist company | Only the "unsupported, labelled" path | **NOT IMPLEMENTED AGAINST A REAL COMPANY** — same honest label |
| Recruitee | Per-company endpoint, none confirmed for any watchlist company | Only the "unsupported, labelled" path | **NOT IMPLEMENTED AGAINST A REAL COMPANY** — same honest label |

**Never silently returns zero jobs**: verified by unit test — every unconfigured/unsupported
watchlist company still produces a `connector_status` row with an explicit reason string, which
shows up in the app's Connector Status dashboard section.

## Watchlist company -> ATS mapping status (all 20 companies from the spec)

| Company | Status |
|---|---|
| Canonical | ✅ Configured — Greenhouse, board token `canonical`, confirmed live |
| GitLab | ✅ Configured — Greenhouse, board token `gitlab`, confirmed live |
| Camunda | ✅ Configured — Ashby, job board `camunda`, confirmed live |
| PagoPA, VF Corporation, BMW Group, lastminute.com, Medacta, Satispay, Product People, Remote, Automattic, Storyblok, Sysdig, Launchmetrics, 360dialog, ShippyPro, Jet HR, Revolut, Kering | ⚪ Unconfigured — no board token/site ID was verified live for any of these 17 in this build (2 quick guesses each for Automattic and Revolut on Greenhouse both 404'd — their real ATS, if any, wasn't identified). Each shows as "requires manual configuration" in Connector Status, never silently skipped. See `COMPANY_WATCHLIST_SETUP.md` for how to find and add the real one yourself. |

## Gmail connector (LinkedIn/Indeed alerts)

See `GMAIL_OAUTH_SETUP.md` and `test_report.md` — code-reviewed and guard-tested, but genuinely
**not exercised against a real Gmail inbox** in this build (no Google Cloud OAuth client or test
Gmail account was available here). The per-job-splitting logic in `email_parser.py` WAS unit
tested against a realistic constructed multi-job LinkedIn-style .eml fixture and correctly
produced 2 separate job records with tracking parameters stripped from each URL — but real
LinkedIn/Indeed alert HTML could look different from the fixture. Treat as a documented starting
point, not a proven feature, until you run it once yourself against your own inbox.
