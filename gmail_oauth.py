"""
Gmail OAuth2 for Daniele Job Radar - the in-app "Connect Gmail" wizard.

Design goals (from the spec):
  - gmail.readonly is the ONLY Gmail scope ever requested. This app can
    never modify a label, mark a message read, delete, send, forward, or
    archive anything - the scope itself makes that impossible, it isn't
    just a promise in this code.
  - The Gmail PASSWORD is never seen by this app. The only thing the
    person enters here is the OAuth Client ID/Secret of their OWN Google
    Cloud project (created once, following GMAIL_OAUTH_SETUP.md) - login
    and consent always happen on accounts.google.com, a page this app
    only links to.
  - No file editing, no terminal: Client ID/Secret are typed into two
    text boxes in the app and stored encrypted in the local SQLite
    database (via encryption.py) - or, if the person prefers, in
    Streamlit Secrets, which is checked first and never overridden.
  - Works on Streamlit Community Cloud, where there is no local browser
    to pop up (unlike a desktop "installed app" flow) - this uses the
    "Web application" OAuth client type: Google redirects back to the
    running app's own URL with a `code` in the query string, which this
    module exchanges for tokens server-side.

Nothing here ever calls a Gmail method that writes: only
`users().labels().list`, `users().messages().list/get`, and
`users().getProfile` (the read-only scope wouldn't allow anything else
even if this code tried).
"""
import os
import secrets as _secrets

import db
import encryption

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
REVOKE_URL = "https://myaccount.google.com/permissions"
GOOGLE_CLOUD_CREDENTIALS_URL = "https://console.cloud.google.com/apis/credentials"

DEFAULT_LABELS = {
    "LinkedIn": "JOB-ALERTS/LinkedIn",
    "Indeed": "JOB-ALERTS/Indeed",
    "Company": "JOB-ALERTS/Company",
}

_KV_CLIENT_ID = "gmail_oauth_client_id"
_KV_CLIENT_SECRET = "gmail_oauth_client_secret_enc"
_KV_TOKEN = "gmail_oauth_token_enc"
_KV_STATE = "gmail_oauth_state"  # short-lived CSRF token for the redirect round-trip
_KV_REDIRECT_URI = "gmail_oauth_redirect_uri"  # the exact URI used to build the auth URL, reused at exchange time


def _streamlit_secrets():
    """Best-effort read of st.secrets['gmail_oauth'] - never raises if
    Streamlit Secrets isn't configured at all (the common case)."""
    try:
        import streamlit as st
        block = st.secrets.get("gmail_oauth") if hasattr(st, "secrets") else None
        if block:
            return block.get("client_id"), block.get("client_secret")
    except Exception:
        pass
    return None, None


def has_client_config():
    client_id, client_secret = get_client_config()
    return bool(client_id) and bool(client_secret)


def get_client_config():
    """Priority: Streamlit Secrets (recommended, read-only, never edited
    by this app) > GMAIL_OAUTH_CLIENT_ID/SECRET environment variables
    (.env / a local process env) > whatever the person saved through the
    wizard (encrypted in the local database)."""
    secret_id, secret_secret = _streamlit_secrets()
    if secret_id and secret_secret:
        return secret_id, secret_secret
    env_id, env_secret = os.environ.get("GMAIL_OAUTH_CLIENT_ID"), os.environ.get("GMAIL_OAUTH_CLIENT_SECRET")
    if env_id and env_secret:
        return env_id, env_secret
    client_id = db.get_kv(_KV_CLIENT_ID)
    enc_secret = db.get_kv(_KV_CLIENT_SECRET)
    client_secret = encryption.decrypt(enc_secret) if enc_secret else None
    return client_id, client_secret


def client_config_source():
    """For the wizard's status line: tells the person WHERE their
    credentials are coming from, without ever showing the secret back."""
    secret_id, secret_secret = _streamlit_secrets()
    if secret_id and secret_secret:
        return "streamlit_secrets"
    if os.environ.get("GMAIL_OAUTH_CLIENT_ID") and os.environ.get("GMAIL_OAUTH_CLIENT_SECRET"):
        return "env"
    if db.get_kv(_KV_CLIENT_ID):
        return "wizard"
    return None


def save_client_config(client_id, client_secret):
    """Step 2 of the wizard. Only the Client ID is stored in the clear
    (it is not a secret - Google's own docs show it in the browser's
    OAuth screen); the Client Secret is encrypted before it touches the
    database. Never logged, never re-displayed after this call returns."""
    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    if not client_id or not client_secret:
        raise ValueError("Client ID e Client Secret sono entrambi obbligatori")
    db.set_kv(_KV_CLIENT_ID, client_id)
    db.set_kv(_KV_CLIENT_SECRET, encryption.encrypt(client_secret))


def clear_client_config():
    db.set_kv(_KV_CLIENT_ID, None)
    db.set_kv(_KV_CLIENT_SECRET, None)


def detect_redirect_base_url():
    """Tries to read the app's own public URL from the incoming request's
    Host header (available on Streamlit >=1.37 via st.context.headers),
    so the wizard can show the exact redirect URI without asking the
    person to type it themselves. Returns None if unavailable (older
    Streamlit, or running locally without a browser request context) -
    the wizard falls back to a manual field in that case, it never
    guesses."""
    try:
        import streamlit as st
        headers = getattr(st.context, "headers", None) if hasattr(st, "context") else None
        if not headers:
            return None
        host = headers.get("Host") or headers.get("host")
        if not host:
            return None
        # Streamlit Cloud always serves over https; localhost stays http.
        scheme = "http" if host.startswith("localhost") or host.startswith("127.0.0.1") else "https"
        return f"{scheme}://{host}"
    except Exception:
        return None


