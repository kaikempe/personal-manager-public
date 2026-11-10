"""Rules that must not silently break: mail triage, the yes rule, the phone endpoint, health.

    python3 -m unittest discover -s tests

Standard library only. No network, no Chrome, no model: every outside call is replaced by a stub, and files the
code writes are redirected to a temporary folder.
"""
import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import os
os.environ["PM_NO_NOTIFY"] = "1"   # a test must never notify the real user

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "dashboard"))

import confirm  # noqa: E402
import health  # noqa: E402
import mail_suggest  # noqa: E402
import phone_server  # noqa: E402


class YesRule(unittest.TestCase):
    def test_plain_yes(self):
        for t in ["yes", "Yes please", "ok book it", "book it", "sí", "vale", "yes!", "go ahead", "ja"]:
            self.assertTrue(confirm.is_yes(t), t)

    def test_new_request_or_hedge_is_not_yes(self):
        for t in ["Book the gym at 4", "yes but at 4", "book gym tomorrow at 3", "no", "wait", "", "yes " * 6]:
            self.assertFalse(confirm.is_yes(t), t)

    def test_no(self):
        self.assertTrue(confirm.is_no("no"))
        self.assertTrue(confirm.is_no("wait, not that"))
        self.assertFalse(confirm.is_no("yes"))


class MailTriage(unittest.TestCase):
    rows = [{"acct": "iCloud", "sender": "Lufthansa Booking <booking@information.lufthansa.com>",
             "subject": "Thank you for booking with us | From Berlin to Munich on 17 December 2026"},
            {"acct": "Gmail", "sender": "Quora Digest <digest@quora.com>", "subject": "Top stories for you"},
            {"acct": "iCloud", "sender": "Iberia <info@iberia.com>", "subject": "Your trip to Munich"}]

    def test_booking_mails_are_picked_even_when_the_model_skips_them(self):
        # The 2026-11-07 miss: the model returned no picks for a Lufthansa booking.
        with mock.patch.object(mail_suggest, "ask_claude", return_value={"pick": []}):
            picked = mail_suggest.triage(self.rows)
        self.assertEqual([r["sender"][:9] for r in picked], ["Lufthansa", "Iberia <i"])

    def test_model_picks_are_kept_and_not_duplicated(self):
        with mock.patch.object(mail_suggest, "ask_claude", return_value={"pick": [0, 1, 99, "x"]}):
            picked = mail_suggest.triage(self.rows)
        self.assertEqual(len(picked), 3)

    def test_newsletters_are_not_forced(self):
        self.assertIsNone(mail_suggest.MUST_PICK.search(self.rows[1]["sender"] + " " + self.rows[1]["subject"]))


class PhoneEndpoint(unittest.TestCase):
    BOOK = {"kind": "book_slot", "date": "2026-11-10", "start": "15:00", "summary": "Book slot Tue 10 Nov 15:00"}
    PLUGIN = {"book_slot": {"label": "Book slot", "voice": True, "slow": True,
                            "slow_reply": lambda a: f'Booking {a["date"]} {a["start"]} now.'}}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.patches = [mock.patch.object(phone_server, "SESSION", t / "s.json"),
                        mock.patch.object(phone_server, "LOG", t / "log.jsonl"),
                        mock.patch.object(phone_server, "TOKEN_FILE", t / "token"),
                        mock.patch.object(phone_server, "notify"),
                        mock.patch.object(phone_server, "plugin_actions", return_value=self.PLUGIN)]
        for p in self.patches:
            p.start()
        (t / "token").write_text("secret-token\n")
        self.acted = []

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()
        phone_server._bad.clear()
        phone_server._locked_until = 0.0

    def say(self, text, reply="Sure."):
        return phone_server.answer(text, chat=lambda msgs: reply, act=lambda a: self.acted.append(a) or "Booked.",
                                   save=lambda r, t: [], run_bg=lambda f: f())

    def test_yes_runs_the_pending_action_once(self):
        out = self.say("book the gym tuesday at 3", f"15:00 is free.\nACTION {json.dumps(self.BOOK)}")
        self.assertIn("Say yes to: Book slot", out)
        self.assertNotIn("ACTION", out)
        self.assertIn("Booking 2026-11-10 15:00 now", self.say("yes"))   # answers at once, books in the background
        self.assertEqual(self.acted, [self.BOOK])
        nxt = self.say("yes")                # a second yes has nothing pending: it goes to the chat
        self.assertEqual(len(self.acted), 1)
        self.assertTrue(nxt.startswith("Earlier: Booked."))              # the background result is told once
        self.assertFalse(self.say("thanks").startswith("Earlier"))

    def test_other_actions_run_at_once(self):
        task = {"kind": "add_task", "title": "Call bank", "due": "2026-11-09", "summary": "Add task Call bank"}
        self.say("remind me", f"ACTION {json.dumps(task)}")
        self.assertEqual(self.say("yes"), "Booked.")
        self.assertEqual(self.acted, [task])

    def test_yes_without_question_does_nothing(self):
        self.say("yes")
        self.assertEqual(self.acted, [])

    def test_no_drops_it(self):
        self.say("book it", f"ACTION {json.dumps(self.BOOK)}")
        self.assertIn("won't", self.say("no"))
        self.say("yes")
        self.assertEqual(self.acted, [])

    def test_yes_expires(self):
        self.say("book it", f"ACTION {json.dumps(self.BOOK)}")
        s = json.loads(phone_server.SESSION.read_text())
        s["pending_at"] -= phone_server.PENDING_S + 1
        phone_server.SESSION.write_text(json.dumps(s))
        self.say("yes")
        self.assertEqual(self.acted, [])

    def test_a_new_request_replaces_the_pending_one(self):
        self.say("book it", f"ACTION {json.dumps(self.BOOK)}")
        self.say("actually what is due this week")
        self.say("yes")
        self.assertEqual(self.acted, [])

    def test_delete_is_not_offered_by_voice(self):
        out = self.say("delete my dinner", 'ACTION {"kind":"delete_event","title":"Dinner","start":"2026-11-10T20:00"}')
        self.assertNotIn("Say yes", out)
        self.say("yes")
        self.assertEqual(self.acted, [])

    def test_token_and_lockout(self):
        self.assertTrue(phone_server.token_ok("Bearer secret-token"))
        self.assertFalse(phone_server.token_ok("Bearer nope"))
        self.assertFalse(phone_server.token_ok("secret-token"))      # no Bearer prefix
        for _ in range(5):
            phone_server.token_ok("Bearer nope")
        self.assertFalse(phone_server.token_ok("Bearer secret-token"))   # locked even with the right token


