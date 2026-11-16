"""Schema creation and in-place migration."""
import os
import sqlite3
import sys
import tempfile
import shutil
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for path in (os.path.dirname(HERE), HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import _bootstrap  # noqa: E402
import db  # noqa: E402

LEGACY = """
CREATE TABLE jobs (
    id TEXT PRIMARY KEY, company TEXT, title TEXT, category TEXT, url TEXT,
    locations TEXT, terms TEXT, degrees TEXT, sponsorship TEXT,
    date_posted INTEGER, date_updated INTEGER, fit INTEGER, reasons TEXT,
    summary TEXT, status TEXT DEFAULT 'new', notes TEXT DEFAULT '',
    detail TEXT DEFAULT '', first_seen INTEGER, last_seen INTEGER
);
CREATE TABLE letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
    variant TEXT NOT NULL, body TEXT NOT NULL, created INTEGER,
    UNIQUE(job_id, variant)
);
CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, started INTEGER, finished INTEGER,
    fetched INTEGER, active INTEGER, matched INTEGER, inserted INTEGER,
    updated INTEGER, note TEXT
);
"""

NEW_JOB_COLUMNS = {"closed_at", "summary_edited", "duplicate_of", "source",
                   "detail_fetched_at", "detail_status", "status_changed_at"}
NEW_RUN_COLUMNS = {"duplicates", "closed", "errors"}


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="jobhunt-migrate-")
        self.path = os.path.join(self.dir, "legacy.db")
        con = sqlite3.connect(self.path)
        con.executescript(LEGACY)
        con.execute(
            """INSERT INTO jobs (id, company, title, category, fit, summary, status, notes,
               first_seen, last_seen) VALUES
               ('legacy-1', 'Draper', 'Analog ASIC Design Intern', 'Hardware', 100,
                'Hand-written note', 'shortlisted', 'keep me', 1000, 2000)""")
        con.execute("INSERT INTO runs (started, finished, fetched) VALUES (1000, 1001, 10)")
        con.commit()
        con.close()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_legacy_upgrade_adds_columns(self):
        con = db.connect(self.path)
        try:
            job_columns = {row[1] for row in con.execute("PRAGMA table_info(jobs)")}
            run_columns = {row[1] for row in con.execute("PRAGMA table_info(runs)")}
            self.assertTrue(NEW_JOB_COLUMNS <= job_columns, NEW_JOB_COLUMNS - job_columns)
            self.assertTrue(NEW_RUN_COLUMNS <= run_columns, NEW_RUN_COLUMNS - run_columns)
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 1)
        finally:
            con.close()

    def test_legacy_rows_are_preserved(self):
        con = db.connect(self.path)
        try:
            row = con.execute("SELECT * FROM jobs WHERE id='legacy-1'").fetchone()
            self.assertEqual(row["status"], "shortlisted")
            self.assertEqual(row["notes"], "keep me")
            self.assertEqual(row["summary"], "Hand-written note")
            self.assertEqual(row["status_changed_at"], 2000)
            self.assertIsNone(row["closed_at"])
            self.assertEqual(row["summary_edited"], 0)
        finally:
            con.close()

    def test_migration_is_idempotent(self):
        for _ in range(3):
            con = db.connect(self.path)
            con.close()
        con = db.connect(self.path)
        try:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)
        finally:
            con.close()

    def test_fresh_database_has_the_current_shape(self):
        fresh = os.path.join(self.dir, "fresh.db")
        con = db.connect(fresh)
        try:
            job_columns = {row[1] for row in con.execute("PRAGMA table_info(jobs)")}
            run_columns = {row[1] for row in con.execute("PRAGMA table_info(runs)")}
            self.assertTrue(NEW_JOB_COLUMNS <= job_columns)
            self.assertTrue(NEW_RUN_COLUMNS <= run_columns)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)
        finally:
            con.close()

    def test_indexes_exist(self):
        con = db.connect(self.path)
        try:
            indexes = {row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")}
            self.assertIn("idx_jobs_open", indexes)
            self.assertIn("idx_jobs_duplicate", indexes)
            self.assertIn("idx_jobs_fit", indexes)
        finally:
            con.close()

    def test_counts_shape(self):
        con = db.connect(self.path)
        try:
            counts = db.counts(con)
            self.assertEqual(counts["total"], 1)
            self.assertEqual(counts["open"], 1)
            self.assertEqual(counts["closed"], 0)
            self.assertEqual(counts["duplicates"], 0)
            self.assertEqual(counts["shortlisted"], 1)
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
