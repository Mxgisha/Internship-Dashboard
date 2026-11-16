"""De-duplication: merge locations, keep a stable representative, prefer ATS URLs."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for path in (os.path.dirname(HERE), HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import _bootstrap  # noqa: E402
import collect  # noqa: E402
from support import NOW, make_job  # noqa: E402


def scored(*jobs):
    return [(collect.score(job, NOW)[0], collect.score(job, NOW)[1], job) for job in jobs]


class DedupeTests(unittest.TestCase):
    def test_same_role_merges(self):
        a = make_job(1, locations=("San Jose, CA",))
        b = make_job(2, locations=("Boston, MA",))
        reps, members = collect.dedupe(scored(a, b), NOW)
        self.assertEqual(len(reps), 1)
        self.assertEqual(reps[0][2]["id"], "id-001")
        self.assertEqual(reps[0][2]["locations"], ["San Jose, CA", "Boston, MA"])
        self.assertEqual([m["id"] for m in members["id-001"]], ["id-002"])

    def test_representative_is_lowest_id_regardless_of_order(self):
        a = make_job(9)
        b = make_job(3)
        reps, _ = collect.dedupe(scored(a, b), NOW)
        self.assertEqual(reps[0][2]["id"], "id-003")

    def test_different_titles_do_not_merge(self):
        a = make_job(1, title="Embedded Firmware Intern")
        b = make_job(2, title="ASIC Design Intern")
        reps, members = collect.dedupe(scored(a, b), NOW)
        self.assertEqual(len(reps), 2)
        self.assertEqual(members["id-001"], [])

    def test_company_match_is_case_insensitive(self):
        a = make_job(1, company="Acme")
        b = make_job(2, company="ACME")
        reps, _ = collect.dedupe(scored(a, b), NOW)
        self.assertEqual(len(reps), 1)

    def test_best_url_wins(self):
        a = make_job(1, url="https://simplify.jobs/p/abc")
        b = make_job(2, url="https://boards.greenhouse.io/acme/jobs/2")
        reps, _ = collect.dedupe(scored(a, b), NOW)
        self.assertEqual(reps[0][2]["url"], "https://boards.greenhouse.io/acme/jobs/2")

    def test_ats_beats_generic_host(self):
        self.assertLess(collect.url_rank("https://boards.greenhouse.io/x"),
                        collect.url_rank("https://example.com/x"))
        self.assertLess(collect.url_rank("https://example.com/x"),
                        collect.url_rank("https://simplify.jobs/p/x"))

    def test_earliest_date_is_kept(self):
        a = make_job(1, date_posted=NOW - 3 * 86400)
        b = make_job(2, date_posted=NOW - 30 * 86400)
        reps, _ = collect.dedupe(scored(a, b), NOW)
        self.assertEqual(reps[0][2]["date_posted"], NOW - 30 * 86400)

    def test_merged_location_changes_fit(self):
        a = make_job(1, title="Intern", locations=("San Jose, CA",))
        b = make_job(2, title="Intern", locations=("Boston, MA",))
        alone = collect.score(a, NOW)[0]
        reps, _ = collect.dedupe(scored(a, b), NOW)
        self.assertEqual(reps[0][0], alone + 8)

    def test_terms_and_degrees_merge(self):
        a = make_job(1, terms=("Summer 2026",))
        b = make_job(2, terms=("Summer 2027", "Fall 2026"), degrees=("Master's", "Bachelor's"))
        reps, _ = collect.dedupe(scored(a, b), NOW)
        self.assertEqual(reps[0][2]["terms"], ["Summer 2026", "Summer 2027", "Fall 2026"])
        self.assertIn("Master's", reps[0][2]["degrees"])

    def test_members_are_copies_not_aliases(self):
        a = make_job(1)
        b = make_job(2, locations=("Boston, MA",))
        _, members = collect.dedupe(scored(a, b), NOW)
        members["id-001"][0]["locations"].append("MUTATED")
        self.assertEqual(b["locations"], ["Boston, MA"])


if __name__ == "__main__":
    unittest.main()
