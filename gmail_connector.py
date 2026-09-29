"""
Gmail connector for LinkedIn / Indeed / Company job-alert emails (spec
sections 7, 8, 9), now driven by the in-app OAuth wizard in
gmail_oauth.py instead of a local credentials.json/token.json pair - the
old file-based "installed app" flow could not work on Streamlit Community
Cloud (it needs to open a local browser on the same machine that's
running the server, which a cloud deployment doesn't have).

Nobody's Gmail password is ever requested or stored anywhere in this
project. Authentication is Google's standard OAuth2 "Web application"
flow: the person clicks "Connetti Gmail" in the app, approves access on
accounts.google.com (a page this app only links to), and Google redirects
back to this same app's URL with a short-lived authorization code that
gmail_oauth.py exchanges for tokens server-side. Only the read-only Gmail
scope is ever requested (`gmail.readonly`) - this connector cannot
modify, label, send, forward, archive, or delete anything; the scope
itself makes those calls impossible, not just unused.

HONESTY NOTE (do not remove): written against Google's official,
documented Gmail API (`googleapiclient` + `google-auth-oauthlib`) and
exercised in this build only against MOCKED HTTP responses (see
GMAIL_OAUTH_TEST_REPORT.md) - a real end-to-end run requires the
person's own Google Cloud OAuth client and their own Gmail login,
neither of which exists in this sandbox. Treat this connector as
UNVERIFIED against a real inbox until you complete the wizard yourself
once with your own Google account.

Per-message processing model (spec section 9):
  - three separate labels: JOB-ALERTS/LinkedIn, JOB-ALERTS/Indeed,
    JOB-ALERTS/Company (configurable via gmail_oauth.DEFAULT_LABELS, or
    the GMAIL_LABEL_* environment variables below for backward
    compatibility).
  - each message is parsed into ZERO OR MORE individual job records via
    email_parser.parse_eml_bytes (never one generic record per email).
  - the Gmail message ID is recorded in the local SQLite database
    (`db.processed_gmail_ids`) so a message is never re-processed - this
    is the "maintain processed message IDs locally" alternative the spec
    allows when a read-only OAuth scope can't apply Gmail labels itself.
  - the user's email is never deleted, modified, or marked read, and no
    message outside the three configured labels is ever touched.
"""
import base64
import os

import db
import gmail_oauth
from email_parser import parse_eml_bytes

LABELS = {
    provider: os.environ.get(f"GMAIL_LABEL_{provider.upper()}", default)
    for provider, default in gmail_oauth.DEFAULT_LABELS.items()
}


def gmail_configured():
    """True once the person has saved an OAuth Client ID/Secret (wizard
    step 2, or Streamlit Secrets) - i.e. the app COULD start a connection,
    whether or not one has been completed yet."""
    return gmail_oauth.has_client_config()


def gmail_connected():
    """True once the person has completed the consent screen at least
    once and a token is stored - used to show Connect vs. Disconnect in
    the wizard without re-authenticating on every render."""
    return gmail_oauth.is_connected()


def disconnect_gmail():
    """'Disconnect Gmail' button (spec sections 7 and 29): deletes the
    locally stored OAuth token only. Never touches the person's actual
    Gmail account or its labels - this only removes this app's own saved
    credential, so it can't read anything again until reconnected. Full
    revocation on Google's side is a separate, explicit step the wizard
    links to (gmail_oauth.REVOKE_URL)."""
    return gmail_oauth.disconnect()


def _get_service():
    """Build an authenticated Gmail API client, or raise a clear error.
    Imports the Google client libraries lazily so the rest of the app
    works fine even before `pip install -r requirements.txt` picks up
    the Gmail-specific dependencies on a fresh environment."""
    try:
        from googleapiclient.discovery import build
    except ImportError as e:
        raise RuntimeError(
            "librerie Gmail non installate: verifica che requirements.txt contenga "
            "google-api-python-client, google-auth-oauthlib, google-auth-httplib2"
        ) from e

    creds = gmail_oauth.get_credentials()  # raises RuntimeError if not connected
    return build("gmail", "v1", credentials=creds)


def _find_label_id(service, label_name):
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for l in labels:
        if l["name"].lower() == label_name.lower():
            return l["id"]
    return None


def fetch_gmail_job_alerts(max_results=25):
    """Fetch recent LinkedIn / Indeed / Company job-alert emails from
    their three dedicated labels, skip any message already processed
    (tracked in SQLite, not via Gmail labels - the read-only scope can't
    apply labels), and parse each unprocessed message into its
    individual job records. Raises a clear RuntimeError when not
    connected; callers (app.py) show that as a plain warning rather than
    a crash.

    Returns (jobs, parsing_failures): `jobs` are real per-vacancy records
    ready for scoring; `parsing_failures` are the honest
    "Unable to extract individual jobs from this ... alert format"
    records, kept separate so app.py can route them to the dedicated
    Parsing Failures section instead of the normal job list."""
    if not gmail_connected():
        raise RuntimeError("Gmail non connesso: completa il wizard di configurazione Gmail (passi 1-5)")

    service = _get_service()
    jobs, failures = [], []
    for provider, label_name in LABELS.items():
        label_id = _find_label_id(service, label_name)
        if not label_id:
            # A missing label is not fatal for the OTHER labels - just
            # skip this one and let the caller see fewer jobs than
            # expected. Section 9 says never crash on this.
            continue
        msg_list = service.users().messages().list(userId="me", labelIds=[label_id], maxResults=max_results).execute()
        for m in msg_list.get("messages", []):
            if db.is_gmail_message_processed(m["id"]):
                continue
            try:
                raw = service.users().messages().get(userId="me", id=m["id"], format="raw").execute()
                raw_bytes = base64.urlsafe_b64decode(raw["raw"])
                records = parse_eml_bytes(raw_bytes, source=provider, forced_provider=provider)
                real_jobs = [r for r in records if not r.get("parsing_failed")]
                jobs.extend(real_jobs)
                failures.extend([r for r in records if r.get("parsing_failed")])
                db.mark_gmail_message_processed(m["id"], label_name, "parsed" if real_jobs else "parsing_failed")
            except Exception as e:
                db.mark_gmail_message_processed(m["id"], label_name, f"error: {e}")
    return jobs, failures
