# Connector setup — everything except Gmail

Gmail has its own guide: `GMAIL_OAUTH_SETUP.md`. Company/ATS connectors have their own guide:
`COMPANY_WATCHLIST_SETUP.md`. This file covers the general job-board connectors.

## Always on, no setup needed

These 6 sources work with zero configuration — nothing to sign up for:

| Source | What it is |
|---|---|
| Himalayas | Public remote-jobs API |
| Arbeitnow | Public remote-jobs API |
| Remotive | Public remote-jobs API |
| We Work Remotely | Official RSS feeds |
| The Muse | Public jobs API (works without a key; an optional key just raises the rate limit) |
| Remote OK | Public jobs API |

## Adzuna (optional, free key)

1. Sign up for a free developer account at [developer.adzuna.com](https://developer.adzuna.com/).
2. Copy your `App ID` and `App Key`.
3. Put them in `.env` (local) or Streamlit Cloud's "Secrets" panel (deployed):
   ```
   ADZUNA_APP_ID=your-app-id
   ADZUNA_APP_KEY=your-app-key
   ADZUNA_COUNTRY=it
   ```
4. Adzuna appears automatically in the "Fonti aggregatore attive" list once configured.

**Not live-tested in this build** — no Adzuna credentials were available (see
`connector_test_report.md`). The "not configured" guard path was tested; the live call wasn't.

## Jooble (optional, free key, separate Italy/Switzerland quotas)

Jooble's free tier has a **limited daily request quota**, shared across everyone using the same
key — this is why the app supports two separate keys (one for Italy searches, one for
Switzerland) and caches every result for 30 minutes so a page refresh doesn't burn quota.

1. Request a free API key at [jooble.org/api/about](https://jooble.org/api/about) — you can
   request it once and mention both markets, or request two separate keys if you want the quotas
   fully independent.
2. Put them in `.env` / Streamlit secrets:
   ```
   JOOBLE_API_KEY_IT=your-italy-key
   JOOBLE_API_KEY_CH=your-switzerland-key
   ```
3. Leave either one blank to disable just that market — the connector for the other still works.
4. To disable Jooble entirely without deleting the keys, just untick it in the "Fonti aggregatore
   attive" multiselect in the app.

**Not live-tested in this build** — no Jooble credentials were available. Use sparingly: the
free quota is genuinely small, so this connector is off by default and meant to be turned on
only when you specifically want it for a session, not left running on autopilot.

## Keeping keys secure

- Never put a real key directly in `config.yaml` or any `.py` file — always an environment
  variable, a local `.env` (already in `.gitignore`, never uploaded to GitHub), or Streamlit
  Cloud's own "Secrets" panel (encrypted, not visible in your public repo).
- None of these keys are ever sent to the browser/frontend — they're only used server-side, in
  the same Python process that renders the dashboard.
- If you ever paste a key into the wrong place (e.g. accidentally committed to GitHub), revoke
  and regenerate it from that provider's own dashboard — don't just delete the commit, the old
  key may already be cached by GitHub/search engines.
