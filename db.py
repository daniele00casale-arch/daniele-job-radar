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
"""

VALID_STATUSES = ["new", "saved", "applied", "interviewing", "rejected", "archived"]


def make_job_id(company, title, url):
    """Stable id used for de-duplication across sources and across runs -
    same job seen again tomorrow keeps the same id, so its status/notes
    survive."""
    key = f"{(company or '').lower().strip()}|{(title or '').lower().strip()}|{(url or '').split('?')[0]}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def init_db(path=DB_PATH):
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(SCHEMA)
        conn.commit()


def upsert_job(job, priority, compatibility, path=DB_PATH):
    """Insert a newly-seen job, or update `date_last_seen` (and priority /
    compatibility, which can change run-to-run as descriptions get more
    complete) for one already known - without touching its status or
    notes, which belong to the user's own tracking."""
    job_id = make_job_id(job.get("company"), job.get("title"), job.get("url"))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with closing(sqlite3.connect(path)) as conn:
        cur = conn.execute("SELECT job_id FROM jobs WHERE job_id = ?", (job_id,))
        exists = cur.fetchone() is not None
        if exists:
            conn.execute(
                "UPDATE jobs SET date_last_seen=?, priority=?, compatibility=? WHERE job_id=?",
                (now, priority, compatibility, job_id),
            )
        else:
            conn.execute(
                "INSERT INTO jobs (job_id, title, company, source, original_url, priority, compatibility, "
                "status, notes, date_first_seen, date_last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
    with closing(sqlite3.connect(path)) as conn:
        if date_field:
            conn.execute(f"UPDATE jobs SET status=?, {date_field}=? WHERE job_id=?", (status, now, job_id))
        else:
            conn.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, job_id))
        conn.commit()


def set_notes(job_id, notes, path=DB_PATH):
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("UPDATE jobs SET notes=? WHERE job_id=?", (notes, job_id))
        conn.commit()


def get_all(path=DB_PATH):
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs").fetchall()
        return [dict(r) for r in rows]


def get_by_status(status, path=DB_PATH):
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs WHERE status=?", (status,)).fetchall()
        return [dict(r) for r in rows]


def get_status_map(path=DB_PATH):
    """job_id -> {status, notes, ...} for every job ever seen, used by
    app.py to overlay saved/applied/archived state onto freshly-fetched
    listings without a per-job query."""
    return {r["job_id"]: r for r in get_all(path)}
