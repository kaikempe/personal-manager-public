#!/usr/bin/env python3
"""Sample data for trying the dashboard without any setup: a fictional student, "Alex", this week.

    python3 dashboard/server.py --demo        # builds it in a temp folder and serves it on http://127.0.0.1:8765
    python3 scripts/make_demo.py [DIR]        # only write the files (default: a new temp folder), print the folder

Dates are relative to today, so the demo always looks current. Nothing here reads your calendar, mail or files.
Standard library only; does not import pm_env (the server sets PM_HOME to this folder before loading settings).
"""
import json
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path


def build(out=None):
    home = Path(out or tempfile.mkdtemp(prefix="pm-demo-"))
    (home / "data").mkdir(parents=True, exist_ok=True)
    (home / "registry").mkdir(exist_ok=True)
    (home / "vault").mkdir(exist_ok=True)
    now = datetime.now().astimezone()
    today = now.date()
    monday = today - timedelta(days=today.weekday())

    def at(d, hm):
        h, m = map(int, hm.split(":"))
        return datetime(d.year, d.month, d.day, h, m, tzinfo=now.tzinfo).isoformat(timespec="minutes")

    events, n = [], 0

    def ev(d, start, end, title, cal, loc=""):
        nonlocal n
        n += 1
        events.append({"id": f"demo-{n}", "title": title, "start": at(d, start), "end": at(d, end), "all_day": False,
                       "calendar": cal, "account": "demo", "location": loc, "notes": ""})

    for w in range(3):
        for i, (s, e, t, loc) in enumerate([("09:00", "10:30", "Statistics (Ses. {n})", "Room 2.1"),
                                            ("11:00", "12:30", "Microeconomics (Ses. {n})", "Room 1.4"),
                                            ("09:30", "11:00", "Programming (Ses. {n})", "Lab B"),
                                            ("10:00", "11:30", "Statistics (Ses. {n})", "Room 2.1"),
                                            ("12:00", "13:30", "Marketing (Ses. {n})", "Room 3.2")]):
            d = monday + timedelta(weeks=w, days=i)
            ev(d, s, e, t.format(n=w * 2 + 3), "University", loc)
            ev(d, "14:00" if i != 4 else "13:40", "15:30" if i != 4 else "15:10", f"Gym · Day {i % 4 + 1}", "Private")
    ev(today + timedelta(days=1), "19:30", "21:30", "Dinner with Sam", "Private", "Calle Mayor 12")
    ev(today + timedelta(days=2), "16:00", "17:00", "Group project meeting", "University", "Library, room 4")
    ev(today + timedelta(days=4), "07:15", "09:40", "Sam flight LH1804 MUC → MAD", "Private", "Munich Airport T2")
    ev(today + timedelta(days=3), "18:00", "18:45", "Haircut", "Private", "Barber shop")
    events.sort(key=lambda e: e["start"])
    stamp = now.isoformat(timespec="seconds")
    w = lambda name, obj: (home / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False))
    w("data/calendar.json", {"schema": 1, "generated_at": stamp, "timezone": str(now.tzinfo), "event_count": len(events),
                             "events": events, "calendars": [{"title": "University", "account": "demo", "type": "subscribed"},
                                                             {"title": "Private", "account": "demo", "type": "caldav"}]})
    w("data/export_status.json", {"ran_at": stamp, "ok": True, "events": len(events), "error": None})
    w("data/mail_status.json", {"ran_at": stamp, "ok": True, "last_ok": stamp, "new_mail": 6, "picked": 2, "proposed": 1})
    w("data/proposals.json", {"proposals": [{
        "id": "demo-p1", "status": "new", "kind": "new", "fields": {}, "existing": None, "created": stamp,
        "item": {"type": "event", "title": "Concert: city orchestra", "start": at(today + timedelta(days=6), "20:00"),
                 "end": at(today + timedelta(days=6), "22:00"), "all_day": False, "location": "Auditorio Nacional",
                 "notes": "From the ticket mail", "confidence": "confirmed"},
        "source": {"account": "iCloud", "received": stamp[:16], "sender": "Tickets <tickets@example.com>",
                   "subject": "Your tickets for Saturday"}}]})
    w("data/inbox_log.json", {"entries": [{"ran_at": stamp, "results": [
        {"item": "Sam lands Friday morning, pick up?", "handled": True, "summary": "Sam's flight is already in the calendar",
         "did": ["linked the note to the flight"], "needs_user": "Do you want a reminder to leave for the airport?"}]}]})
    w("bb.json", {"timestamp": now.replace(tzinfo=None).isoformat(timespec="seconds"), "error": None, "courses": [],
                  "announcements": [], "prep": [], "deadlines": [
        {"course": "STATISTICS", "source": "assignment", "title": "Problem set 4", "due": at(today + timedelta(days=2), "23:59"),
         "done": False, "status": "open", "kind": "assignment"},
        {"course": "MARKETING", "source": "exam", "title": "Midterm", "due": at(today + timedelta(days=8), "12:00"),
         "ends": at(today + timedelta(days=8), "13:30"), "done": False, "status": "open", "kind": "exam"}]})
    w("items.json", {"_doc": "Demo data: tasks, routines and details behind calendar events.", "items": [
        {"id": "t1", "type": "task", "title": "Email the group the slide outline", "who": "Alex",
         "due": (today + timedelta(days=1)).isoformat(), "status": "open", "confidence": "confirmed", "source": "me"},
        {"id": "t2", "type": "task", "title": "Renew the transit card", "who": "Alex",
         "due": (today + timedelta(days=5)).isoformat(), "status": "open", "confidence": "confirmed", "source": "me"}]})
    (home / "state.md").write_text(f"""# State

Last reviewed: {today.isoformat()}

## This week's priorities
1. Statistics problem set 4 (graded, due in 2 days)
2. Marketing midterm prep: one past paper per day
3. Portfolio site: ship the projects page

## Waiting on
- Group project: Maria sends her section by Thursday

## Not in the calendar
- Gym follows the class days
""")
    (home / "CLAUDE.md").write_text("# Working rules (demo)\n\nGraded work > paid work > own projects. Answer first, max 3 items.\n")
    for name, status, kind, summary in [("portfolio-site", "active", "project", "Personal site with project write-ups"),
                                        ("trading-journal", "on-hold", "project", "Spreadsheet-backed trading journal"),
                                        ("statistics", "active", "course", "Statistics, second semester")]:
        (home / "registry" / f"{name}.md").write_text(
            f"---\nname: {name}\nkind: {kind}\nstatus: {status}\nconfirmed: true\nsummary: {summary}\n"
            f"next: The next concrete step.\n" + ("revisit: after the midterms\n" if status == "on-hold" else "") +
            f"---\n\n{summary}. Demo entry.\n")
    return home


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else None))
