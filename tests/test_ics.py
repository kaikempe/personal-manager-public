"""ICS calendar source: feeds from Google, Outlook or a school become the same records as Apple Calendar's.

    python3 -m unittest discover -s tests
"""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ics_source  # noqa: E402
import export_calendar  # noqa: E402

TZ = ZoneInfo("Europe/Berlin")
FEED = "\r\n".join([
    "BEGIN:VCALENDAR", "VERSION:2.0",
    # weekly Mon+Wed 09:00-10:30, 6 times, one Wednesday excluded, one Monday moved to 11:00
    "BEGIN:VEVENT", "UID:lecture-1", "SUMMARY:Statistics\\, lecture", "LOCATION:Room 2.1",
    "DTSTART;TZID=Europe/Berlin:20261102T090000", "DTEND;TZID=Europe/Berlin:20261102T103000",
    "RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=6", "EXDATE;TZID=Europe/Berlin:20261104T090000",
    "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-PT15M", "END:VALARM", "END:VEVENT",
    "BEGIN:VEVENT", "UID:lecture-1", "RECURRENCE-ID;TZID=Europe/Berlin:20261109T090000",
    "SUMMARY:Statistics\\, lecture (moved)", "DTSTART;TZID=Europe/Berlin:20261109T110000",
    "DTEND;TZID=Europe/Berlin:20261109T123000", "END:VEVENT",
    # all-day, folded description, Outlook's Windows zone name on a timed one
    "BEGIN:VEVENT", "UID:trip", "SUMMARY:Trip", "DTSTART;VALUE=DATE:20261106", "DTEND;VALUE=DATE:20261108",
    "DESCRIPTION:line one\\nline", "  two", "END:VEVENT",
    "BEGIN:VEVENT", "UID:call", "SUMMARY:Call", "DTSTART;TZID=W. Europe Standard Time:20261105T170000",
    "DURATION:PT30M", "END:VEVENT",
    "BEGIN:VEVENT", "UID:gone", "SUMMARY:Cancelled thing", "STATUS:CANCELLED",
    "DTSTART:20261105T080000Z", "DTEND:20261105T090000Z", "END:VEVENT",
    # monthly on the last Friday
    "BEGIN:VEVENT", "UID:review", "SUMMARY:Review", "DTSTART:20261030T150000Z", "DTEND:20261030T160000Z",
    "RRULE:FREQ=MONTHLY;BYDAY=-1FR;UNTIL=20270101T000000Z", "END:VEVENT",
    "END:VCALENDAR", ""])


def window():
    return datetime(2026, 11, 1, tzinfo=TZ), datetime(2027, 1, 31, tzinfo=TZ)


class Ics(unittest.TestCase):
    def setUp(self):
        self.evs = ics_source.raw_events("Uni", FEED, *window(), TZ)
        self.by = {}
        for e in self.evs:
            self.by.setdefault(e["title"], []).append(e)

    def starts(self, title):
        return [datetime.fromtimestamp(e["start_ts"], TZ).strftime("%a %d %H:%M") for e in self.by[title]]

    def test_weekly_rule_with_exdate_and_moved_occurrence(self):
        self.assertEqual(self.starts("Statistics, lecture"),
                         ["Mon 02 09:00", "Wed 11 09:00", "Mon 16 09:00", "Wed 18 09:00"])
        self.assertEqual(self.starts("Statistics, lecture (moved)"), ["Mon 09 11:00"])
        self.assertEqual(self.by["Statistics, lecture"][0]["location"], "Room 2.1")

    def test_all_day_folding_and_windows_zone(self):
        trip = self.by["Trip"][0]
        self.assertTrue(trip["all_day"])
        self.assertEqual(trip["notes"], "line one\nline two")
        end = datetime.fromtimestamp(trip["end_ts"], TZ)
        self.assertEqual((end.day, end.hour), (7, 23))           # like EventKit: 23:59:59 of the last day
        call = self.by["Call"][0]
        self.assertEqual(datetime.fromtimestamp(call["start_ts"], TZ).hour, 17)
        self.assertEqual(call["end_ts"] - call["start_ts"], 1800)

    def test_cancelled_is_dropped_and_monthly_last_friday(self):
        self.assertNotIn("Cancelled thing", self.by)
        self.assertEqual([s[:6] for s in self.starts("Review")], ["Fri 27", "Fri 25"])

    def test_same_shape_as_the_apple_export(self):
        rec = export_calendar.shape_event(self.by["Call"][0], TZ)
        self.assertEqual(set(rec), {"id", "title", "start", "end", "all_day", "calendar", "account", "location", "notes"})
        self.assertEqual((rec["start"], rec["calendar"], rec["account"]), ("2026-11-05T17:00+01:00", "Uni", "ics"))

    def test_feed_file_and_local_path(self):
        with tempfile.TemporaryDirectory() as t:
            ics = Path(t, "uni.ics")
            ics.write_text(FEED)
            lst = Path(t, "feeds.txt")
            lst.write_text(f"# comment\nUni | {ics}\n\nbroken line\n")
            feeds = ics_source.read_feeds(lst)
            self.assertEqual(feeds, [("Uni", str(ics))])
            evs, cals = ics_source.read_ics(feeds, *window())
        self.assertEqual(cals[0]["title"], "Uni")
        self.assertEqual(len(evs), len(self.evs))

    def test_runaway_rule_is_capped(self):
        feed = FEED.replace("RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=6", "RRULE:FREQ=DAILY")
        evs = ics_source.raw_events("Uni", feed, datetime(2026, 11, 1, tzinfo=TZ), datetime(2036, 1, 1, tzinfo=TZ), TZ)
        self.assertLessEqual(len([e for e in evs if e["title"].startswith("Statistics")]), ics_source.MAX_INSTANCES + 1)


if __name__ == "__main__":
    unittest.main()
