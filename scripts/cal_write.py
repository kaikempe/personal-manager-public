"""Writes to Apple Calendar through AppleScript: create, enrich, and delete (delete only on the user's explicit
accept, one event in the writable calendar, PM_WRITE_CALENDAR).

Used for suggestions and chat actions the user accepted. In demo mode (PM_DEMO=1) nothing is written. Event text can come from an email, so every
string is stripped of control characters and escaped before it goes into a script.
"""
import re
import subprocess
from datetime import datetime, timedelta

import pm_env

CALENDAR = pm_env.WRITE_CALENDAR
MARKER = "Added from mail by personal-manager"


# Events that must never go into the calendar (PM_NEVER_ADD regex on "title | location"), e.g. a booking system's
# slots when another event already stands for the visit. Checked here so every writer is covered; the dashboard
# also hides matching events that already sit in a synced calendar.
NEVER_ADD = re.compile(pm_env.get("PM_NEVER_ADD"), re.I) if pm_env.get("PM_NEVER_ADD") else None


def blocked(ev):
    return bool(NEVER_ADD and NEVER_ADD.search(f'{ev.get("title", "")} | {ev.get("location", "")}'))


def q(s):
    """AppleScript string literal for untrusted text."""
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", str(s or "")).strip()[:300]
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def osa(script):
    if pm_env.DEMO:
        raise RuntimeError("demo mode: the calendar is not changed")
    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=60)
    if res.returncode:
        raise RuntimeError(res.stderr.strip()[:300] or "osascript failed")
    return res.stdout.strip()


def as_date(var, v):
    return (f"set {var} to current date\nset year of {var} to {v.year}\nset month of {var} to 1\nset day of {var} to 1\n"
            f"set month of {var} to {v.month}\nset day of {var} to {v.day}\nset time of {var} to {v.hour * 3600 + v.minute * 60}\n")


def parse(s):
    return datetime.fromisoformat(s) if len(s) > 10 else datetime.fromisoformat(s + "T00:00")


def create(ev, calendar=CALENDAR, note=""):
    """ev: title, start, end (optional), all_day, location. Returns the new event's uid."""
    if blocked(ev):
        raise RuntimeError("refused: matches PM_NEVER_ADD, so it is never added to the calendar")
    start = parse(ev["start"])
    all_day = bool(ev.get("all_day"))
    if all_day:
        start = start.replace(hour=0, minute=0)
        end = start + timedelta(days=1)
    else:
        end = parse(ev["end"]) if ev.get("end") else start + timedelta(hours=1)
        if end <= start:
            end = start + timedelta(hours=1)
    desc = MARKER + (f". {note}" if note else "")
    props = f'summary:{q(ev["title"])}, start date:s, end date:e, description:{q(desc)}'
    if ev.get("location"):
        props += f', location:{q(ev["location"])}'
    if all_day:
        props += ", allday event:true"
    return osa(f'''tell application "Calendar"
set c to calendar {q(calendar)}
{as_date("s", start)}{as_date("e", end)}set ev to make new event at end of events of c with properties {{{props}}}
return uid of ev
end tell''')


def delete(existing, calendar=CALENDAR):
    """Delete ONE event from the writable calendar, matched by title and start. Only called after the user's
    explicit accept on the dashboard (see server.act_chat). Refuses unless exactly one event matches."""
    start = parse(existing["start"])
    return osa(f'''tell application "Calendar"
set c to calendar {q(calendar)}
{as_date("s", start)}set found to (every event of c whose summary is {q(existing["title"])} and start date is s)
if (count of found) is not 1 then return "not found or ambiguous (" & (count of found) & ")"
delete item 1 of found
return "ok"
end tell''')


def enrich(existing, calendar, location=None, end=None):
    """Fill a missing location and/or end time on ONE existing event (matched by title and start)."""
    start = parse(existing["start"])
    sets = ""
    if location:
        sets += f"set location of m to {q(location)}\n"
    if end:
        sets += as_date("e", parse(end)) + "set end date of m to e\n"
    if not sets:
        return "nothing to add"
    return osa(f'''tell application "Calendar"
set c to calendar {q(calendar)}
{as_date("s", start)}set found to (every event of c whose summary is {q(existing["title"])} and start date is s)
if (count of found) is not 1 then return "not found or ambiguous (" & (count of found) & ")"
set m to item 1 of found
{sets}return "ok"
end tell''')
