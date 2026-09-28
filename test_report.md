# Test Report — Daniele Job Radar (this round of changes)

This report covers what changed in this round: the Potential Diamond/Gold/Silver tiers, the
diagnostic report, the new connectors, and the ATS connectors. Per the project's own rule,
nothing below is claimed to work unless it was actually exercised in this environment.
`connector_test_report.md` has the connector-by-connector detail; this file is the overall
pipeline/UI/scoring test log.

## Network limitation (unchanged from previous rounds)

This sandbox's shell/Python network access goes through an egress allowlist that blocks direct
calls to every job-board/API domain used by this project (confirmed again this round: Himalayas,
Arbeitnow, Remotive, We Work Remotely, The Muse, Remote OK, Adzuna, Jooble, Greenhouse, Lever,
and Ashby all fail with a proxy-level connection error from `requests`/`curl`). The `WebFetch`
tool (a separate network path) reaches most of these directly and was used to confirm live
schemas — see `connector_test_report.md`. Every connector's parsing/mapping logic was then
unit-tested against fixture data built from those confirmed live shapes, with
`requests.get`/`requests.post` monkey-patched to serve the fixtures instead of hitting the
network.

## Results

| # | Area | Method | Result |
|---|---|---|---|
| 1 | Potential Diamond (salary missing, worldwide confirmed) | Unit test | **PASS** |
| 2 | Potential Diamond (salary confirmed, worldwide unclear but role mentions remote) | Unit test | **PASS** |
| 3 | Full Diamond (both confirmed) still classifies as DIAMOND, not Potential | Unit test | **PASS** |
| 4 | Potential Gold (role+location+seniority ok, salary missing) | Unit test | **PASS** — also caught and fixed a real bug during testing (see Bugs Found) |
| 5 | Hard exclusion (7+ years, senior) still excluded even with high salary and worldwide remote | Unit test | **PASS** |
| 6 | Unpaid/equity-only excluded regardless of fit | Unit test | **PASS** |
| 7 | Watchlist company match that doesn't qualify for any tier is tagged "WATCHLIST MATCH, NOT QUALIFIED" (not silently dropped into the generic filtered list) | Unit test | **PASS** |
| 8 | `scoring.diagnose()` produces the full per-job diagnostic row (fields received/missing, hard filters passed/failed, classification, exclusion reason, confidence) | Unit test | **PASS** |
| 9 | The Muse connector | Live schema fetch (WebFetch) + fixture unit test | **PASS** |
| 10 | Remote OK connector (correctly skips the legend/disclaimer item at index 0) | Live schema fetch (WebFetch) + fixture unit test | **PASS** |
| 11 | Jooble connector — not-configured guard | Unit test | **PASS** |
| 12 | Jooble connector — fixture parse | Fixture unit test (schema per Jooble's own docs, **not live-tested**, no credentials available) | **PASS on fixture** |
| 13 | Greenhouse connector | Live schema fetch (WebFetch, against Canonical and GitLab's real boards) + fixture unit test | **PASS** |
| 14 | Lever connector | Live schema fetch (WebFetch, against Lever's own official demo board) + fixture unit test | **PASS** |
| 15 | Ashby connector | Live schema fetch (WebFetch, against Ramp's and Camunda's real boards) + fixture unit test | **PASS** |
| 16 | Unsupported ATS (Workable/SmartRecruiters/Teamtailor/Recruitee/unconfigured) never silently returns zero — raises a labelled status instead | Unit test | **PASS** |
| 17 | Workday specifically returns the exact spec-required label "PUBLIC WORKDAY CONNECTOR UNAVAILABLE" | Unit test | **PASS** |
| 18 | `ats_connectors.fetch_for_directory_entry` dispatch (config.yaml -> correct fetcher) | Unit test | **PASS** |
| 19 | Email parser splits a multi-job LinkedIn alert into separate per-job records (not one record per email) | Unit test with a realistic constructed .eml fixture | **PASS** |
| 20 | Email parser strips tracking parameters (trk, refId, etc.) without breaking the job URL | Unit test | **PASS** |
| 21 | Email parser falls back to the exact required message ("Unable to extract individual jobs from this ... alert format") when it can't confidently split an email, instead of guessing | Unit test | **PASS** |
| 22 | SQLite: new tables (`connector_status`, `refresh_logs`, `processed_gmail_ids`) — insert/read/delete for all three | Unit test | **PASS** |
| 23 | Gmail per-message dedup (`is_gmail_message_processed` / `mark_gmail_message_processed`) | Unit test | **PASS** |
| 24 | "Delete local job history" / "Export personal data" / "Delete imported email data" (privacy section 29) | Unit test | **PASS** |
| 25 | Streamlit app boots and renders with the new sections, filters, and privacy buttons | Booted via `streamlit run app.py --server.headless true`, returned HTTP 200 | **PASS** |
| 26 | Streamlit app survives ALL connectors failing at once (this sandbox's network block) without crashing | Driven with Playwright: clicked "Aggiorna posizioni" with all sources + all 20 watchlist ATS entries enabled; 39 connector attempts, all failed with the network blocked exactly as expected, shown in "Avvisi connettori", app rendered normally with 0/0/0 metrics and a helpful empty-state message pointing at Connector Status/Filtered Out | **PASS** |
| 27 | Mobile viewport (390×844) — no forced horizontal scroll, no console/page errors | Playwright: `document.documentElement.scrollWidth === clientWidth`, zero console/page errors captured | **PASS** |
| 28 | HTML fallback JS/Python parity for the NEW Potential-tier logic | The fallback's `assess()` was run in-browser (Playwright) against the same 5 fixture jobs used for the Python tests — identical classification (DIAMOND/POTENTIAL_DIAMOND/POTENTIAL_GOLD/hard-exclusion) on every one | **PASS** |
| 29 | Windows launcher (`start_job_radar.bat`) | Reviewed — unchanged this round, no new dependency was added | **UNVERIFIED (cannot run .bat outside Windows), unchanged from previous review** |
| 30 | Streamlit Community Cloud deployment | Not re-tested this round — this environment still has no GitHub/Streamlit Cloud account access | **N/A — see DEPLOY_STREAMLIT_CLOUD.md** |

28 automated checks ran in one suite this round (`run_tests_v3`-equivalent) — **all 28 passed**
after the bug fix below.

## Bug found and fixed during THIS round of testing

**Potential Diamond over-triggering on non-remote, on-site jobs.** The first version of the
"remote scope to verify" branch treated ANY job with no explicit worldwide evidence AND no
explicit country-restriction phrase as "unclear -> Potential Diamond". Test #4 above (a
"Junior Business Analyst, office in Lugano" job — not remote at all) exposed this: because
`target_titles` are unioned into every tier's role-keyword list (a change from a previous
round), it matched Diamond's role check too, and with no restriction phrase present it was
wrongly classified POTENTIAL_DIAMOND instead of falling through to the Gold check where it
correctly belonged. **Fix:** "remote scope unclear" now additionally requires the job's own text
to mention remote/distributed/anywhere/WFH at all — an on-site listing that never uses any of
those words no longer qualifies as "unclear", it correctly falls through to Gold/Silver. Verified
fixed by re-running the suite (Delta Co / Lugano job now correctly lands in POTENTIAL_GOLD, not
POTENTIAL_DIAMOND).

## What remains genuinely unverified (unchanged categories from previous rounds, still true)

- **Adzuna and Jooble live behaviour** — no credentials for either were available in this
  session. Both fail with a clear "not configured" message rather than crashing; neither has
  actually called its live endpoint.
- **Gmail connector, end to end** — needs a real Google Cloud OAuth client and Gmail login,
  neither available here. Only the guards and the local dedup/label-lookup logic were unit
  tested. See `GMAIL_OAUTH_SETUP.md`.
- **The 5 unsupported ATS types** (Workable, SmartRecruiters, Workday, Teamtailor, Recruitee) —
  intentionally not implemented against any real company, since no working endpoint was
  confirmed for any watchlist company. They report their status honestly instead. See
  `COMPANY_WATCHLIST_SETUP.md`.
- **17 of the 20 watchlist companies' direct ATS connectors** — left `ats: unconfigured` because
  no real board token was verified for them (only Canonical, GitLab, Camunda were). They still
  appear in Connector Status, never silently skipped.
- **`start_job_radar.bat` on an actual Windows machine** and **Streamlit Community Cloud
  deployment itself** — both unchanged from previous rounds, still not executable/testable from
  this Linux sandbox.
- **Real-world classification volume** — the Potential-tier fix is verified correct on
  constructed test fixtures; how many REAL live jobs end up Diamond vs. Potential Diamond vs.
  filtered out can only be seen once connectors reach real data outside this sandbox (Connector
  Status and Diagnostic Report are built specifically to make that visible once they do).
