"""
OPTIONAL Gmail connector for LinkedIn / Indeed job-alert emails (spec
sections 7, 8, 9).

Nobody's Gmail password is ever requested or stored. Authentication uses
Google's standard OAuth2 "installed app" flow (a `credentials.json`
downloaded from Google Cloud Console by the user themselves, and a
`token.json` created locally the first time they log in through the
browser consent screen Google shows). Only the read-only Gmail scope is
used (`gmail.readonly`) - this connector never modifies, labels, or
deletes the user's email.

HONESTY NOTE (do not remove): written against Google's official,
documented Gmail API (`googleapiclient` + `google-auth-oauthlib`) but
could NOT be exercised end-to-end in this build - that requires a real
Google Cloud OAuth client and a real Gmail login, neither of which this
sandbox has. Disabled by default; every network path raises a clear "not
configured" error instead of crashing or silently returning nothing.
Treat this connector as UNVERIFIED until you run it yourself once with
your own Google Cloud credentials - see GMAIL_OAUTH_SETUP.md.

Per-message processing model (spec section 9):
  - two separate default labels, one per provider: JOB-ALERTS/LinkedIn and
    JOB-ALERTS/Indeed (configurable via GMAIL_LABEL_LINKEDIN / GMAIL_LABEL_INDEED).
  - each message is parsed into ZERO OR MORE individual job records via
    email_parser.parse_eml_bytes (never one generic record per email).
  - the Gmail message ID is recorded in the local SQLite database
    (`db.processed_gmail_ids`) so a message is never re-processed - this is
    the "maintain processed message IDs locally" alternative the spec
    allows when read-only OAuth can't apply Gmail labels itself.
  - the user's email is never deleted and no unrelated message is touched.
"""
import base64
import os

import db
from email_parser import parse_eml_bytes

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DEFAULT_LABELS = {"LinkedIn": "JOB-ALERTS/LinkedIn", "Indeed": "JOB-ALERTS/Indeed"}
TOKEN_PATH_DEFAULT = "token.json"
CREDENTIALS_PATH_DEFAULT = "credentials.json"


def gmail_configured():
    """True only when the user has explicitly opted in AND placed a
    credentials file where we told them to. Never assume yes."""
    if os.environ.get("ENABLE_GMAIL_CONNECTOR", "").lower() not in ("1", "true", "yes"):
        return False
    cred_path = os.environ.get("GMAIL_CREDENTIALS_JSON", CREDENTIALS_PATH_DEFAULT)
    return os.path.exists(cred_path)


def gmail_connected():
    """True once a token.json exists - i.e. the user has completed the
    OAuth consent screen at least once. Used to show a Connect/Disconnect
    toggle without re-authenticating every render."""
    token_path = os.environ.get("GMAIL_TOKEN_JSON", TOKEN_PATH_DEFAULT)
    return os.path.exists(token_path)


def disconnect_gmail():
    """'Disconnect Gmail' button (spec sections 7 and 29): deletes the
    locally stored OAuth token. Never touches the user's actual Gmail
    account or its labels - this only removes this app's own saved
    credential so it can no longer read anything until reconnected."""
    token_path = os.environ.get("GMAIL_TOKEN_JSON", TOKEN_PATH_DEFAULT)
    if os.path.exists(token_path):
        os.remove(token_path)
        return True
    return False


def _get_service():
    """Build an authenticated Gmail API client, or raise a clear error.
    Imports the Google client libraries lazily so the rest of the app
    works fine even when they aren't installed (they're an optional
    extra - see requirements-gmail.txt)."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as e:
        raise RuntimeError(
            "librerie Gmail non installate: esegui 'pip install -r requirements-gmail.txt' per attivare questo connettore opzionale"
        ) from e

    cred_path = os.environ.get("GMAIL_CREDENTIALS_JSON", CREDENTIALS_PATH_DEFAULT)
    token_path = os.environ.get("GMAIL_TOKEN_JSON", TOKEN_PATH_DEFAULT)
    if not os.path.exists(cred_path):
        raise RuntimeError(f"non configurato: file credenziali Gmail non trovato in {cred_path}")

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(cred_path, SCOPES)
            creds = flow.run_local_server(port=0)  # opens a browser for consent, first run only
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def _find_label_id(service, label_name):
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for l in labels:
        if l["name"].lower() == label_name.lower():
            return l["id"]
    return None


def fetch_gmail_job_alerts(max_results=25):
    """Fetch recent LinkedIn AND Indeed job-alert emails from their two
    dedicated labels, skip any message already processed (tracked in
    SQLite, not via Gmail labels - read-only scope can't apply labels),
    and parse each unprocessed message into its individual job records.
    Raises a clear RuntimeError when not configured; callers (app.py) show
    that as a plain warning rather than a crash."""
    if not gmail_configured():
        raise RuntimeError(
            "non configurato: imposta ENABLE_GMAIL_CONNECTOR=1 e GMAIL_CREDENTIALS_JSON "
            "(vedi GMAIL_OAUTH_SETUP.md) per attivare questo connettore opzionale"
        )
    service = _get_service()
    labels = {
        "LinkedIn": os.environ.get("GMAIL_LABEL_LINKEDIN", DEFAULT_LABELS["LinkedIn"]),
        "Indeed": os.environ.get("GMAIL_LABEL_INDEED", DEFAULT_LABELS["Indeed"]),
    }

    out = []
    for provider, label_name in labels.items():
        label_id = _find_label_id(service, label_name)
        if not label_id:
            # Missing label is not fatal for the OTHER provider's label -
            # just skip this one and let the caller see it went through
            # with fewer jobs than expected. Section 9 says never crash.
            continue
        msg_list = service.users().messages().list(userId="me", labelIds=[label_id], maxResults=max_results).execute()
        for m in msg_list.get("messages", []):
            if db.is_gmail_message_processed(m["id"]):
                continue
            try:
                raw = service.users().messages().get(userId="me", id=m["id"], format="raw").execute()
                raw_bytes = base64.urlsafe_b64decode(raw["raw"])
                records = parse_eml_bytes(raw_bytes, source=provider)
                real_jobs = [r for r in records if not r.get("parsing_failed")]
                out.extend(real_jobs)
                db.mark_gmail_message_processed(m["id"], label_name, "parsed" if real_jobs else "parsing_failed")
            except Exception as e:
                db.mark_gmail_message_processed(m["id"], label_name, f"error: {e}")
    return out
