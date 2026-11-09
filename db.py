"""SQLite storage. One file, no server, no migrations."""
import json
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
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
    last_seen     INTEGER
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
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    started   INTEGER,
    finished  INTEGER,
    fetched   INTEGER,
    active    INTEGER,
    matched   INTEGER,
    inserted  INTEGER,
    updated   INTEGER,
    note      TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_fit ON jobs(fit DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""

STATUSES = ["new", "shortlisted", "applied", "interviewing", "offer", "rejected", "archived"]


def connect():
    os.makedirs(DATA, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
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
    for row in con.execute("SELECT status, COUNT(*) c FROM jobs GROUP BY status"):
        out[row["status"]] = row["c"]
    out["letters"] = con.execute("SELECT COUNT(*) FROM letters").fetchone()[0]
    return out


def dump_json(con):
    """Machine-readable snapshot so the documents and the app never drift apart."""
    jobs = [dict(r) for r in con.execute("SELECT * FROM jobs ORDER BY fit DESC")]
    path = os.path.join(DATA, "snapshot.json")
    with open(path, "w") as fh:
        json.dump(jobs, fh, indent=1)
    return path
