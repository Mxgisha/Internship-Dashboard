"""The repository must not contain the user's identity outside config.toml."""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for path in (ROOT, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import _bootstrap  # noqa: E402,F401

SOURCES = [
    "collect.py", "config.py", "db.py", "letters.py", "profile.py", "server.py",
    "README.md", "BRIEF.md", "PLAN.md", "Makefile", ".gitignore",
    os.path.join("tests", "support.py"),
    os.path.join("tests", "fixture_config.toml"),
]

# Deliberately blunt: names, school domain, and the phone number from the
# original hardcoded letters. config.toml is excluded because it is personal.
PATTERNS = [
    r"peter", r"wiehler", r"tufts", r"929\)\s*216", r"216-8804",
]


class DepersonalizationTests(unittest.TestCase):
    def test_no_identity_in_source_or_docs(self):
        for relative in SOURCES:
            path = os.path.join(ROOT, relative)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for pattern in PATTERNS:
                with self.subTest(file=relative, pattern=pattern):
                    self.assertNotRegex(text, re.compile(pattern, re.IGNORECASE))

    def test_example_config_uses_placeholders(self):
        with open(os.path.join(ROOT, "config.example.toml"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("Your Name", text)
        self.assertIn("you@example.com", text)
        for pattern in PATTERNS:
            self.assertNotRegex(text, re.compile(pattern, re.IGNORECASE))

    def test_personal_config_is_not_tracked(self):
        # .gitignore is the enforcement mechanism; config.toml itself is local.
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as fh:
            lines = [line.strip() for line in fh]
        self.assertIn("config.toml", lines)


if __name__ == "__main__":
    unittest.main()
