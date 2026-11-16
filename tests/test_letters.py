"""Letter drafts: three variants, a hook placeholder, unique filenames."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for path in (os.path.dirname(HERE), HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import _bootstrap  # noqa: E402
import collect  # noqa: E402
import db  # noqa: E402
import letters as L  # noqa: E402
from support import NOW, TempDB, make_job, silent  # noqa: E402


class LetterTests(unittest.TestCase):
    def setUp(self):
        self.env = TempDB()
        self.env.__enter__()
        self.con = self.env.con

    def tearDown(self):
        self.env.__exit__(None, None, None)

    def seed(self, jobs):
        collect.collect(self.con, jobs, now=NOW, fresh=True, log=silent)

    def test_three_variants_with_hook(self):
        self.seed([make_job(1)])
        job = self.con.execute("SELECT * FROM jobs WHERE id='id-001'").fetchone()
        bodies = []
        for variant in ("technical", "builder", "consulting"):
            text = L.build(job, variant)
            self.assertIn("[HOOK", text)
            self.assertIn("Acme", text)
            self.assertIn(job["title"], text)
            bodies.append(text)
        self.assertEqual(len(set(bodies)), 3)

    def test_build_uses_config_identity_and_prose(self):
        self.seed([make_job(1)])
        job = self.con.execute("SELECT * FROM jobs WHERE id='id-001'").fetchone()
        text = L.build(job, "technical")
        self.assertIn("Test University", text)
        self.assertIn("test@example.com", text)
        self.assertIn("(000) 000-0000", text)
        self.assertIn("RESEARCH_FACT", text)
        self.assertIn("BUILDING_FACT", text)
        self.assertIn("Sincerely,", text)

    def test_write_letters_stores_three_and_writes_files(self):
        self.seed([make_job(1)])
        made = L.write_letters(self.con, "id-001")
        self.assertEqual(made, 3)
        count = self.con.execute(
            "SELECT COUNT(*) FROM letters WHERE job_id='id-001'").fetchone()[0]
        self.assertEqual(count, 3)
        files = sorted(os.listdir(db.LETTERS))
        self.assertEqual(len(files), 3)
        self.assertTrue(all("id-001" in name for name in files), files)

    def test_same_role_different_jobs_do_not_collide(self):
        self.seed([make_job(1), make_job(2)])
        L.write_letters(self.con, "id-001")
        L.write_letters(self.con, "id-002")
        files = sorted(os.listdir(db.LETTERS))
        self.assertEqual(len(files), 6)
        self.assertEqual(len(set(files)), 6)

    def test_missing_job_writes_nothing(self):
        self.assertEqual(L.write_letters(self.con, "nope"), 0)

    def test_classify(self):
        self.assertEqual(L.classify({"title": "ASIC Design Intern", "category": "Hardware"}),
                         "hardware")
        self.assertEqual(L.classify({"title": "Product Analyst Intern", "category": "Product"}),
                         "consulting")
        self.assertEqual(L.classify({"title": "Software Engineer Intern", "category": "Software"}),
                         "software")

    def test_refresh_replaces_body(self):
        self.seed([make_job(1)])
        L.write_letters(self.con, "id-001")
        first = self.con.execute(
            "SELECT body FROM letters WHERE job_id='id-001' AND variant='technical'").fetchone()[0]
        self.con.execute("UPDATE jobs SET company='Acme Renamed' WHERE id='id-001'")
        self.con.commit()
        L.write_letters(self.con, "id-001")
        second = self.con.execute(
            "SELECT body FROM letters WHERE job_id='id-001' AND variant='technical'").fetchone()[0]
        self.assertNotEqual(first, second)
        self.assertIn("Acme Renamed", second)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM letters WHERE job_id='id-001'").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
