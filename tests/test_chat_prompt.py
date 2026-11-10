"""The chat's system prompt is the same for every user: no owner's pronouns, name, school or habits baked in.
The owner's own rules live in config/chat_rules.md and plugins, and are added at run time (server.chat_system()).

    python3 -m unittest discover -s tests
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))
import server  # noqa: E402  (importing does not start the server)
import pm_env  # noqa: E402


class ChatPrompt(unittest.TestCase):
    def test_no_gendered_pronouns(self):
        self.assertIsNone(re.search(r"\b(he|his|him|she|her|hers)\b", server.CHAT_SYSTEM, re.I))

    def test_no_owner_specifics(self):
        for word in [pm_env.OWNER, pm_env.get("PM_UNIVERSITY"), *pm_env.READONLY_CALENDARS,
                     pm_env.TIMEZONE.split("/")[-1].replace("_", " ")]:
            if word and word != "UTC":
                self.assertNotIn(word, server.CHAT_SYSTEM)

    def test_delete_rule_names_the_writable_calendar(self):
        self.assertIn(f"for an event in the {server.ACTION_CAL} calendar", server.CHAT_SYSTEM)

    def test_travel_mode_comes_from_the_working_rules(self):
        self.assertIn("travel mode the working rules give", server.CHAT_SYSTEM)

    def test_own_rules_and_plugins_are_appended(self):
        full = server.chat_system()
        self.assertTrue(full.startswith(server.CHAT_SYSTEM))
        own = pm_env.chat_rules()
        if own:
            self.assertIn(own, full)
        for kind, spec in server.PLUGIN_ACTIONS.items():
            self.assertIn(spec["example"], full)


if __name__ == "__main__":
    unittest.main()