def redirect_uri_from_base(base_url):
    return base_url.rstrip("/") + "/"


def _client_secrets_dict(client_id, client_secret, redirect_uri):
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def build_authorization_url(redirect_uri):
    """Step 4: returns (auth_url, state). `state` AND `redirect_uri` are
    stashed server-side (in the local database, tied to nothing
    personal) rather than in Streamlit's session_state, because the
    browser's redirect back from Google's consent screen is a fresh page
    load that starts a brand-new Streamlit session - anything kept only
    in session_state before the redirect would already be gone by the
    time exchange_code() runs. `state` is checked against what Google
    sends back, to prevent a forged callback from a different OAuth flow
    being accepted; `redirect_uri` is reused as-is at exchange time so it
    is guaranteed to match exactly what was authorized (Google requires
    an exact match)."""
    from google_auth_oauthlib.flow import Flow

    client_id, client_secret = get_client_config()
    if not client_id or not client_secret:
        raise RuntimeError("Client ID/Secret non configurati: completa il passo 2 del wizard")

    flow = Flow.from_client_config(
        _client_secrets_dict(client_id, client_secret, redirect_uri),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    state = _secrets.token_urlsafe(24)
    auth_url, _ = flow.authorization_url(
        access_type="offline",       # request a refresh token
        include_granted_scopes="true",
        prompt="consent",            # always show the consent screen so a refresh token is reliably issued
        state=state,
    )
    db.set_kv(_KV_STATE, state)
    db.set_kv(_KV_REDIRECT_URI, redirect_uri)
    return auth_url, state


def exchange_code(code, state):
    """Step 5: called once Google redirects back with ?code=...&state=....
    Verifies `state` first and reuses the exact `redirect_uri` stored by
    build_authorization_url(). On success, stores the resulting
    credentials (encrypted) and returns True. Raises a clear
    RuntimeError on any mismatch or failure - callers show that as an
    error, never silently pretend the connection succeeded."""
    from google_auth_oauthlib.flow import Flow

    expected_state = db.get_kv(_KV_STATE)
    redirect_uri = db.get_kv(_KV_REDIRECT_URI)
    if not expected_state or state != expected_state:
        raise RuntimeError(
            "stato OAuth non corrispondente (possibile richiesta scaduta o duplicata) - "
            "clicca di nuovo su 'Connetti Gmail' per ripartire"
        )
    if not redirect_uri:
        raise RuntimeError("URI di reindirizzamento non trovato - clicca di nuovo su 'Connetti Gmail' per ripartire")
    db.set_kv(_KV_STATE, None)

    client_id, client_secret = get_client_config()
    if not client_id or not client_secret:
        raise RuntimeError("Client ID/Secret non configurati: completa il passo 2 del wizard")

    flow = Flow.from_client_config(
        _client_secrets_dict(client_id, client_secret, redirect_uri),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    granted = set(creds.scopes or [])
    if granted - set(SCOPES):
        # Google should never grant more than we asked for, but if it
        # ever did, refuse to store credentials with a wider scope than
        # the spec allows rather than silently accepting them.
        raise RuntimeError(
            f"Google ha concesso permessi più ampi del previsto ({sorted(granted)}) - connessione rifiutata per sicurezza"
        )
    db.set_kv(_KV_TOKEN, encryption.encrypt(creds.to_json()))
    db.set_kv(_KV_REDIRECT_URI, None)
    return True


def is_connected():
    return db.get_kv(_KV_TOKEN) is not None


def disconnect():
    """'Disconnect Gmail' button - deletes only this app's locally stored
    token. Never touches the Google account itself; the person can also
    fully revoke this app's access at REVOKE_URL if they want to remove
    it from their Google account's connected-apps list too."""
    had_token = db.get_kv(_KV_TOKEN) is not None
    db.set_kv(_KV_TOKEN, None)
    return had_token


def get_credentials():
    """Loads stored credentials, refreshing the access token first if it
    has expired (using the stored refresh token - this is the only
    "automatic" step; it never re-prompts the person). Persists the
    refreshed token back to the database so the next run doesn't have to
    refresh again. Raises RuntimeError with a clear message if nothing
    is connected yet."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    enc_token = db.get_kv(_KV_TOKEN)
    if not enc_token:
        raise RuntimeError("Gmail non connesso: completa il wizard di configurazione Gmail")
    creds = Credentials.from_authorized_user_info(
        __import__("json").loads(encryption.decrypt(enc_token)), SCOPES
    )
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            db.set_kv(_KV_TOKEN, encryption.encrypt(creds.to_json()))
        else:
            raise RuntimeError(
                "il token Gmail salvato non è più valido e non ha un refresh token utilizzabile - "
                "disconnetti e riconnetti Gmail dal wizard"
            )
    return creds


def connected_email_address():
    """Read-only `getProfile` call, used only to show the person WHICH
    Gmail account is connected (a sanity check, e.g. "is this really my
    personal account and not a work one"). Never used for anything else."""
    from googleapiclient.discovery import build

    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress")
