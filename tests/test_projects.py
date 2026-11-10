"""Rules behind the Projects page: titles, relative activity, order, groups, the questions for the user and the live
Studies strip.

    python3 -m unittest discover -s tests

Standard library only. No network, no git: registry rows are built by hand with the fields registry() and
git_activity() would give them.
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

os.environ["PM_NO_NOTIFY"] = "1"   # a test must never notify the real user

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "dashboard"))

import server  # noqa: E402

ZONE = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=ZONE)
TODAY = NOW.date()


def row(name, **kw):
    """A registry() row: frontmatter plus the git facts (no git by default)."""
    r = {"name": name, "file": name, "kind": "project", "status": "active", "confirmed": "true", "path": "", "repo": "",
         "summary": "", "next": "", "drafted": "", "body": "", "last_active": None, "last_msg": "", "backup_only": False,
         "has_git": False, "uncommitted": 0, "unpushed": 0, "unmerged_branch": ""}
    r.update(kw)
    return r


def days_ago(n):
    return (TODAY - timedelta(days=n)).isoformat()


def card(name, **kw):
    return server.project_card(row(name, **kw), TODAY)


class Titles(unittest.TestCase):
    def test_a_slug_becomes_words_with_acronyms_in_capitals(self):
        self.assertEqual(server.project_title("ai-implementation-sme"), "AI Implementation SME")
        self.assertEqual(server.project_title("performance-hud"), "Performance HUD")

    def test_configured_acronyms_and_small_words(self):
        self.assertEqual(server.project_title("bb-tracker", ["BB"]), "BB Tracker")
        self.assertEqual(server.project_title("bb-tracker"), "Bb Tracker")
        self.assertEqual(server.project_title("history-of-ideas"), "History of Ideas")
        self.assertEqual(server.project_title("the_side_project"), "The Side Project")

    def test_a_hand_written_name_is_kept(self):
        self.assertEqual(server.project_title("Portfolio site v2"), "Portfolio site v2")
        self.assertEqual(server.project_title("iPhoneApp"), "iPhoneApp")


class Activity(unittest.TestCase):
    def test_relative_time(self):
        cases = {None: "", 0: "today", 1: "yesterday", 5: "5 days ago", 13: "13 days ago", 20: "3 weeks ago",
                 45: "6 weeks ago", 90: "3 months ago", 400: "1 year ago", 800: "2 years ago"}
        for days, text in cases.items():
            self.assertEqual(server.ago_text(days), text, days)

    def test_a_card_carries_idle_days_and_the_relative_time(self):
        c = card("site", last_active=days_ago(3), has_git=True)
        self.assertEqual((c["idle_days"], c["ago"], c["stale"]), (3, "3 days ago", False))
        self.assertTrue(card("old", last_active=days_ago(31), has_git=True)["stale"])
        self.assertEqual(card("nogit")["ago"], "")

    def test_none_is_not_a_next_step(self):
        self.assertEqual(card("a", next="none.")["next_step"], "")
        self.assertEqual(card("b", next=" Ship the page ")["next_step"], "Ship the page")


class GitHints(unittest.TestCase):
    def test_housekeeping_is_a_hint_on_the_card(self):
        c = card("a", has_git=True, repo="example/a", unpushed=1, uncommitted=3, unmerged_branch="feature/x")
        self.assertEqual(c["hints"], ["1 commit not pushed", "latest work on branch feature/x", "3 uncommitted changes"])
        self.assertEqual(c["questions"], [], "git housekeeping is never a question")

    def test_missing_backup(self):
        self.assertEqual(card("a", has_git=True)["hints"], ["no remote backup"])
        self.assertEqual(card("b", path="b")["hints"], ["folder not in git"])

    def test_archived_entries_get_no_hints(self):
        self.assertEqual(card("a", status="archived", has_git=True, unpushed=4)["hints"], [])


class Questions(unittest.TestCase):
    def reasons(self, **kw):
        return card("x", **kw)["reasons"]

    def test_active_but_idle_for_more_than_30_days(self):
        self.assertEqual(self.reasons(has_git=True, last_active=days_ago(32)), ["stale"])
        self.assertIn("32 days ago", card("x", has_git=True, last_active=days_ago(32))["questions"][0])
        self.assertEqual(self.reasons(has_git=True, last_active=days_ago(30)), [])

    def test_not_this_week_is_idle_on_purpose(self):
        self.assertEqual(self.reasons(has_git=True, last_active=days_ago(60), this_week="pause"), [])

    def test_backup_commits_do_not_count_as_idle_work(self):
        self.assertEqual(self.reasons(has_git=True, last_active=days_ago(60), backup_only=True), [])

    def test_on_hold_revisit(self):
        self.assertEqual(self.reasons(status="on-hold", revisit="2026-11-01"), ["revisit_due"])
        self.assertEqual(self.reasons(status="on-hold", revisit="2026-11-10"), ["revisit_due"])
        self.assertEqual(self.reasons(status="on-hold", revisit="2026-12-01"), [])
        self.assertEqual(self.reasons(status="on-hold", revisit="after the exams (2026-10-01)"), [],
                         "a trigger in words is not a date")
        self.assertEqual(self.reasons(status="on-hold", revisit=""), ["no_revisit"])

    def test_a_status_the_user_has_not_confirmed(self):
        self.assertEqual(self.reasons(confirmed="false"), ["unconfirmed"])
        self.assertEqual(self.reasons(drafted="summary,status"), ["unconfirmed"])
        self.assertEqual(self.reasons(drafted="summary,next"), [], "drafted text is a card hint, not a question")
        self.assertEqual(self.reasons(status="unknown"), ["unknown"])
        self.assertEqual(card("x", status="someday")["status"], "unknown")

    def test_completed_needs_an_outcome(self):
        self.assertEqual(self.reasons(status="completed", outcome=""), ["no_outcome"])
        self.assertEqual(self.reasons(status="completed", outcome="Shipped v1 in 2026"), [])

    def test_archived_with_a_recent_commit(self):
        self.assertEqual(self.reasons(status="archived", has_git=True, last_active=days_ago(2)), ["recent_work"])
        self.assertEqual(self.reasons(status="archived", has_git=True, last_active=days_ago(40)), [])


class Page(unittest.TestCase):
    def page(self, rows, deadlines=()):
        return server.projects_page(rows, list(deadlines), NOW)

    def test_order_focus_then_graded_and_paid_then_recent_activity_then_not_this_week(self):
        rows = [row("idle", has_git=True, last_active=days_ago(40)),
                row("nodata"),
                row("recent", has_git=True, last_active=days_ago(1)),
                row("older", has_git=True, last_active=days_ago(9)),
                row("paid-work", purpose="paid"),
                row("later", this_week="pause", has_git=True, last_active=days_ago(0)),
                row("focus", this_week="focus", has_git=True, last_active=days_ago(20)),
                row("unsorted", status="unknown")]
        self.assertEqual([c["file"] for c in self.page(rows)["working"]],
                         ["focus", "paid-work", "recent", "older", "nodata", "idle", "later", "unsorted"])

    def test_groups(self):
        rows = [row("a"), row("b", status="on-hold", revisit="later"), row("c", status="idea"),
                row("d", status="completed", outcome="Shipped"), row("e", status="archived"),
                row("f", kind="course"), row("g", kind="venture")]
        p = self.page(rows)
        self.assertEqual([c["file"] for c in p["working"]], ["a", "g"])
        self.assertEqual([c["file"] for c in p["on_hold"]], ["b"])
        self.assertEqual([[c["file"] for c in p[k]] for k in ("ideas", "completed", "archived", "courses")],
                         [["c"], ["d"], ["e"], ["f"]])
        self.assertEqual(p["counts"], {"working": 2, "on_hold": 1, "decisions": 0})

    def test_decisions_list_only_real_questions_most_basic_first(self):
        rows = [row("idle", has_git=True, last_active=days_ago(45), unpushed=2),
                row("busy", has_git=True, last_active=days_ago(0), unpushed=3, unmerged_branch="x"),
                row("drafted", confirmed="false"),
                row("held", status="on-hold", revisit="2026-11-02")]
        d = self.page(rows)["decisions"]
        self.assertEqual([x["file"] for x in d], ["drafted", "held", "idle"])
        self.assertTrue(all(q.endswith("?") for x in d for q in x["questions"]))

    def test_unchanged_rows_are_not_modified(self):
        r = row("a")
        self.page([r])
        self.assertNotIn("title", r)


class Studies(unittest.TestCase):
    def dl(self, course, title, due, **kw):
        return {"course": course, "title": title, "due": due, "kind": "exam", **kw}

    def test_one_line_per_course_with_its_next_item_soonest_first(self):
        rows = [self.dl("STATISTICS", "Problem set 5", "2026-11-20T23:59+01:00"),
                self.dl("STATISTICS", "Problem set 4", "2026-11-12T23:59+01:00"),
                self.dl("MARKETING", "Midterm", "2026-11-11T10:00+01:00")]
        s = server.studies(rows, NOW)
        self.assertEqual([(x["course"], x["title"], x["more"]) for x in s],
                         [("MARKETING", "Midterm", 0), ("STATISTICS", "Problem set 4", 1)])

    def test_a_past_item_is_never_shown_as_coming_up(self):
        rows = [self.dl("STATISTICS", "Midterm", "2026-10-27T09:00+01:00"),
                self.dl("STATISTICS", "Quiz", "2026-11-10T09:00+01:00", ends="2026-11-10T10:00+01:00")]
        self.assertEqual(server.studies(rows, NOW), [])

    def test_an_exam_still_running_is_shown(self):
        rows = [self.dl("STATISTICS", "Quiz", "2026-11-10T11:30+01:00", ends="2026-11-10T13:00+01:00")]
        self.assertEqual([x["title"] for x in server.studies(rows, NOW)], ["Quiz"])

    def test_an_unclear_date_is_left_out(self):
        rows = [self.dl("STATISTICS", "Quiz", "2026-11-12T09:00+01:00", unclear={"timetable": "x"})]
        self.assertEqual(server.studies(rows, NOW), [])

    def test_a_course_entry_is_matched_and_shows_its_live_next_item_not_its_text(self):
        rows = [row("statistics", kind="course", this_week="focus", summary="Midterm on 27 Oct")]
        p = server.projects_page(rows, [self.dl("STATISTICS 1", "Final exam", "2026-12-10T09:30+01:00")], NOW)
        self.assertEqual(p["studies"][0]["entry"], "statistics")
        self.assertTrue(p["studies"][0]["focus"])
        self.assertEqual(p["courses"][0]["live_next"]["title"], "Final exam")
        self.assertEqual(p["working"], [], "a course is not a project card")
        self.assertIsNone(server.course_entry_for("STATISTICS", [server.project_card(row("stat"), TODAY)]))


class Writes(unittest.TestCase):
    def test_the_outcome_of_a_completed_entry_can_be_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = Path(tmp) / "registry"
            reg.mkdir()
            (reg / "site.md").write_text("---\nname: site\nstatus: completed\noutcome: \n---\nBody\n")
            with mock.patch.object(server, "DATA", Path(tmp)):
                server.set_registry("site", {"outcome": "Shipped  v1,\n2026"})
            self.assertIn("outcome: Shipped v1, 2026\n", (reg / "site.md").read_text())


if __name__ == "__main__":
    unittest.main()
