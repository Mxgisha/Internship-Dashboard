"""Scoring: deterministic, itemised, and clamped."""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for path in (os.path.dirname(HERE), HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import _bootstrap  # noqa: E402
import collect  # noqa: E402
from support import NOW, make_job  # noqa: E402

DAY = 86400


def base_job(**over):
    """No keyword hits, no freshness: 25 season + 20 category + 10 degree + 10 US = 65."""
    options = dict(title="Intern", category="Hardware", terms=("Summer 2027",),
                   locations=("San Jose, CA",), degrees=("Bachelor's",),
                   date_posted=NOW - 30 * DAY)
    options.update(over)
    return make_job(**options)


def signed_sum(reasons):
    return sum(int(re.match(r"^([+-]\d+)", reason).group(1)) for reason in reasons)


class SeasonTests(unittest.TestCase):
    def test_summer(self):
        fit, reasons = collect.score(base_job(), NOW)
        self.assertEqual(fit, 65)
        self.assertIn("+25 season Summer 2027", reasons)

    def test_winter(self):
        fit, _ = collect.score(base_job(terms=("Winter 2027",)), NOW)
        self.assertEqual(fit, 50)

    def test_fall(self):
        fit, _ = collect.score(base_job(terms=("Fall 2026",)), NOW)
        self.assertEqual(fit, 48)

    def test_best_of_multiple_terms(self):
        fit, reasons = collect.score(base_job(terms=("Summer 2026", "Summer 2027")), NOW)
        self.assertEqual(fit, 65)
        self.assertIn("+25 season Summer 2027", reasons)

    def test_no_season_is_penalised(self):
        fit, reasons = collect.score(base_job(terms=()), NOW)
        self.assertEqual(fit, 25)
        self.assertIn("-15 season not targeted", reasons)

    def test_case_insensitive(self):
        fit, _ = collect.score(base_job(terms=("summer 2027",)), NOW)
        self.assertEqual(fit, 65)


class CategoryTests(unittest.TestCase):
    def test_hardware(self):
        self.assertEqual(collect.score(base_job(), NOW)[0], 65)

    def test_ai_ml(self):
        self.assertEqual(collect.score(base_job(category="AI/ML/Data"), NOW)[0], 63)

    def test_software(self):
        self.assertEqual(collect.score(base_job(category="Software"), NOW)[0], 60)

    def test_unknown_category_adds_nothing(self):
        fit, reasons = collect.score(base_job(category="Marketing"), NOW)
        self.assertEqual(fit, 45)
        self.assertIn("+0 category Marketing", reasons)


class KeywordTests(unittest.TestCase):
    def test_keyword_boost(self):
        fit, reasons = collect.score(base_job(title="FPGA Intern"), NOW)
        self.assertEqual(fit, 83)
        self.assertIn("+18 'fpga'", reasons)

    def test_penalty(self):
        fit, reasons = collect.score(base_job(title="PhD Intern"), NOW)
        self.assertEqual(fit, 40)
        self.assertIn("-25 'phd'", reasons)

    def test_multiple_keywords_stack(self):
        fit, reasons = collect.score(base_job(title="Embedded Firmware Intern"), NOW)
        self.assertEqual(fit, 97)
        self.assertIn("+16 'embedded'", reasons)
        self.assertIn("+16 'firmware'", reasons)


class DegreeTests(unittest.TestCase):
    def test_bachelor_accepted(self):
        fit, reasons = collect.score(base_job(degrees=("Bachelor's",)), NOW)
        self.assertEqual(fit, 65)
        self.assertIn("+10 accepts bachelor's", reasons)

    def test_phd_only_penalised(self):
        fit, reasons = collect.score(base_job(degrees=("PhD",)), NOW)
        self.assertEqual(fit, 45)
        self.assertIn("-10 degrees phd", reasons)

    def test_masters_only_penalised(self):
        fit, _ = collect.score(base_job(degrees=("Master's",)), NOW)
        self.assertEqual(fit, 45)

    def test_empty_degrees_neutral(self):
        fit, _ = collect.score(base_job(degrees=()), NOW)
        self.assertEqual(fit, 55)


class FreshnessTests(unittest.TestCase):
    def test_under_seven_days(self):
        fit, reasons = collect.score(base_job(date_posted=NOW - DAY), NOW)
        self.assertEqual(fit, 75)
        self.assertIn("+10 posted <7d", reasons)

    def test_under_twenty_one_days(self):
        fit, reasons = collect.score(base_job(date_posted=NOW - 10 * DAY), NOW)
        self.assertEqual(fit, 70)
        self.assertIn("+5 posted <21d", reasons)

    def test_older_than_twenty_one_days(self):
        fit, _ = collect.score(base_job(date_posted=NOW - 30 * DAY), NOW)
        self.assertEqual(fit, 65)

    def test_boundary_seven_days(self):
        fit, reasons = collect.score(base_job(date_posted=NOW - 7 * DAY), NOW)
        self.assertEqual(fit, 70)
        self.assertIn("+5 posted <21d", reasons)

    def test_boundary_twenty_one_days(self):
        fit, _ = collect.score(base_job(date_posted=NOW - 21 * DAY), NOW)
        self.assertEqual(fit, 65)

    def test_future_date_gets_no_bonus(self):
        fit, reasons = collect.score(base_job(date_posted=NOW + DAY), NOW)
        self.assertEqual(fit, 65)
        self.assertNotIn("posted <7d", " ".join(reasons))

    def test_missing_date_gets_no_bonus(self):
        fit, _ = collect.score(base_job(date_posted=0), NOW)
        self.assertEqual(fit, 65)


class ClampAndExplainTests(unittest.TestCase):
    def test_high_clamp(self):
        job = base_job(
            title="Embedded Firmware FPGA ASIC RTL Verilog SoC DSP Hardware Electrical Silicon",
            locations=("Boston, MA",), date_posted=NOW - DAY)
        fit, reasons = collect.score(job, NOW)
        self.assertEqual(fit, 100)
        self.assertGreater(signed_sum(reasons), 100)

    def test_low_clamp(self):
        job = base_job(title="PhD Senior Sales Unpaid Intern", category="Other",
                       terms=(), degrees=("PhD",), locations=("Toronto, ON, Canada",))
        fit, reasons = collect.score(job, NOW)
        self.assertEqual(fit, 0)
        self.assertLess(signed_sum(reasons), 0)

    def test_reasons_sum_to_fit(self):
        jobs = [
            base_job(),
            base_job(title="Embedded Firmware Intern"),
            base_job(terms=(), category="Unknown"),
            base_job(degrees=(), locations=("Springfield",)),
            base_job(title="FPGA Intern", locations=("San Jose, CA",), date_posted=NOW - DAY),
            base_job(title="Senior Sales Intern", locations=("Toronto, ON, Canada",)),
        ]
        for job in jobs:
            with self.subTest(title=job["title"]):
                fit, reasons = collect.score(job, NOW)
                self.assertEqual(fit, signed_sum(reasons))
                self.assertTrue(all(re.match(r"^[+-]\d+ ", r) for r in reasons), reasons)

    def test_deterministic(self):
        job = base_job(title="Embedded Firmware Intern", locations=("Boston, MA",))
        self.assertEqual(collect.score(job, NOW), collect.score(job, NOW))

    def test_clock_is_not_read_when_injected(self):
        job = base_job(date_posted=NOW - DAY)
        first = collect.score(job, NOW)
        second = collect.score(job, NOW + 365 * DAY)
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
