"""Location parsing: the cases that motivated the rewrite."""
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

US = [
    "San Jose, CA", "SF", "NYC", "LA", "Boston", "Medford", "Remote", "Remote, US",
    "Remote in USA", "Remote (US)", "U.S.", "US", "California", "Texas",
    "Massachusetts", "Washington", "Washington, DC", "New Mexico", "Indiana",
    "Indianapolis, IN", "Austin, Texas", "Seattle, Washington", "New York, NY",
    "Ontario, CA", "Nashville, TN", "Bay Area", "Silicon Valley",
]
FOREIGN = [
    "Toronto, ON, Canada", "Vancouver, BC", "Montreal, QC", "Ottawa, ON, Canada",
    "London, UK", "Cambridge, UK", "Remote in UK", "Remote in Canada",
    "Berlin, Germany", "Zürich, Switzerland", "Mexico City", "Bangalore, India",
    "Ontario", "EMEA", "Singapore",
]
UNKNOWN = ["", "Hybrid", "Springfield", "Multiple Locations"]


class LocationTests(unittest.TestCase):
    def test_us_matrix(self):
        for location in US:
            with self.subTest(location=location):
                self.assertEqual(collect.classify_location(location), "us")

    def test_foreign_matrix(self):
        for location in FOREIGN:
            with self.subTest(location=location):
                self.assertEqual(collect.classify_location(location), "foreign")

    def test_unknown_matrix(self):
        for location in UNKNOWN:
            with self.subTest(location=location):
                self.assertEqual(collect.classify_location(location), "unknown")

    def test_indianapolis_is_not_india(self):
        self.assertEqual(collect.classify_location("Indianapolis, IN"), "us")
        self.assertEqual(collect.classify_location("Bangalore, India"), "foreign")

    def test_new_mexico_is_not_mexico(self):
        self.assertEqual(collect.classify_location("New Mexico"), "us")
        self.assertEqual(collect.classify_location("Mexico City"), "foreign")

    def test_cambridge_disambiguated_by_country(self):
        self.assertEqual(collect.classify_location("Cambridge, MA"), "us")
        self.assertEqual(collect.classify_location("Cambridge, UK"), "foreign")

    def test_any_us_location_wins(self):
        self.assertEqual(collect.location_verdict(["Toronto, ON, Canada", "New York, NY"]), "us")

    def test_unknown_is_preserved_when_mixed(self):
        self.assertEqual(collect.location_verdict(["Springfield", "Toronto, ON, Canada"]), "foreign")
        self.assertEqual(collect.location_verdict(["Springfield"]), "unknown")

    def test_is_us_is_boolean_wrapper(self):
        self.assertTrue(collect.is_us(["Boston"]))
        self.assertFalse(collect.is_us(["Toronto, ON, Canada"]))
        self.assertFalse(collect.is_us(["Springfield"]))

    def test_unknown_location_costs_nothing(self):
        fit, reasons = collect.score(make_job(title="Intern", locations=["Springfield"]), NOW)
        self.assertIn("+0 location unknown", reasons)
        self.assertNotIn("-15 outside US", reasons)

    def test_unknown_loses_to_us(self):
        unknown_fit, _ = collect.score(make_job(title="Intern", locations=["Springfield"]), NOW)
        us_fit, _ = collect.score(make_job(title="Intern", locations=["San Jose, CA"]), NOW)
        self.assertEqual(us_fit - unknown_fit, 10)

    def test_preferred_location_bonus(self):
        fit, reasons = collect.score(make_job(title="Intern", locations=["Boston, MA"]), NOW)
        self.assertIn("+10 US location", reasons)
        self.assertIn("+8 preferred location", reasons)
        plain, _ = collect.score(make_job(title="Intern", locations=["San Jose, CA"]), NOW)
        self.assertEqual(fit - plain, 8)

    def test_foreign_penalty(self):
        fit, reasons = collect.score(make_job(title="Intern", locations=["Toronto, ON, Canada"]), NOW)
        self.assertIn("-15 outside US", reasons)
        us_fit, _ = collect.score(make_job(title="Intern", locations=["San Jose, CA"]), NOW)
        self.assertEqual(us_fit - fit, 25)


if __name__ == "__main__":
    unittest.main()
