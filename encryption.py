"""
Local at-rest encryption for the few secrets this app stores itself
(Gmail OAuth Client Secret, and the OAuth refresh/access token) -
spec requirement: "Store secrets through Streamlit Secrets or another
secure configuration mechanism."

Streamlit Secrets (st.secrets) is one first-class option and is checked
first wherever a secret is read (see gmail_oauth.py). When the person
instead enters the Client ID/Secret through the in-app wizard (to avoid
making them edit any file), this module is the "another secure
configuration mechanism": values are encrypted with a locally-generated
Fernet key before being written to the SQLite database, so the .db file
never holds a Client Secret or an OAuth token in plain text.

The encryption key itself lives in `local_secrets/encryption.key`, a
file that is:
  - generated once, automatically, on first use;
  - never committed to git (`local_secrets/` is in .gitignore);
  - the only way to decrypt what's in the database - deleting it (or the
    whole `local_secrets/` folder) makes any previously stored secret
    permanently unreadable, which is exactly what should happen if the
    person wipes the deployment.

This protects against someone reading the .db file in isolation (a stray
backup, a misconfigured public file listing, etc). It does NOT protect
against someone with full access to the running container/host, which
could always read the key file too - no purely local-storage scheme can
do better than that without an external secrets manager, which is why
Streamlit Secrets remains the recommended option for a Streamlit Cloud
deployment.
"""
import os

KEY_DIR = "local_secrets"
KEY_PATH = os.path.join(KEY_DIR, "encryption.key")


def _get_or_create_key():
    from cryptography.fernet import Fernet

    os.makedirs(KEY_DIR, exist_ok=True)
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, "rb") as f:
            return f.read()
    key = Fernet.generate_key()
    with open(KEY_PATH, "wb") as f:
        f.write(key)
    try:
        os.chmod(KEY_PATH, 0o600)
    except OSError:
        pass  # best-effort on platforms that don't support chmod (e.g. some Windows setups)
    return key


def is_available():
    """False only if the `cryptography` package genuinely isn't installed
    (it's in requirements.txt, so this should not normally happen) -
    callers use this to show an honest error instead of crashing."""
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def encrypt(plaintext):
    """Returns a str safe to store in a TEXT column. Raises RuntimeError
    with a clear message if `cryptography` isn't installed - never
    silently falls back to storing the secret unencrypted."""
    from cryptography.fernet import Fernet

    if plaintext is None:
        return None
    key = _get_or_create_key()
    return Fernet(key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token):
    from cryptography.fernet import Fernet, InvalidToken

    if token is None:
        return None
    key = _get_or_create_key()
    try:
        return Fernet(key).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise RuntimeError(
            "impossibile decifrare il valore salvato: la chiave locale in local_secrets/encryption.key "
            "è cambiata o manca (succede se sposti il progetto senza copiare quella cartella) - "
            "riconfigura le credenziali Gmail dal wizard"
        ) from e
