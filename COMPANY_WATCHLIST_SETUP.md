# Company watchlist — wiring up direct ATS connectors

The app already treats every company in `config.yaml`'s `watchlist_companies` list as
watch-worthy wherever it shows up through the general job-board sources (Himalayas, Arbeitnow,
etc.) — that part needs no setup. This file is about the OPTIONAL extra step: pulling jobs
**directly** from a watchlist company's own careers page/ATS, which catches postings that never
make it into the aggregators at all.

## What's already wired up and verified

Three companies were confirmed live in this build (see `connector_test_report.md` for the exact
checks) and are already configured in `config.yaml`'s `ats_directory`:

| Company | ATS | Verified via |
|---|---|---|
| Canonical | Greenhouse | `api.greenhouse.io/v1/boards/canonical/jobs` — live, returned real postings |
| GitLab | Greenhouse | `api.greenhouse.io/v1/boards/gitlab/jobs` — live, returned real postings |
| Camunda | Ashby | `api.ashbyhq.com/posting-api/job-board/camunda` — live, returned real postings |

Every other watchlist company is intentionally left `ats: unconfigured` rather than guessing a
board token that was never confirmed working — a guessed-wrong token fails silently or points at
someone else's job board, which is worse than clearly saying "not configured yet." The Connector
Status dashboard section shows every unconfigured company honestly, it never hides them.

## How to find and add a company's real board token (a few minutes, no coding)

Each ATS exposes jobs through the SAME public URL pattern for every company that uses it — you
just need that one company's own identifier (its "board token" / "site ID" / "job board name").

**Greenhouse** — try this in a browser: `https://api.greenhouse.io/v1/boards/COMPANYNAME/jobs`
(lowercase, no spaces, e.g. `pagopa`, `satispay`). If it returns JSON starting with `{"jobs":`,
that's a working token. If it 404s, try variations (the company's exact internal slug is
sometimes different from its public name — check the company's own careers page URL, which is
often `job-boards.greenhouse.io/COMPANYNAME` or `boards.greenhouse.io/COMPANYNAME`).

**Lever** — same idea: `https://api.lever.co/v0/postings/COMPANYNAME?mode=json`. Some companies
use the EU instance instead (`api.eu.lever.co`) — if the global one 404s, try that.

**Ashby** — the company's own careers page is usually `jobs.ashbyhq.com/COMPANYNAME`; the API is
`https://api.ashbyhq.com/posting-api/job-board/COMPANYNAME`.

Once you've confirmed a URL returns real JSON (not a 404), add it to `config.yaml`:

```yaml
ats_directory:
  Satispay:
    ats: greenhouse          # or lever / ashby
    board_token: satispay    # Greenhouse: board_token · Lever: site_id · Ashby: job_board_name
```

The app picks it up on the next refresh — no code changes needed.

## Companies with no working public endpoint

Workable, SmartRecruiters, Workday, Teamtailor, and Recruitee don't have a single documented
endpoint that works the same way for every company the way Greenhouse/Lever/Ashby do — some
companies on these platforms do expose a public JSON feed, but it has to be found per company,
and none was confirmed for any watchlist company in this build. `ats_connectors.py` has the exact
URL patterns to try for each vendor in its `VENDOR_NOTES` dict if you want to go looking yourself
— when you find a real one, wire it in `config.yaml` the same way as above and it'll start
returning real jobs immediately (the fetch functions already exist for all 5 platforms conceptually,
they just need a confirmed real endpoint per company, which this project will not fabricate).

Until then, these companies show up honestly in Connector Status as
**"UNSUPPORTED OR REQUIRES MANUAL CONFIGURATION"** (or, for Workday specifically, **"PUBLIC
WORKDAY CONNECTOR UNAVAILABLE"**) — never silently skipped.

## Verifying a per-vacancy remote policy (the rule that's easy to forget)

However a watchlist company's jobs get in — aggregator or direct ATS connector — the app never
assumes a company-wide remote policy applies to any specific vacancy. A company known for hiring
remotely can still post a vacancy that requires being on-site, or in a specific country. Every
card explicitly shows "Remote arrangement requires confirmation" whenever the individual job
listing's own text doesn't say so explicitly — check the original link before assuming.
