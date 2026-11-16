"""Configuration loading and validation."""
import copy
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for path in (os.path.dirname(HERE), HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import _bootstrap  # noqa: E402,F401
import config  # noqa: E402
import profile as P  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_example_loads(self):
        cfg = config.load(config.EXAMPLE_PATH)
        self.assertEqual(cfg["identity"]["name"], "Your Name")
        self.assertEqual(set(cfg["letters"]), set(config.LETTER_KEYS))
        self.assertEqual(cfg["scoring"]["min_fit"], 70)

    def test_missing_file_explains_the_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(config.ConfigError) as caught:
                config.load(os.path.join(tmp, "nope.toml"))
        self.assertIn("config.example.toml", str(caught.exception))
        self.assertIn("cp ", str(caught.exception))

    def test_invalid_toml_is_reported(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write("[scoring\nmin_fit = ")
            path = fh.name
        try:
            with self.assertRaises(config.ConfigError) as caught:
                config.load(path)
            self.assertIn("invalid TOML", str(caught.exception))
        finally:
            os.unlink(path)

    def base(self):
        return copy.deepcopy(config.load(config.EXAMPLE_PATH))

    def test_min_fit_range(self):
        cfg = self.base()
        cfg["scoring"]["min_fit"] = 101
        with self.assertRaises(config.ConfigError) as caught:
            config.validate(cfg)
        self.assertIn("between 0 and 100", str(caught.exception))

    def test_negative_max_jobs(self):
        cfg = self.base()
        cfg["scoring"]["max_jobs"] = -1
        with self.assertRaises(config.ConfigError):
            config.validate(cfg)

    def test_missing_identity_key(self):
        cfg = self.base()
        cfg["identity"].pop("email")
        with self.assertRaises(config.ConfigError) as caught:
            config.validate(cfg)
        self.assertIn("[identity].email", str(caught.exception))

    def test_missing_letters_key(self):
        cfg = self.base()
        cfg["letters"].pop("research")
        with self.assertRaises(config.ConfigError) as caught:
            config.validate(cfg)
        self.assertIn("[letters].research", str(caught.exception))

    def test_weight_must_be_integer(self):
        cfg = self.base()
        cfg["scoring"]["title_keywords"]["fpga"] = "lots"
        with self.assertRaises(config.ConfigError) as caught:
            config.validate(cfg)
        self.assertIn("must be an integer", str(caught.exception))

    def test_company_table_shape(self):
        cfg = self.base()
        cfg["companies"] = {"Acme": {"summary": "ok", "aliases": "not-a-list"}}
        with self.assertRaises(config.ConfigError):
            config.validate(cfg)

    def test_profile_reads_the_fixture(self):
        self.assertEqual(P.IDENTITY["name"], "Test User")
        self.assertEqual(P.SEASONS["Summer 2027"], 25)
        self.assertEqual(P.MIN_FIT, 70)
        self.assertEqual(P.MAX_JOBS, 400)
        self.assertIn("boston", P.PREFERRED_LOCATIONS)

    def test_profile_companies_and_aliases(self):
        self.assertEqual(P.COMPANY_ALIASES["RTX"], "Raytheon")
        self.assertEqual(P.company_summary("RTX", 2), P.COMPANY_PROFILES["Raytheon"])
        self.assertIn("No profile on file for Nobody", P.company_summary("Nobody", 1))

    def test_env_points_at_fixture(self):
        self.assertTrue(config.path_from_env().endswith("fixture_config.toml"))

    def test_user_config_is_gitignored(self):
        with open(os.path.join(os.path.dirname(HERE), ".gitignore")) as fh:
            ignored = fh.read()
        self.assertIn("config.toml", ignored)


if __name__ == "__main__":
    unittest.main()
