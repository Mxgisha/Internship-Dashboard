"""SQLite storage. One file, no server, small in-place migrations."""
import json
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_OVERRIDE = os.environ.get("JOBHUNT_DATA_DIR")
DATA = (os.path.abspath(os.path.expanduser(_DATA_OVERRIDE)) if _DATA_OVERRIDE
        else os.path.join(HERE, "data"))
DB_PATH = os.path.join(DATA, "jobhunt.db")
LETTERS = os.path.join(HERE, "letters")
LOGS = os.path.join(HERE, "logs")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    company       TEXT,
    title         TEXT,
    category      TEXT,
    url           TEXT,
    locations     TEXT,
    terms         TEXT,
    degrees       TEXT,
    sponsorship   TEXT,
    date_posted   INTEGER,
    date_updated  INTEGER,
    fit           INTEGER,
    reasons       TEXT,
    summary       TEXT,
    status        TEXT DEFAULT 'new',
    notes         TEXT DEFAULT '',
    detail        TEXT DEFAULT '',
    first_seen    INTEGER,
    last_seen     INTEGER,
    closed_at     INTEGER,
    summary_edited INTEGER DEFAULT 0,
    duplicate_of  TEXT,
    source        TEXT,
    detail_fetched_at INTEGER,
    detail_status TEXT,
    status_changed_at INTEGER
);
CREATE TABLE IF NOT EXISTS letters (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id    TEXT NOT NULL,
    variant   TEXT NOT NULL,
    body      TEXT NOT NULL,
    created   INTEGER,
    UNIQUE(job_id, variant)
);
CREATE TABLE IF NOT EXISTS runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started    INTEGER,
    finished   INTEGER,
    fetched    INTEGER,
    active     INTEGER,
    matched    INTEGER,
    inserted   INTEGER,
    updated    INTEGER,
    duplicates INTEGER,
    closed     INTEGER,
    errors     TEXT,
    note       TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_fit ON jobs(fit DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""

# Columns added after the first release. connect() adds any that are missing, so
# an existing database is upgraded in place. Keep the DDL here, not in a version
# number: this way a fresh schema and an old file converge on the same shape.
JOB_COLUMNS = {
    "closed_at": "INTEGER",
    "summary_edited": "INTEGER DEFAULT 0",
    "duplicate_of": "TEXT",
    "source": "TEXT",
    "detail_fetched_at": "INTEGER",
    "detail_status": "TEXT",
    "status_changed_at": "INTEGER",
}
RUN_COLUMNS = {
    "duplicates": "INTEGER",
    "closed": "INTEGER",
    "errors": "TEXT",
}

STATUSES = ["new", "shortlisted", "applied", "interviewing", "offer", "rejected", "archived"]


def _columns(con, table):
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}


def migrate(con):
    """Add missing columns and backfill the one field that can be inferred."""
    for table, columns in (("jobs", JOB_COLUMNS), ("runs", RUN_COLUMNS)):
        have = _columns(con, table)
        for name, ddl in columns.items():
            if name not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_open ON jobs(closed_at, fit DESC)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_duplicate ON jobs(duplicate_of)")
    # Best available approximation for rows written before the column existed.
    con.execute("UPDATE jobs SET status_changed_at = last_seen "
                "WHERE status_changed_at IS NULL AND last_seen IS NOT NULL")
    con.execute("PRAGMA user_version = 1")
    con.commit()


def connect(path=None):
    db_path = path or DB_PATH
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    migrate(con)
    return con


def log(msg, run_id=None):
    """Append to the plain-text process log. This is the 'logging of the process'."""
    os.makedirs(LOGS, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}\n"
    with open(os.path.join(LOGS, "collect.log"), "a") as fh:
        fh.write(line)
    print(line, end="")


def counts(con):
    out = {}
    out["total"] = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    out["open"] = con.execute("SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL").fetchone()[0]
    out["closed"] = con.execute(
        "SELECT COUNT(*) FROM jobs WHERE closed_at IS NOT NULL").fetchone()[0]
    out["duplicates"] = con.execute(
        "SELECT COUNT(*) FROM jobs WHERE duplicate_of IS NOT NULL").fetchone()[0]
    for row in con.execute(
            "SELECT status, COUNT(*) c FROM jobs WHERE closed_at IS NULL GROUP BY status"):
        out[row["status"]] = row["c"]
    out["letters"] = con.execute("SELECT COUNT(*) FROM letters").fetchone()[0]
    return out


def dump_json(con):
    """Machine-readable snapshot so the documents and the app never drift apart."""
    jobs = [dict(r) for r in con.execute("SELECT * FROM jobs ORDER BY fit DESC")]
    path = os.path.join(DATA, "snapshot.json")
    os.makedirs(DATA, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(jobs, fh, indent=1)
    return path
