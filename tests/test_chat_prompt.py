"""The chat's system prompt is the same for every user: no owner's pronouns, school or habits baked in.

    python3 -m unittest discover -s tests
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))
import server  # noqa: E402  (importing does not start the server)


class ChatPrompt(unittest.TestCase):
    def test_no_gendered_pronouns(self):
        self.assertIsNone(re.search(r"\b(he|his|him|she|her|hers)\b", server.CHAT_SYSTEM, re.I))

    def test_no_owner_specifics(self):
        for word in ("IE University", "Madrid"):
            self.assertNotIn(word, server.CHAT_SYSTEM)

    def test_delete_rule_names_the_writable_calendar(self):
        self.assertIn(f"for an event in the {server.ACTION_CAL} calendar", server.CHAT_SYSTEM)

    def test_travel_mode_comes_from_the_working_rules(self):
        self.assertIn("travel mode the working rules give", server.CHAT_SYSTEM)


if __name__ == "__main__":
    unittest.main()
