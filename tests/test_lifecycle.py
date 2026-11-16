"""Lifecycle: insert, refresh, close, reopen, summary provenance, dry runs."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for path in (os.path.dirname(HERE), HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import _bootstrap  # noqa: E402
import collect  # noqa: E402
import profile as P  # noqa: E402
from support import NOW, TempDB, make_job, silent  # noqa: E402

DAY = 86400


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.env = TempDB()
        self.env.__enter__()
        self.con = self.env.con

    def tearDown(self):
        self.env.__exit__(None, None, None)

    def run_collect(self, jobs, now=NOW, fresh=True, dry_run=False, show_all=False):
        return collect.collect(self.con, jobs, now=now, fresh=fresh, dry_run=dry_run,
                               show_all=show_all, log=silent)

    def row(self, job_id):
        row = self.con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def test_insert_and_counts(self):
        stats = self.run_collect([make_job(1), make_job(2, title="ASIC Design Intern")])
        self.assertEqual(stats["inserted"], 2)
        self.assertEqual(stats["matched"], 2)
        self.assertEqual(self.row("id-001")["status"], "new")
        self.assertIsNone(self.row("id-001")["closed_at"])
        self.assertEqual(self.row("id-001")["first_seen"], NOW)
        self.assertEqual(self.row("id-001")["last_seen"], NOW)

    def test_duplicate_rows_are_marked_not_dropped(self):
        stats = self.run_collect([make_job(1), make_job(2, locations=("Boston, MA",))])
        self.assertEqual(stats["inserted"], 2)
        self.assertEqual(stats["duplicates"], 1)
        rep = self.row("id-001")
        dup = self.row("id-002")
        self.assertIsNone(rep["duplicate_of"])
        self.assertEqual(dup["duplicate_of"], "id-001")
        self.assertEqual(rep["locations"], '["San Jose, CA", "Boston, MA"]')

    def test_close_and_reopen(self):
        self.run_collect([make_job(1), make_job(2, title="ASIC Design Intern")])
        stats = self.run_collect([make_job(1)], now=NOW + 3600)
        self.assertEqual(stats["closed"], 1)
        self.assertIsNotNone(self.row("id-002")["closed_at"])
        self.assertIsNone(self.row("id-001")["closed_at"])

        stats = self.run_collect([make_job(1), make_job(2, title="ASIC Design Intern")],
                                 now=NOW + 7200)
        self.assertEqual(stats["closed"], 0)
        self.assertIsNone(self.row("id-002")["closed_at"])

    def test_offline_run_does_not_close(self):
        self.run_collect([make_job(1)])
        stats = self.run_collect([], now=NOW + 3600, fresh=False)
        self.assertEqual(stats["closed"], 0)
        self.assertIsNone(self.row("id-001")["closed_at"])

    def test_offline_run_does_not_reopen(self):
        self.run_collect([make_job(1)])
        self.run_collect([], now=NOW + 3600, fresh=True)
        self.assertIsNotNone(self.row("id-001")["closed_at"])
        self.run_collect([make_job(1)], now=NOW + 7200, fresh=False)
        self.assertIsNotNone(self.row("id-001")["closed_at"])

    def test_status_and_notes_survive(self):
        self.run_collect([make_job(1)])
        self.con.execute("UPDATE jobs SET status='shortlisted', notes='talked to recruiter' WHERE id='id-001'")
        self.con.commit()
        self.run_collect([make_job(1)], now=NOW + 3600)
        row = self.row("id-001")
        self.assertEqual(row["status"], "shortlisted")
        self.assertEqual(row["notes"], "talked to recruiter")

    def test_reopen_preserves_status(self):
        self.run_collect([make_job(1)])
        self.run_collect([], now=NOW + 3600)
        self.con.execute("UPDATE jobs SET status='applied' WHERE id='id-001'")
        self.con.commit()
        self.run_collect([make_job(1)], now=NOW + 7200)
        self.assertEqual(self.row("id-001")["status"], "applied")

    def test_summary_refreshes_until_edited(self):
        self.run_collect([make_job(1, company="Acme")])
        self.assertIn("No profile on file for Acme", self.row("id-001")["summary"])

        P.COMPANY_PROFILES["Acme"] = "Curated Acme summary"
        self.addCleanup(P.COMPANY_PROFILES.pop, "Acme", None)
        self.run_collect([make_job(1, company="Acme")], now=NOW + 3600)
        self.assertEqual(self.row("id-001")["summary"], "Curated Acme summary")

        self.con.execute("UPDATE jobs SET summary='My own note', summary_edited=1 WHERE id='id-001'")
        self.con.commit()
        self.run_collect([make_job(1, company="Acme")], now=NOW + 7200)
        self.assertEqual(self.row("id-001")["summary"], "My own note")

        self.con.execute("UPDATE jobs SET summary_edited=0 WHERE id='id-001'")
        self.con.commit()
        self.run_collect([make_job(1, company="Acme")], now=NOW + 10800)
        self.assertEqual(self.row("id-001")["summary"], "Curated Acme summary")

    def test_company_alias_resolves(self):
        self.run_collect([make_job(1, company="RTX")])
        self.assertEqual(self.row("id-001")["summary"], P.COMPANY_PROFILES["Raytheon"])

    def test_below_threshold_existing_row_is_rescored(self):
        self.run_collect([make_job(1, title="Intern", locations=("San Jose, CA",))])
        self.assertEqual(self.row("id-001")["fit"], 75)
        self.run_collect([make_job(1, title="Intern", locations=("Toronto, ON, Canada",))],
                         now=NOW + 3600)
        row = self.row("id-001")
        self.assertEqual(row["fit"], 50)
        self.assertIsNone(row["closed_at"])

    def test_invisible_listing_is_closed(self):
        self.run_collect([make_job(1), make_job(2, title="ASIC Design Intern")])
        self.run_collect([make_job(1), make_job(2, title="ASIC Design Intern", visible=False)],
                         now=NOW + 3600)
        self.assertIsNotNone(self.row("id-002")["closed_at"])

    def test_acceptance_no_stale_open_rows(self):
        self.run_collect([make_job(1), make_job(2, title="ASIC Design Intern")])
        later = NOW + 3600
        self.run_collect([make_job(1)], now=later)
        stale = self.con.execute(
            "SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL AND last_seen < ?",
            (later,)).fetchone()[0]
        self.assertEqual(stale, 0)

    def test_dry_run_writes_nothing(self):
        self.run_collect([make_job(1)])
        stats = self.run_collect([make_job(1), make_job(2, title="ASIC Design Intern")],
                                 now=NOW + 3600, dry_run=True)
        self.assertEqual(stats["would_insert"], 1)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)
        self.assertIsNone(self.row("id-002"))

    def test_dry_run_reports_closures(self):
        self.run_collect([make_job(1)])
        stats = self.run_collect([], now=NOW + 3600, dry_run=True)
        self.assertEqual(stats["would_close"], 1)
        self.assertIsNone(self.row("id-001")["closed_at"])

    def test_show_all_ignores_threshold(self):
        low = make_job(1, title="Intern", terms=(), category="Other",
                       locations=("Toronto, ON, Canada",))
        self.assertEqual(collect.score(low, NOW)[0] < P.MIN_FIT, True)
        stats = self.run_collect([low], show_all=True)
        self.assertEqual(stats["inserted"], 1)
        self.assertEqual(self.row("id-001")["fit"], collect.score(low, NOW)[0])

    def test_status_follows_representative_change(self):
        self.run_collect([make_job(1), make_job(2)])
        self.con.execute(
            "UPDATE jobs SET status='shortlisted', notes='keep me', status_changed_at=? "
            "WHERE id='id-001'", (NOW + 100,))
        self.con.commit()

        self.run_collect([make_job(2)], now=NOW + 3600)
        rep = self.row("id-002")
        self.assertIsNone(rep["duplicate_of"])
        self.assertEqual(rep["status"], "shortlisted")
        self.assertEqual(rep["notes"], "keep me")
        self.assertIsNotNone(self.row("id-001")["closed_at"])

    def test_representative_human_status_is_not_overwritten(self):
        self.run_collect([make_job(1), make_job(2)])
        self.con.execute("UPDATE jobs SET status='shortlisted' WHERE id='id-001'")
        self.con.execute("UPDATE jobs SET status='applied' WHERE id='id-002'")
        self.con.commit()

        self.run_collect([make_job(2)], now=NOW + 3600)
        self.assertEqual(self.row("id-002")["status"], "applied")

    def test_edited_summary_follows_representative_change(self):
        self.run_collect([make_job(1), make_job(2)])
        self.con.execute(
            "UPDATE jobs SET summary='My role note', summary_edited=1 WHERE id='id-001'")
        self.con.commit()

        self.run_collect([make_job(2)], now=NOW + 3600)
        rep = self.row("id-002")
        self.assertEqual(rep["summary"], "My role note")
        self.assertEqual(rep["summary_edited"], 1)

    def test_old_closed_donor_is_not_inherited(self):
        self.run_collect([make_job(1), make_job(2)])
        self.con.execute("UPDATE jobs SET status='shortlisted', closed_at=? WHERE id='id-001'",
                         (NOW - 60 * DAY,))
        self.con.commit()
        self.run_collect([make_job(2)], now=NOW + 3600)
        self.assertEqual(self.row("id-002")["status"], "new")

    def test_duplicate_filter_counts(self):
        self.run_collect([make_job(1), make_job(2)])
        counts = collect.db.counts(self.con)
        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["duplicates"], 1)
        self.assertEqual(counts["open"], 2)


if __name__ == "__main__":
    unittest.main()
