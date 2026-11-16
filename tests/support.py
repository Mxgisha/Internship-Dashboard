"""Shared helpers for the test suite. Standard library only."""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import db  # noqa: E402

# Fixed clock: 2027-01-15-ish. Every scorer test injects this.
NOW = 1_800_000_000


def make_job(i=1, company="Acme", title="Embedded Firmware Intern", category="Hardware",
             locations=("San Jose, CA",), terms=("Summer 2027",), degrees=("Bachelor's",),
             date_posted=None, active=True, visible=True, url=None, **over):
    posted = NOW - 86400 if date_posted is None else date_posted
    job = {
        "id": f"id-{i:03d}",
        "company_name": company,
        "title": title,
        "category": category,
        "url": url if url is not None else f"https://boards.greenhouse.io/acme/jobs/{i}",
        "locations": list(locations),
        "terms": list(terms),
        "degrees": list(degrees),
        "date_posted": posted,
        "date_updated": posted,
        "active": active,
        "is_visible": visible,
        "sponsorship": "Other",
        "source": "Simplify",
    }
    job.update(over)
    return job


class TempDB:
    """Point db at a throwaway file and restore the previous globals on exit."""

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="jobhunt-test-")
        self.saved = (db.DB_PATH, db.LETTERS, db.LOGS)
        self.saved_log = db.log
        db.DB_PATH = os.path.join(self.dir, "test.db")
        db.LETTERS = os.path.join(self.dir, "letters")
        db.LOGS = os.path.join(self.dir, "logs")
        db.log = silent
        self.con = db.connect()
        return self

    def __exit__(self, *exc):
        try:
            self.con.close()
        finally:
            db.DB_PATH, db.LETTERS, db.LOGS = self.saved
            db.log = self.saved_log
            shutil.rmtree(self.dir, ignore_errors=True)
        return False


def silent(*_args, **_kwargs):
    pass
