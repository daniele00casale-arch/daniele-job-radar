"""
Lightweight SQLite persistence for Daniele Job Radar.

Stores one row per unique job (deduplicated across sources) with its
current pipeline status (new / saved / applied / interviewing / rejected
/ archived) and free-text notes, plus the dates that matter for a job
search: first seen, last seen, application date, interview date,
rejection date.

Every function opens and closes its own short-lived connection - simplest
possible approach for a single-user local/Streamlit-Cloud app, avoids any
threading/locking complexity.
"""
import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

DB_PATH = "job_radar.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    title TEXT,
    company TEXT,
    source TEXT,
    original_url TEXT,
    priority TEXT,
    compatibility INTEGER,
    status TEXT DEFAULT 'new',
    notes TEXT DEFAULT '',
    date_first_seen TEXT,
    date_last_seen TEXT,
    application_date TEXT,
    interview_date TEXT,
    rejection_date TEXT
);
CREATE TABLE IF NOT EXISTS connector_status (
    source TEXT PRIMARY KEY,
    enabled INTEGER DEFAULT 1,
    configured INTEGER DEFAULT 1,
    last_attempted TEXT,
    last_successful TEXT,
    jobs_retrieved INTEGER DEFAULT 0,
    new_jobs INTEGER DEFAULT 0,
    duplicates_removed INTEGER DEFAULT 0,
    accepted_jobs INTEGER DEFAULT 0,
    rejected_jobs INTEGER DEFAULT 0,
    connection_error TEXT,
    parsing_error TEXT,
    status TEXT
);
CREATE TABLE IF NOT EXISTS refresh_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    total_collected INTEGER,
    total_assessed INTEGER,
    total_filtered INTEGER,
    errors_count INTEGER
);
CREATE TABLE IF NOT EXISTS processed_gmail_ids (
    message_id TEXT PRIMARY KEY,
    label TEXT,
    processed_at TEXT,
    outcome TEXT
);
CREATE TABLE IF NOT EXISTS secure_kv (
    k TEXT PRIMARY KEY,
    v TEXT,
    updated_at TEXT
);
"""

VALID_STATUSES = ["new", "saved", "applied", "interviewing", "rejected", "archived"]


def make_job_id(company, title, url):
    """Stable id used for de-duplication across sources and across runs -
    same job seen again tomorrow keeps the same id, so its status/notes
    survive."""
    key = f"{(company or '').lower().strip()}|{(title or '').lower().strip()}|{(url or '').split('?')[0]}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def init_db(path=DB_PATH):
    with closing(sqlite3.connect(path, timeout=15)) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def upsert_job(job, priority, compatibility, path=DB_PATH):
    """Insert a newly-seen job, or update `date_last_seen` (and priority /
    compatibility, which can change run-to-run as descriptions get more
    complete) for one already known - without touching its status or
    notes, which belong to the user's own tracking.

    Uses a single atomic "INSERT ... ON CONFLICT DO UPDATE" (SQLite UPSERT)
    instead of a separate SELECT-then-INSERT/UPDATE. The two-step version
    had a real race condition: Streamlit can re-run the script (a widget
    interaction triggering a rerun while a previous run's DB write was
    still in flight) fast enough that two calls both saw "not found" for
    the same job_id and then both tried to INSERT, crashing with
    "UNIQUE constraint failed: jobs.job_id". The single atomic statement
    below can't race with itself - fixed and confirmed against the exact
    error a real deployment hit."""
    job_id = make_job_id(job.get("company"), job.get("title"), job.get("url"))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with closing(sqlite3.connect(path, timeout=15)) as conn:
        conn.execute(
            "INSERT INTO jobs (job_id, title, company, source, original_url, priority, compatibility, "
            "status, notes, date_first_seen, date_last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(job_id) DO UPDATE SET date_last_seen=excluded.date_last_seen, "
            "priority=excluded.priority, compatibility=excluded.compatibility",
            (job_id, job.get("title"), job.get("company"), job.get("source"), job.get("url"),
             priority, compatibility, "new", "", now, now),
        )
        conn.commit()
    return job_id


def set_status(job_id, status, path=DB_PATH):
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_field = {"applied": "application_date", "interviewing": "interview_date", "rejected": "rejection_date"}.get(status)
    with closing(sqlite3.connect(path, timeout=15)) as conn:
        if date_field:
            conn.execute(f"UPDATE jobs SET status=?, {date_field}=? WHERE job_id=?", (status, now, job_id))
        else:
            conn.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, job_id))
        conn.commit()


def set_notes(job_id, notes, path=DB_PATH):
    with closing(sqlite3.connect(path, timeout=15)) as conn:
        conn.execute("UPDATE jobs SET notes=? WHERE job_id=?", (notes, job_id))
        conn.commit()


def get_all(path=DB_PATH):
    with closing(sqlite3.connect(path, timeout=15)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs").fetchall()
        return [dict(r) for r in rows]


def get_by_status(status, path=DB_PATH):
    with closing(sqlite3.connect(path, timeout=15)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs WHERE status=?", (status,)).fetchall()
        return [dict(r) for r in rows]


def get_status_map(path=DB_PATH):
    """job_id -> {status, notes, ...} for every job ever seen, used by
    app.py to overlay saved/applied/archived state onto freshly-fetched
    listings without a per-job query."""
    return {r["job_id"]: r for r in get_all(path)}


def record_connector_status(source, status, jobs_retrieved=0, connection_error=None, parsing_error=None,
                              configured=True, enabled=True, path=DB_PATH):
    """Upsert one row of the Connector Status dashboard (spec section 24).
    `status` is one of: ok / zero_results / failed / not_configured /
    unsupported / rate_limited - callers decide which, this just persists."""
    now = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(path, timeout=15)) as conn:
        cur = conn.execute("SELECT source FROM connector_status WHERE source=?", (source,))
        exists = cur.fetchone() is not None
        last_successful_clause = ", last_successful=?" if status == "ok" else ""
        params = [now, int(configured), int(enabled), jobs_retrieved, connection_error, parsing_error, status]
        if status == "ok":
            params.append(now)
        if exists:
            conn.execute(
                f"UPDATE connector_status SET last_attempted=?, configured=?, enabled=?, jobs_retrieved=?, "
                f"connection_error=?, parsing_error=?, status=?{last_successful_clause} WHERE source=?",
                params + [source],
            )
        else:
            conn.execute(
                "INSERT INTO connector_status (source, last_attempted, configured, enabled, jobs_retrieved, "
                "connection_error, parsing_error, status, last_successful) VALUES (?,?,?,?,?,?,?,?,?)",
                [source, now, int(configured), int(enabled), jobs_retrieved, connection_error, parsing_error, status,
                 now if status == "ok" else None],
            )
        conn.commit()


def get_connector_status(path=DB_PATH):
    with closing(sqlite3.connect(path, timeout=15)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM connector_status").fetchall()
        return [dict(r) for r in rows]


def log_refresh(total_collected, total_assessed, total_filtered, errors_count, path=DB_PATH):
    now = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(path, timeout=15)) as conn:
        conn.execute(
            "INSERT INTO refresh_logs (ts, total_collected, total_assessed, total_filtered, errors_count) VALUES (?,?,?,?,?)",
            (now, total_collected, total_assessed, total_filtered, errors_count),
        )
        conn.commit()


def last_refresh(path=DB_PATH):
    with closing(sqlite3.connect(path, timeout=15)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM refresh_logs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def is_gmail_message_processed(message_id, path=DB_PATH):
    with closing(sqlite3.connect(path, timeout=15)) as conn:
        cur = conn.execute("SELECT 1 FROM processed_gmail_ids WHERE message_id=?", (message_id,))
        return cur.fetchone() is not None


def mark_gmail_message_processed(message_id, label, outcome, path=DB_PATH):
    now = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(path, timeout=15)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO processed_gmail_ids (message_id, label, processed_at, outcome) VALUES (?,?,?,?)",
            (message_id, label, now, outcome),
        )
        conn.commit()


def set_kv(key, value, path=DB_PATH):
    """Generic small key/value store, used only for the (already-encrypted
    by the caller - see encryption.py) Gmail OAuth client config and
    token. `value=None` deletes the key instead of storing a null."""
    if value is None:
        return delete_kv(key, path)
    now = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(path, timeout=15)) as conn:
        conn.execute(
            "INSERT INTO secure_kv (k, v, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(k) DO UPDATE SET v=excluded.v, updated_at=excluded.updated_at",
            (key, value, now),
        )
        conn.commit()


def get_kv(key, path=DB_PATH):
    with closing(sqlite3.connect(path, timeout=15)) as conn:
        row = conn.execute("SELECT v FROM secure_kv WHERE k=?", (key,)).fetchone()
        return row[0] if row else None


def delete_kv(key, path=DB_PATH):
    with closing(sqlite3.connect(path, timeout=15)) as conn:
        conn.execute("DELETE FROM secure_kv WHERE k=?", (key,))
        conn.commit()


def delete_all_job_history(path=DB_PATH):
    """'Delete local job history' (spec section 29)."""
    with closing(sqlite3.connect(path, timeout=15)) as conn:
        conn.execute("DELETE FROM jobs")
        conn.commit()


def delete_gmail_processed_ids(path=DB_PATH):
    """'Delete imported email data' (spec section 29) - removes only the
    processed-message-id bookkeeping; the app never stores email bodies."""
    with closing(sqlite3.connect(path, timeout=15)) as conn:
        conn.execute("DELETE FROM processed_gmail_ids")
        conn.commit()


def export_all_data(path=DB_PATH):
    """'Export personal data' (spec section 29) - everything this app has
    stored about the user's own job search, as plain dicts ready for
    json.dumps or a CSV writer."""
    return {"jobs": get_all(path), "connector_status": get_connector_status(path)}
