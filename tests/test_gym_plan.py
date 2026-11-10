"""Gym planner input rules found on 2026-11-09 (scripts/add_gym.py class_ends).

    python3 -m unittest tests.test_gym_plan
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import add_gym  # noqa: E402


def ev(cal, day, start, end, title):
    return {"calendar": cal, "all_day": False, "title": title,
            "start": f"{day}T{start}+01:00", "end": f"{day}T{end}+01:00"}


class ClassEnds(unittest.TestCase):
    FEED, VISIBLE = "Feed", "Visible"

    def ends(self, events, window_from="2026-11-08T00:00+01:00"):
        with tempfile.TemporaryDirectory() as t:
            Path(t, "data").mkdir()
            Path(t, "data", "calendar.json").write_text(json.dumps(
                {"generated_at": "2026-11-09T20:00+01:00", "window": {"from": window_from}, "events": events}))
            with mock.patch.object(add_gym, "ROOT", Path(t)), mock.patch.object(add_gym, "FEED", self.FEED), \
                    mock.patch.object(add_gym, "VISIBLE", self.VISIBLE), \
                    mock.patch.object(add_gym.pm_env, "CLASS_CALENDARS", (self.FEED, self.VISIBLE)):
                return add_gym.class_ends()[0]

    def test_feed_copy_of_a_moved_session_is_ignored(self):
        # Marketing Ses. 13: the feed had Tue 12:00 AND Wed 12:30; the visible calendar only Tue.
        got = self.ends([
            ev(self.FEED, "2026-11-10", "12:00", "13:20", "MARKETING MANAGEMENT  (Ses. 13) Live in-person"),
            ev(self.VISIBLE, "2026-11-10", "12:00", "13:20", "MARKETING MANAGEMENT (Ses. 13-13)"),
            ev(self.FEED, "2026-11-11", "12:30", "13:50", "MARKETING MANAGEMENT  (Ses. 13) Live in-person"),
            ev(self.FEED, "2026-11-11", "11:00", "12:20", "CALCULUS FOR COMPUTER SCIENCE  (Ses. 23) Live in-person"),
            ev(self.VISIBLE, "2026-11-11", "11:00", "12:20", "CALCULUS FOR COMPUTER SCIENCE (Ses. 23-23)"),
        ])
        self.assertEqual(got["2026-11-11"], datetime(2026, 11, 11, 12, 20))
        self.assertEqual(got["2026-11-10"], datetime(2026, 11, 10, 13, 20))

    def test_feed_only_session_still_counts(self):
        # A session the visible calendar does not list at all is not a moved copy: keep it.
        got = self.ends([ev(self.FEED, "2026-11-12", "13:00", "14:20", "BIG HISTORY  (Ses. 9) Live in-person")])
        self.assertEqual(got["2026-11-12"], datetime(2026, 11, 12, 14, 20))

    def test_first_day_is_the_export_window_not_the_first_event(self):
        # Mon 9 had no class and the first event was Tue: Monday must not count as "before the export".
        self.ends([ev(self.VISIBLE, "2026-11-10", "12:00", "13:20", "MARKETING MANAGEMENT (Ses. 13-13)")])
        self.assertEqual(add_gym.FIRST_DAY, "2026-11-08")


if __name__ == "__main__":
    unittest.main()