class Health(unittest.TestCase):
    def test_rows_are_well_formed(self):
        rows = health.checks()
        self.assertTrue(rows)
        for r in rows:
            self.assertIn(r["level"], ("ok", "warn", "error"))
            self.assertTrue(r["name"] and r["detail"])

    def test_stale_calendar_is_an_error(self):
        with tempfile.TemporaryDirectory() as t:
            old = (datetime.now().astimezone() - timedelta(hours=3)).isoformat()
            Path(t, "export_status.json").write_text('{"ok": true, "events": 5}')
            Path(t, "calendar.json").write_text(json.dumps({"generated_at": old}))
            with mock.patch.object(health, "DATA", Path(t)):
                rows = {n: (lv, d) for lv, n, d in health.data_checks(datetime.now().astimezone())}
        self.assertEqual(rows["Calendar data"][0], "error")

    def test_failed_mail_run_is_an_error(self):
        with tempfile.TemporaryDirectory() as t:
            Path(t, "mail_status.json").write_text('{"ok": false, "error": "Mail did not answer"}')
            with mock.patch.object(health, "DATA", Path(t)):
                rows = {n: (lv, d) for lv, n, d in health.data_checks(datetime.now().astimezone())}
        self.assertEqual(rows["Mail check"], ("error", "last run failed: Mail did not answer"))

    def test_a_usage_limit_pauses_mail_and_is_only_a_warning(self):
        # The model's limit is not a fault: unseen mails are retried every hour. As an error it would also be
        # pushed to the phone every day the user works a lot.
        with tempfile.TemporaryDirectory() as t:
            Path(t, "mail_status.json").write_text(json.dumps({"ok": False, "error": "You've hit your 5-hour limit · resets 9:40am"}))
            with mock.patch.object(health, "DATA", Path(t)):
                rows = {n: (lv, d) for lv, n, d in health.data_checks(datetime.now().astimezone())}
        self.assertEqual(rows["Mail check"][0], "warn")

    def test_job_not_loaded_is_an_error(self):
        with tempfile.TemporaryDirectory() as t:
            Path(t, f"{health.P}.dashboard.plist").write_text("<plist/>")
            with mock.patch.object(health, "AGENTS", Path(t)):
                rows = {n: lv for lv, n, d in health.job_checks({})}
        self.assertEqual(rows["Dashboard server"], "error")

    def test_optional_job_not_installed_is_silent(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(health, "AGENTS", Path(t)), \
                mock.patch.object(health, "REQUIRED", {f"{health.P}.calendar-export"}):
            rows = {n: lv for lv, n, d in health.job_checks({})}
        self.assertEqual(rows, {"Calendar export (every 15 min)": "error"})


if __name__ == "__main__":
    unittest.main()
