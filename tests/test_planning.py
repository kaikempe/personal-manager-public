"""Rules behind the plan: which deadline dates are trusted, where gym sessions go, and how the user is told.

    python3 -m unittest discover -s tests

Standard library only. No network, no Calendar, no Reminders: files go to a temporary folder and every outside
call is a stub.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

os.environ["PM_NO_NOTIFY"] = "1"   # a test must never notify the real user

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "dashboard"))

import add_gym  # noqa: E402
import notify  # noqa: E402
import pm_env  # noqa: E402
import server  # noqa: E402


class DeadlineDates(unittest.TestCase):
    """A tracker row whose date came from an announcement is checked before it is believed."""
    # The expected times are local times in a +01:00 zone: pin it, so the test does not depend on config.env.
    ZONE = ZoneInfo("Europe/Berlin")
    NOW = datetime(2026, 11, 9, 23, 0, tzinfo=ZONE)

    def setUp(self):
        p = mock.patch.object(server, "TZ", self.ZONE)
        p.start()
        self.addCleanup(p.stop)
    QUIZ = {"course": "CALCULUS", "source": "exam", "title": "Quiz", "done": False, "status": "open",
            "due": "2026-11-09T09:00+01:00", "ends": "2026-11-09T10:20+01:00",
            "timetable_due": "2026-11-10T09:00+01:00", "timetable_ends": "2026-11-10T10:20+01:00",
            "date_source": "announcement",
            "date_from": {"title": "Quiz 2 and Problem Set 4", "created": "2026-11-09T10:15:39.504Z"}}

    def test_a_move_to_before_the_announcement_leaves_the_row_without_a_date(self):
        # Seen 2026-11-09: the post was written at 11:15, the quiz "moved" to 09:00 that morning, and the row
        # vanished from every list as already over. Changed 2026-11-10: the timetable date is not right either, so
        # the row stays (sortable by it) but carries `unclear` instead of passing as a deadline; tests/test_upcoming.py
        # pins what the pages and the phone do with it.
        [row] = server.open_deadlines([self.QUIZ], self.NOW)
        self.assertEqual(row["unclear"]["timetable"][:16], "2026-11-10T09:00")
        self.assertIn("date unclear", row["flag"])
        self.assertIn("Quiz 2 and Problem Set 4", row["flag"])

    def test_a_plausible_move_is_kept_and_says_where_it_came_from(self):
        moved = {**self.QUIZ, "due": "2026-11-16T12:00+01:00", "ends": "2026-11-16T13:20+01:00"}
        [row] = server.open_deadlines([moved], self.NOW)
        self.assertEqual(row["due"][:16], "2026-11-16T12:00")
        self.assertTrue(row["flag"].startswith("moved by announcement"))
        self.assertIn("was Tue 10 Nov 09:00", row["flag"])

    def test_rows_without_an_announcement_date_have_no_flag(self):
        plain = {k: v for k, v in self.QUIZ.items() if not k.startswith(("timetable", "date_"))}
        plain["due"], plain["ends"] = "2026-11-12T10:00+01:00", "2026-11-12T11:20+01:00"
        [row] = server.open_deadlines([plain], self.NOW)
        self.assertIsNone(row["flag"])

    def test_submitted_and_finished_work_is_not_open(self):
        rows = [{"course": "C", "source": "blackboard", "title": "Essay", "done": False, "status": "submitted",
                 "due": "2026-11-10T22:59:00.000Z"},
                {"course": "C", "source": "blackboard", "title": "Old", "done": True, "status": "graded",
                 "due": "2026-11-11T22:59:00.000Z"},
                {"course": "C", "source": "blackboard", "title": "Reflection", "done": False, "status": "open",
                 "due": "2026-11-10T22:59:00.000Z"}]
        self.assertEqual([d["title"] for d in server.open_deadlines(rows, self.NOW)], ["Reflection"])


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 9)   # a Monday


def lesson(day, start, end, title="MATHS (Ses. 1) Live in-person"):
    return {"title": title, "start": f"{day}T{start}+01:00", "end": f"{day}T{end}+01:00", "all_day": False,
            "calendar": "School", "notes": ""}


class GymPlan(unittest.TestCase):
    ITEM = {"id": "gym-weekly", "recurrence": {"days": ["Mon", "Tue", "Thu", "Fri"]},
            "details": {"split": {"Mon": "Day 1 chest", "Tue": "Day 2 back", "Thu": "Day 3 arms", "Fri": "Day 4 legs"}}}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        (self.root / "items.json").write_text(json.dumps({"items": [self.ITEM]}))
        self.patches = [mock.patch.object(add_gym, "ROOT", self.root), mock.patch.object(add_gym, "date", FixedDate),
                        mock.patch.object(add_gym, "FEED", "School"), mock.patch.object(add_gym, "VISIBLE", ""),
                        mock.patch.object(add_gym, "CLASS_TITLE", re.compile(".")), mock.patch.object(add_gym, "CLASS_SKIP", None),
                        mock.patch.object(add_gym, "CALENDAR", "Private"), mock.patch.object(add_gym, "WEEKS", 0),
                        mock.patch.object(add_gym, "OFF_CAMPUS", re.compile(pm_env.DEFAULTS["PM_OFF_CAMPUS"], re.I)),
                        mock.patch.object(pm_env, "CLASS_CALENDARS", ["School"])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def calendar(self, extra=()):
        # No class on Monday; classes Tuesday to Friday.
        events = [lesson("2026-11-10", "12:00", "13:20"), lesson("2026-11-11", "11:00", "12:20"),
                  lesson("2026-11-12", "13:00", "14:20"), lesson("2026-11-13", "11:30", "12:50"), *extra]
        (self.root / "data/calendar.json").write_text(json.dumps({
            "generated_at": "2026-11-09T08:00:00+01:00", "window": {"from": "2026-11-09T00:00+01:00"}, "events": events}))

    def days(self):
        events, notes, _ = add_gym.plan()
        return [(f'{e["start"]:%a %H:%M}', e["day"]) for e in events], notes

    def test_monday_off_gives_tue_wed_fri(self):
        self.calendar()
        got, _ = self.days()
        self.assertEqual(got, [("Tue 13:30", 1), ("Wed 12:30", 2), ("Fri 13:00", 4)])

    def test_an_online_day_has_no_gym_and_the_session_moves_on(self):
        # A strike: Wednesday's classes can be followed from home. One all-day event says so, in any calendar.
        self.calendar([{"title": "Online day (strike)", "start": "2026-11-11", "end": "2026-11-11", "all_day": True,
                        "calendar": "Private", "notes": ""}])
        got, notes = self.days()
        self.assertEqual(got, [("Tue 13:30", 1), ("Thu 14:30", 2), ("Fri 13:00", 4)])
        self.assertTrue(any("Online day (strike)" in n for n in notes))
        self.assertNotIn("2026-11-11", add_gym.class_ends()[0])   # so "after class" has nothing to book either

    def test_other_all_day_events_change_nothing(self):
        self.calendar([{"title": "St. Martin", "start": "2026-11-11", "end": "2026-11-11", "all_day": True,
                        "calendar": "Holidays", "notes": ""}])
        self.assertEqual(self.days()[0], [("Tue 13:30", 1), ("Wed 12:30", 2), ("Fri 13:00", 4)])

    def test_drift_names_what_is_missing_and_what_is_left_over(self):
        self.calendar()
        events, _, _ = add_gym.plan()
        mine = lambda start, title: {"start": start + "+01:00", "title": title, "calendar": "Private",  # noqa: E731
                                     "notes": add_gym.MARKER}
        cal = [mine("2026-11-10T13:30", "Gym · Day 1 chest"), mine("2026-11-11T14:00", "Gym · Day 2 back"),
               mine("2026-11-13T13:00", "Gym · Day 4 legs"),
               {"start": "2026-11-12T18:00+01:00", "title": "Gym", "calendar": "Private", "notes": ""}]   # not ours
        missing, extra = add_gym.drift(events, cal, FixedDate.today())
        self.assertEqual(missing, [("2026-11-11T12:30", "Gym · Day 2 back")])
        self.assertEqual(extra, [("2026-11-11T14:00", "Gym · Day 2 back")])
        cal[1] = mine("2026-11-11T12:30", "Gym · Day 2 back")
        self.assertEqual(add_gym.drift(events, cal, FixedDate.today()), ([], []))


class Notify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.patches = [mock.patch.object(notify, "SENT", t / "sent.json"), mock.patch.object(notify, "LOG", t / "log.jsonl"),
                        mock.patch.object(notify, "phone_list", return_value="Alerts"),
                        mock.patch.object(pm_env, "DEMO", False), mock.patch.dict(os.environ, {"PM_NO_NOTIFY": ""})]
        for p in self.patches:
            p.start()
        self.mac, self.phone = [], []

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def send(self, text, **kw):
        return notify.send(text, _mac=lambda t, title: self.mac.append(t),
                           _phone=lambda t, notes, when: self.phone.append((t, when)), **kw)

    def test_phone_only_when_asked(self):
        self.send("on the Mac")
        self.send("on both", phone=True)
        self.assertEqual(self.mac, ["on the Mac", "on both"])
        self.assertEqual([t for t, _ in self.phone], ["on both"])

    def test_same_key_is_sent_once(self):
        now = datetime(2026, 11, 10, 12, 0)
        self.assertEqual(self.send("due today", phone=True, key="p:1", now=now)["phone"], "sent")
        self.assertEqual(self.send("due today", phone=True, key="p:1", now=now + timedelta(hours=1))["phone"], "duplicate")
        self.assertEqual(len(self.phone), 1)
        self.assertEqual(len(self.mac), 1)

    def test_a_failed_phone_alert_is_tried_again_and_never_raises(self):
        def broken(*a):
            raise RuntimeError("Reminders access denied")
        out = notify.send("x", phone=True, key="k", _mac=lambda *a: None, _phone=broken)
        self.assertTrue(out["phone"].startswith("error"))
        self.assertEqual(self.send("x", phone=True, key="k")["phone"], "sent")

    def test_quiet_hours_ring_in_the_morning(self):
        q = "23:00-07:30"
        self.assertEqual(notify.alarm_time(datetime(2026, 11, 10, 3, 0), q), datetime(2026, 11, 10, 7, 30))
        self.assertEqual(notify.alarm_time(datetime(2026, 11, 10, 23, 30), q), datetime(2026, 11, 11, 7, 30))
        self.assertEqual(notify.alarm_time(datetime(2026, 11, 10, 12, 0), q), datetime(2026, 11, 10, 12, 2))

    def test_the_test_suite_and_demo_mode_never_notify(self):
        with mock.patch.dict(os.environ, {"PM_NO_NOTIFY": "1"}):
            self.assertEqual(self.send("x", phone=True)["phone"], "demo")
        self.assertEqual((self.mac, self.phone), ([], []))


class HourlyAlerts(unittest.TestCase):
    NOW = datetime(2026, 11, 9, 12, 0)

    def run_alerts(self, o, prev=()):
        import state_refresh
        sent = []
        errors = state_refresh.alerts({"proposals": [], "health": [], "bb": {"deadlines": []}, **o}, self.NOW, prev,
                                      send=lambda text, phone=False, key=None: sent.append((key, text)))
        return sent, errors

    def test_a_suggestion_due_soon_reaches_the_phone(self):
        # 2026-11-09: "Submit Problem Set 4", due that day, waited 12 hours on a page only seen at the Mac.
        props = [{"id": "a1", "status": "new", "item": {"type": "task", "title": "Submit Problem Set 4", "start": "2026-11-09"}},
                 {"id": "a2", "status": "new", "item": {"type": "task", "title": "Renew pass", "start": "2026-11-24"}},
                 {"id": "a3", "status": "dismissed", "item": {"type": "task", "title": "Old", "start": "2026-11-09"}},
                 {"id": "a4", "status": "new", "item": {"type": "event", "title": "Labs fair", "start": "2026-11-10T12:30"}},
                 {"id": "a5", "status": "new", "item": {"type": "task", "title": "Past", "start": "2026-11-07"}}]
        sent, _ = self.run_alerts({"proposals": props})
        self.assertEqual([k for k, _ in sent], ["proposal:a1", "proposal:a4"])
        self.assertTrue(sent[0][1].startswith("Due today: Submit Problem Set 4"))
        self.assertTrue(sent[1][1].startswith("On tomorrow: Labs fair"))

    def test_an_unclear_deadline_date_reaches_the_phone(self):
        # Changed 2026-11-10: unclear rows come in `bb.unclear` (not in the dated list) and the text says what is known.
        d = {"course": "CALCULUS", "title": "Quiz", "due": "2026-11-10T09:00+01:00",
             "unclear": {"timetable": "2026-11-10T09:00+01:00", "announcement": "Q", "posted": "2026-11-09T10:15:00Z"}}
        ok = {"course": "CALCULUS", "title": "Exam", "due": "2026-12-11T11:30+01:00", "flag": 'moved by announcement "X"'}
        sent, _ = self.run_alerts({"bb": {"deadlines": [ok], "unclear": [d]}})
        self.assertEqual([k for k, _ in sent], ["deadline-flag:CALCULUS:Quiz:2026-11-10"])
        self.assertIn("the date is unclear (timetable says Tue 10 Nov 09:00", sent[0][1])

    def test_undated_tasks_are_called_out_on_sunday(self):
        import state_refresh
        items = [{"type": "task", "status": "open", "title": "Get the residence card", "created": "2026-10-25"},
                 {"type": "task", "status": "open", "title": "Enroll in a lab", "created": "2026-10-28", "due": "2026-11-20"},
                 {"type": "task", "status": "open", "title": "New thing", "created": "2026-11-08"},
                 {"type": "task", "status": "done", "title": "Finished", "created": "2026-10-01"}]
        self.assertEqual(state_refresh.undated_days(items[0], self.NOW.date()), 15)
        self.assertIsNone(state_refresh.undated_days(items[1], self.NOW.date()))
        sent, _ = self.run_alerts({"items": items})                      # a Monday: nothing
        self.assertEqual(sent, [])
        sunday = datetime(2026, 11, 15, 18, 0)
        got = []
        state_refresh.alerts({"proposals": [], "health": [], "bb": {"deadlines": []}, "items": items}, sunday,
                             send=lambda text, phone=False, key=None: got.append(text))
        self.assertEqual(len(got), 1)
        self.assertIn("Get the residence card", got[0])
        self.assertNotIn("New thing", got[0])

    def test_a_health_error_is_sent_only_when_it_lasts(self):
        health = [{"level": "error", "name": "Calendar data", "detail": "stale"}, {"level": "warn", "name": "Mail check", "detail": "paused"}]
        sent, errors = self.run_alerts({"health": health})
        self.assertEqual((sent, errors), ([], ["Calendar data"]))
        sent, _ = self.run_alerts({"health": health}, prev=errors)
        self.assertEqual([k for k, _ in sent], ["health:Calendar data:2026-11-09"])


class InboxCommands(unittest.TestCase):
    """A line a plugin owns is run in code: ticked first, then run once, and never shown to a model."""

    def setUp(self):
        import inbox_process
        self.ip = inbox_process

        class Plugin:
            INBOX_LINE = re.compile(r"^do it\b", re.I)
        self.plugin, self.order = Plugin, []
        self.items = [{"kind": "reminder", "key": "r1", "text": "Do it tomorrow", "note": "", "created": "2026-11-09T22:00:00+01:00"},
                      {"kind": "reminder", "key": "r2", "text": "Dinner with Sam on Friday", "note": "", "created": ""},
                      {"kind": "file", "key": "pass.png", "text": "pass.png", "note": ""}]

    def run_cmds(self, fn, tick=None):
        return self.ip.plugin_commands(list(self.items), hooks=[(self.plugin, fn)],
                                       tick=tick or (lambda key: self.order.append(("tick", key))))

    def test_the_command_runs_once_after_its_reminder_is_ticked(self):
        def fn(text, created):
            self.order.append(("run", text, created))
            return "Booked: slot"
        rest, results = self.run_cmds(fn)
        self.assertEqual([i["key"] for i in rest], ["r2", "pass.png"])
        self.assertEqual(self.order, [("tick", "r1"), ("run", "Do it tomorrow", datetime(2026, 11, 9, 22, 0))])
        self.assertEqual(results[0]["summary"], "Booked: slot")
        self.assertIsNone(results[0]["needs_user"])

    def test_nothing_runs_when_the_reminder_cannot_be_ticked(self):
        ran = []

        def tick(key):
            raise RuntimeError("Reminders did not answer")
        rest, results = self.run_cmds(lambda t, c: ran.append(t), tick)
        self.assertEqual(ran, [])
        self.assertIn("not run", results[0]["summary"])

    def test_a_refusal_or_a_crash_is_reported_to_the_user(self):
        _, results = self.run_cmds(lambda t, c: "Not booked: the slot had already started")
        self.assertTrue(results[0]["needs_user"])

        def boom(t, c):
            raise OSError("browser gone")
        _, results = self.run_cmds(boom)
        self.assertEqual(results[0]["summary"], "Not done: browser gone")
        self.assertTrue(results[0]["needs_user"])


class GymProposalsOnThePhone(unittest.TestCase):
    """The phone shows the review and the open weight proposals; a tap there is applied on the Mac."""
    PROPS = {"proposals": [
        {"id": "day-1-curls-16", "day": "Day 1", "exercise": "Curls", "from": 14, "to": 16, "reason": "2×15+", "status": "pending"},
        {"id": "day-2-rows-70", "day": "Day 2", "exercise": "Rows", "from": 67.5, "to": 70, "reason": "3×8", "status": "pending"},
        {"id": "day-2-old", "day": "Day 2", "exercise": "Rows", "from": 60, "to": 62.5, "reason": "", "status": "dismissed"}]}
    PLAN = {"days": {"Day 1": {"exercises": [{"name": "Curls", "weight": 18.0}]},      # raised by hand since the proposal
                     "Day 2": {"exercises": [{"name": "Rows", "weight": 67.5}]}}}

    def setUp(self):
        import gym_pull
        import gym_review
        self.pull, self.review = gym_pull, gym_review
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        (t / "data").mkdir()
        (t / "data/gym_proposals.json").write_text(json.dumps(self.PROPS))
        (t / "data/gym_review.json").write_text(json.dumps({"session": {"date": "2026-11-05", "day": "Day 2", "text": "18/19 sets"},
                                                            "weekly": {"week_of": "2026-11-02", "text": "2 sessions"}}))
        self.patches = [mock.patch.object(gym_pull, "ROOT", t), mock.patch.object(gym_review, "PROPOSALS", t / "data/gym_proposals.json")]
        for p in self.patches:
            p.start()
        self.t = t

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def status(self):
        return {p["id"]: p["status"] for p in json.loads((self.t / "data/gym_proposals.json").read_text())["proposals"]}

    def test_notes_carry_the_reviews_and_only_pending_proposals(self):
        n = self.pull.notes()
        self.assertEqual([p["id"] for p in n["proposals"]], ["day-1-curls-16", "day-2-rows-70"])
        self.assertNotIn("status", n["proposals"][0])
        self.assertEqual((n["session"]["text"], n["week"]["text"]), ("18/19 sets", "2 sessions"))

    def test_a_proposal_the_plan_overtook_is_closed_not_offered(self):
        self.assertEqual(self.review.supersede_stale(self.PLAN), ["day-1-curls-16"])
        self.assertEqual(self.status(), {"day-1-curls-16": "superseded", "day-2-rows-70": "pending", "day-2-old": "dismissed"})
        self.assertEqual([p["id"] for p in self.pull.notes()["proposals"]], ["day-2-rows-70"])
        self.assertEqual(self.review.supersede_stale(self.PLAN), [])

    def test_a_tap_runs_apply_or_dismiss_and_is_logged(self):
        calls = []

        class Review:
            apply = staticmethod(lambda pid: calls.append(("apply", pid)))
            dismiss = staticmethod(lambda pid: calls.append(("dismiss", pid)))
        self.assertEqual(self.pull.decide({"kind": "decision", "proposal": "day-2-rows-70", "accept": True}, Review), "applied")
        self.assertEqual(self.pull.decide({"kind": "decision", "proposal": "day-1-curls-16", "accept": False}, Review), "dismissed")
        self.assertEqual(self.pull.decide({"kind": "decision", "proposal": "day-1-curls-16", "accept": "yes"}, Review), "dismissed")  # only true accepts
        self.assertEqual(calls, [("apply", "day-2-rows-70"), ("dismiss", "day-1-curls-16"), ("dismiss", "day-1-curls-16")])
        log = [json.loads(l) for l in (self.t / "data/gym_decisions.jsonl").read_text().splitlines()]
        self.assertEqual([(r["proposal"], r["result"]) for r in log][:2], [("day-2-rows-70", "applied"), ("day-1-curls-16", "dismissed")])

    def test_a_refused_accept_is_reported_and_never_raises(self):
        told = []

        class Review:
            @staticmethod
            def apply(pid):
                raise ValueError("Gym.md says 18 kg for Curls, not 14 kg")
        out = self.pull.decide({"proposal": "day-1-curls-16", "accept": True}, Review, lambda text, phone=False: told.append(text))
        self.assertTrue(out.startswith("refused"))
        self.assertEqual(len(told), 1)


if __name__ == "__main__":
    unittest.main()
