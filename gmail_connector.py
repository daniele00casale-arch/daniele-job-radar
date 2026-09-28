"""
OPTIONAL Gmail connector for LinkedIn / Indeed job-alert emails.

This module is intentionally inert unless the user explicitly configures
it. Nobody's Gmail password is ever requested or stored: authentication
uses Google's standard OAuth2 "installed app" flow (a `credentials.json`
downloaded from Google Cloud Console by the user themselves, and a
`token.json` created locally the first time they log in through the
browser consent screen Google shows). Only read-only Gmail scope is used.

HONESTY NOTE (do not remove): this connector was written against Google's
official, documented Gmail API (`googleapiclient` + `google-auth-oauthlib`)
but could NOT be exercised end-to-end in this build, because doing so
requires a real Google Cloud OAuth client and a real Gmail account login -
neither of which this environment has access to. It is disabled by
default and every code path that would touch the network is guarded so
that, when not configured, calling it simply raises a clear
"not configured" error that app.py reports in the connector-warnings panel
instead of crashing. Treat this connector as UNVERIFIED until you've run
it yourself once with your own Google Cloud credentials.

Setup (optional, advanced - see README_MOBILE_FIRST.md for the short version):
  1. Google Cloud Console -> create a project -> enable the "Gmail API".
  2. Create OAuth client credentials of type "Desktop app" -> download the
     JSON -> save it as `credentials.json` next to this file (or point
     GMAIL_CREDENTIALS_JSON at its path).
  3. Set the environment variable ENABLE_GMAIL_CONNECTOR=1.
  4. Run the app locally once; the first Gmail fetch opens a browser
     window asking you to log in and consent to read-only Gmail access.
     A `token.json` is then saved next to this file so you don't need to
     log in again.
  5. In Gmail, create a filter/label (e.g. "JobAlerts") that catches
     LinkedIn and Indeed job-alert emails, and set GMAIL_LABEL to that
     label name (default: "JobAlerts").
"""
import base64
import os

from email_parser import parse_eml_bytes

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def gmail_configured():
    """True only when the user has explicitly opted in AND placed a
    credentials file where we told them to. Never assume yes."""
    if os.environ.get("ENABLE_GMAIL_CONNECTOR", "").lower() not in ("1", "true", "yes"):
        return False
    cred_path = os.environ.get("GMAIL_CREDENTIALS_JSON", "credentials.json")
    return os.path.exists(cred_path)


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

    cred_path = os.environ.get("GMAIL_CREDENTIALS_JSON", "credentials.json")
    token_path = os.environ.get("GMAIL_TOKEN_JSON", "token.json")
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


def fetch_gmail_job_alerts(label=None, max_results=25):
    """Fetch recent LinkedIn/Indeed job-alert emails from a labelled
    Gmail folder and parse each one with the same logic used for manually
    imported .eml files. Returns a list of job dicts, or raises a clear
    RuntimeError when the connector isn't configured - callers (app.py)
    are expected to catch this and show it as a plain warning rather than
    a crash."""
    if not gmail_configured():
        raise RuntimeError(
            "non configurato: imposta ENABLE_GMAIL_CONNECTOR=1 e GMAIL_CREDENTIALS_JSON (vedi gmail_connector.py per le istruzioni) per attivare questo connettore opzionale"
        )
    label = label or os.environ.get("GMAIL_LABEL", "JobAlerts")
    service = _get_service()

    label_id = None
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for l in labels:
        if l["name"].lower() == label.lower():
            label_id = l["id"]
            break
    if not label_id:
        raise RuntimeError(f"etichetta Gmail '{label}' non trovata: crea un filtro/etichetta per gli alert LinkedIn/Indeed")

    msg_list = service.users().messages().list(userId="me", labelIds=[label_id], maxResults=max_results).execute()
    out = []
    for m in msg_list.get("messages", []):
        raw = service.users().messages().get(userId="me", id=m["id"], format="raw").execute()
        raw_bytes = base64.urlsafe_b64decode(raw["raw"])
        out.append(parse_eml_bytes(raw_bytes, source="Gmail alert"))
    return out
