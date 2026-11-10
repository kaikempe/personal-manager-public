"""The Upcoming page's two rules: a deadline whose date is unclear is never shown on a day, and a task's `start` is
never a deadline.

    python3 -m unittest discover -s tests

Standard library only. No network, no Calendar, no Reminders.
"""
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

os.environ["PM_NO_NOTIFY"] = "1"   # a test must never notify the real user

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "dashboard"))

import server  # noqa: E402
import state_refresh  # noqa: E402

ZONE = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 10, 10, 0, tzinfo=ZONE)
QUIZ = {"course": "CALCULUS FOR COMPUTER SCIENCE", "source": "exam", "kind": "quiz", "title": "Quiz", "done": False,
        "status": "open", "due": "2026-11-09T09:00+01:00", "ends": "2026-11-09T10:20+01:00",
        "timetable_due": "2026-11-10T09:00+01:00", "timetable_ends": "2026-11-10T10:20+01:00",
        "date_source": "announcement", "date_from": {"title": "Quiz 2 and Problem Set 4", "created": "2026-11-09T10:15:39.504Z"}}


def event(title, start, calendar="Private", end=None):
    return {"title": title, "start": start, "end": end or start, "calendar": calendar, "all_day": False}


class UnclearDates(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(server, "TZ", ZONE)
        p.start()
        self.addCleanup(p.stop)

    def rows(self, events=(), now=NOW, rows=None):
        return server.open_deadlines(rows or [QUIZ], now, events, "Private")

    def test_the_users_own_calendar_settles_it(self):
        ev = [event("Calculus quiz", "2026-11-16T12:00+01:00", end="2026-11-16T13:20+01:00")]
        [row] = self.rows(ev)
        self.assertIsNone(row["unclear"])
        self.assertEqual((row["due"][:16], row["ends"][:16]), ("2026-11-16T12:00", "2026-11-16T13:20"))
        self.assertEqual(row["flag"], 'date from your calendar: "Calculus quiz"')

    def test_only_a_fitting_event_in_the_writable_calendar_counts(self):
        for ev in ([event("Calculus quiz", "2026-11-16T12:00+01:00", calendar="School")],      # not the writable calendar
                   [event("Calculus lecture", "2026-11-16T12:00+01:00")],                        # not the kind of exam
                   [event("Algebra quiz", "2026-11-16T12:00+01:00")],                            # not the course
                   [event("Calculus quiz", "2026-11-08T12:00+01:00")],                           # before the announcement
                   [event("Calculus quiz", "2026-12-20T12:00+01:00")],                           # long after it
                   [event("Calculus quiz", "2026-11-16T12:00+01:00"), event("Quiz calculus", "2026-11-17T12:00+01:00")]):  # two fit
            with self.subTest(ev=ev):
                [row] = self.rows(ev)
                self.assertTrue(row["unclear"])

    def test_an_unsettled_row_has_no_day_but_stays_for_two_weeks(self):
        [row] = self.rows()
        self.assertEqual(row["unclear"]["timetable"][:16], "2026-11-10T09:00")
        later = datetime(2026, 11, 20, 12, 0, tzinfo=ZONE)          # the timetable slot is long past
        self.assertEqual(len(self.rows(now=later)), 1)
        self.assertEqual(self.rows(now=datetime(2026, 11, 24, 12, 0, tzinfo=ZONE)), [])

    def test_a_plausible_announcement_date_still_says_it_moved(self):
        moved = {**QUIZ, "due": "2026-11-16T12:00+01:00", "ends": "2026-11-16T13:20+01:00"}
        [row] = self.rows(rows=[moved])
        self.assertIsNone(row["unclear"])
        self.assertTrue(row["flag"].startswith("moved by announcement"))
        self.assertIn("was Tue 10 Nov 09:00", row["flag"])

    def test_overview_keeps_unclear_rows_out_of_every_dated_list(self):
        with mock.patch.object(server, "calendar_events", return_value=({}, [])), \
             mock.patch.object(server, "read_json", side_effect=lambda p, d=None: {"deadlines": [QUIZ]} if p == server.BB_DATA else d), \
             mock.patch.object(server, "load_items", return_value={"items": []}), \
             mock.patch.object(server, "registry", return_value=[]), mock.patch.object(server, "health_rows", return_value=[]), \
             mock.patch.object(server, "datetime", wraps=datetime) as dt:
            dt.now.return_value = NOW
            o = server.overview()
        self.assertEqual(o["bb"]["deadlines"], [])
        self.assertEqual(len(o["bb"]["unclear"]), 1)

    def test_state_block_and_alert(self):
        o = {"now": NOW.isoformat(), "calendar": {}, "items": [], "proposals": [], "health": [],
             "bb": {"deadlines": [], "unclear": self.rows()}}
        text = state_refresh.build(o)
        self.assertIn("DATE UNCLEAR", text)
        self.assertNotIn("Today:", text)
        self.assertIn("Nothing graded or due", text)
        sent = []
        state_refresh.alerts(o, datetime(2026, 11, 10, 10, 0), send=lambda t, phone=False, key=None: sent.append((key, t)))
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1], "Calculus for Computer Science quiz: the date is unclear (timetable says Tue 10 Nov 09:00, "
                                     "an announcement changed it). Read the announcement.")

    def test_a_settled_row_sends_no_alert(self):
        ev = [event("Calculus quiz", "2026-11-16T12:00+01:00")]
        o = {"now": NOW.isoformat(), "items": [], "proposals": [], "health": [],
             "bb": {"deadlines": self.rows(ev), "unclear": []}}
        sent = []
        state_refresh.alerts(o, datetime(2026, 11, 10, 10, 0), send=lambda t, phone=False, key=None: sent.append(t))
        self.assertEqual(sent, [])


class StartAfterTasks(unittest.TestCase):
    TASK = {"type": "task", "title": "Start prep", "status": "open", "start": "2026-11-07", "created": "2026-10-25"}

    def test_start_is_never_a_deadline(self):
        self.assertEqual(server.task_when(self.TASK, "2026-11-10"),
                         {"kind": "open", "date": None, "hint": "can start since 7 Nov"})
        self.assertEqual(server.task_when(self.TASK, "2026-11-07")["hint"], "can start today")
        self.assertEqual(server.task_when(self.TASK, "2026-11-05"),
                         {"kind": "later", "date": "2026-11-07", "hint": "from 7 Nov"})

    def test_due_keeps_its_meaning(self):
        self.assertEqual(server.task_when({**self.TASK, "due": "2026-11-08"}, "2026-11-10")["kind"], "due")
        self.assertEqual(server.task_when({"type": "task", "title": "x"}, "2026-11-10")["kind"], "none")

    def test_state_block_never_calls_it_a_deadline(self):
        o = {"now": NOW.isoformat(), "calendar": {}, "proposals": [], "bb": {"deadlines": []},
             "items": [{**self.TASK, "when": server.task_when(self.TASK, "2026-11-10")}]}
        text = state_refresh.build(o)
        self.assertIn("- Start prep | can start since 7 Nov", text)
        self.assertNotIn("due 2026-11-07", text)

    def test_a_task_that_cannot_start_yet_is_not_called_undated(self):
        self.assertIsNone(state_refresh.undated_days({**self.TASK, "start": "2026-11-20"}, NOW.date()))
        self.assertEqual(state_refresh.undated_days(self.TASK, NOW.date()), 16)


if __name__ == "__main__":
    unittest.main()
