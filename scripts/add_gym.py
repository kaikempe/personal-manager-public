#!/usr/bin/env python3
"""Keep the gym sessions in the writable Apple Calendar (PM_WRITE_CALENDAR) in sync with the class timetable.

    python3 scripts/add_gym.py            # dry run: print the plan and what would change
    python3 scripts/add_gym.py --write    # apply it
    python3 scripts/add_gym.py --auto     # what the gym job runs: apply only when data/calendar.json shows a difference

Rules (items.json gym-weekly holds the data; classes are the events in PM_CLASS_CALENDARS):
  - Sessions in order: Day 1 chest/biceps (usually Mon), Day 2 back/triceps (Tue), Day 3 arms/shoulders (Thu), Day 4 legs (Fri).
  - Only on a day with an in-person class, starting 10 min after the last such class, 1.5h. Online sessions
    (titles matching PM_CLASS_SKIP) and asynchronous ones do not count as "last class".
  - A session whose usual day has no class moves to the next class day after the previous session; legs stays Friday.
  - Never more than 2 gym days in a row; from a longer run the lowest priority is dropped (Day 3, then 2, then 1).
  - Nothing special per weekday: with Monday off this gives Tue Day 1, Wed Day 2, Fri legs.
  - A week with no class at all (holidays): no gym.
  - A day with an event whose title matches PM_OFF_CAMPUS (default: "Online day", "Off campus", "No campus"), in any
    calendar, has no in-person class: its classes are attended from home. Add such an all-day event to skip a day
    (a strike, a sick day); the session moves by the rules above.

Never deletes. Events this script made carry a marker in their notes; when the plan changes, such
an event is moved or renamed to the new slot instead. Nothing else in the calendar is touched. An
event that is no longer needed is reported, and the user deletes it by hand. Safe to re-run.

--auto (PM_GYM_AUTOSYNC=1, from scripts/gym_ingest.py): a class that moves, or a new "Online day", changes the plan,
and the events used to stay where they were until someone re-ran --write. The job now compares the plan with
data/calendar.json (no AppleScript) and applies it only when they differ and the export is fresh; what it moved,
created or no longer needs is sent to the user (scripts/notify.py).
"""
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pm_env

ROOT = pm_env.DATA
CALENDAR = pm_env.WRITE_CALENDAR
# PM_CLASS_CALENDARS: the official class feed first, then (optional) the calendar you actually see, which wins when
# the two disagree. PM_CLASS_TITLE: regex a class title matches (default: every event in those calendars).
FEED, VISIBLE = (pm_env.CLASS_CALENDARS + ["", ""])[:2]
CLASS_TITLE = re.compile(pm_env.get("PM_CLASS_TITLE", "."), re.I)
CLASS_SKIP = re.compile(pm_env.get("PM_CLASS_SKIP"), re.I) if pm_env.get("PM_CLASS_SKIP") else None
OFF_CAMPUS = re.compile(pm_env.setting("PM_OFF_CAMPUS"), re.I) if pm_env.setting("PM_OFF_CAMPUS") else None
OFF_DAYS = {}   # date -> title of the event that says so; filled by class_ends()
WEEKS = 4
DURATION = timedelta(minutes=90)
GAP = timedelta(minutes=10)
MARKER = "Created by personal-manager (scripts/add_gym.py)"


def gym_item():
    items = json.loads((ROOT / "items.json").read_text())["items"]
    return next(i for i in items if i["id"] == "gym-weekly")


FIRST_DAY = ""


def off_days(events):
    """{date: event title} for every day covered by an event whose title matches PM_OFF_CAMPUS."""
    out = {}
    for e in events:
        if not (OFF_CAMPUS and OFF_CAMPUS.search(e.get("title") or "")):
            continue
        d = date.fromisoformat(e["start"][:10])
        last = max(d, date.fromisoformat((e.get("end") or e["start"])[:10]))
        if not e.get("all_day") and last > d and (e.get("end") or "")[11:16] == "00:00":
            last -= timedelta(days=1)   # a timed event ending at midnight does not reach into the next day
        while d <= last and len(out) < 60:
            out[d.isoformat()] = e["title"].strip()
            d += timedelta(days=1)
    return out


def class_ends():
    cal = json.loads((ROOT / "data/calendar.json").read_text())
    ends = {}
    # A school feed can keep a moved session at its old slot too (seen once: one session listed on Tue AND Wed; the
    # visible calendar had only Tue). When VISIBLE has the same course and session on another day, the FEED copy is
    # stale and ignored.
    def session(title):
        m = re.match(r"\s*(.+?)\s*\(Ses\.\s*(\d+)", title, re.I)
        return m and (re.sub(r"\s+", " ", m.group(1)).upper(), m.group(2))
    visible = {}
    for e in cal["events"]:
        if VISIBLE and e["calendar"] == VISIBLE and not e["all_day"] and session(e["title"]):
            visible.setdefault(session(e["title"]), set()).add(e["start"][:10])
    for e in cal["events"]:
        if e["all_day"] or e["calendar"] not in pm_env.CLASS_CALENDARS:
            continue
        if not CLASS_TITLE.search(e["title"]):
            continue
        key = session(e["title"])
        if e["calendar"] == FEED and key in visible and e["start"][:10] not in visible[key]:
            continue
        if CLASS_SKIP and CLASS_SKIP.search(e["title"]):
            continue
        start, end = (datetime.fromisoformat(e[k]).replace(tzinfo=None) for k in ("start", "end"))
        # Asynchronous sessions are exported as whole-day events; they are not a class to wait for.
        if "asynchronous" in e["title"].lower() or end - start > timedelta(hours=5):
            continue
        day = e["start"][:10]
        ends[day] = max(ends.get(day, end), end)
    OFF_DAYS.clear()
    OFF_DAYS.update(off_days(cal["events"]))
    for day in OFF_DAYS:   # at home that day: no class to come from, so no gym and no "after class" slot
        ends.pop(day, None)
    last_day = max((e["start"][:10] for e in cal["events"] if not e["all_day"]), default="")
    global FIRST_DAY
    # The export's own window start, not its first event: on 2026-11-09 (Mon, no class, first event Tue) the first-event
    # date made Monday "before the export, assume class", which put Day 1 on Monday and shifted the whole week.
    FIRST_DAY = (cal.get("window") or {}).get("from", "")[:10] or \
        min((e["start"][:10] for e in cal["events"] if not e["all_day"]), default="")
    return ends, cal["generated_at"], last_day


def plan():
    g = gym_item()
    days, split = g["recurrence"]["days"], g["details"]["split"]
    ends, generated, last_day = class_ends()
    today = date.today()
    out, notes = [], []
    for day, title in sorted(OFF_DAYS.items()):
        if day >= today.isoformat():
            notes.append(f'{date.fromisoformat(day):%a %d %b}: "{title}" in the calendar, so no in-person class and no gym')
    first_monday = today - timedelta(days=today.weekday())
    for w in range(WEEKS + 1):
        monday = first_monday + timedelta(weeks=w)
        week = [monday + timedelta(days=i) for i in range(5)]
        if week[-1] < today:
            continue
        if week[0].isoformat() > last_day:
            notes.append(f"week of {monday}: beyond the calendar export, not planned")
            continue
        if not any(d.isoformat() in ends for d in week):
            notes.append(f"week of {monday}: no class, no gym")
            continue
        # No special cases per weekday: the plan follows from the rules above. Sessions go in order (Day 1, 2, 3, legs), each on its
        # usual weekday, only on a day with an in-person class. A session whose day has no class moves to the next class day
        # after the previous session; legs stays on its day (Friday). Then no more than 2 gym days in a row: from a run of 3+,
        # the lowest-priority session is dropped (priority: legs, Day 1, Day 2, Day 3). Monday off therefore comes out as
        # Tue Day 1, Wed Day 2, Fri legs. A day before the export starts is assumed to have class (it says nothing about it).
        wd = {d.strftime("%a"): d for d in week}
        has_class = lambda d: d.isoformat() in ends or d.isoformat() < FIRST_DAY
        last = days[-1]
        chosen, prev = {}, None  # date -> split key
        for k in days:
            pref = wd[k]
            if k == last:
                d = pref if has_class(pref) else None
            elif has_class(pref) and (prev is None or pref > prev):
                d = pref
            else:
                d = next((x for x in week if has_class(x) and (prev is None or x > prev) and x < wd[last]), None)
            if d:
                chosen[d] = k
                prev = d
            else:
                notes.append(f"week of {monday}: {split[k]} has no class day, skipped")
        drop_order = days[:-1][::-1]  # Day 3 first, then Day 2, then Day 1; legs is never dropped
        while True:
            ds, runs, cur = sorted(chosen), [], []
            for d in ds:
                cur = cur + [d] if cur and d - cur[-1] == timedelta(days=1) else [d]
                if len(cur) > 2:
                    runs.append(list(cur))
            if not runs:
                break
            victim = next((d for k in drop_order for d in runs[0] if chosen[d] == k), None)
            if victim is None:
                break
            notes.append(f"{victim:%a %d %b}: {split[chosen[victim]]} dropped (max 2 gym days in a row)")
            del chosen[victim]
        for d, key in sorted(chosen.items()):
            if d < today:
                continue
            end = ends.get(d.isoformat())
            if not end:
                notes.append(f"{d:%a %d %b}: no class that day, skipped")
                continue
            s = end + GAP
            out.append({"title": f"Gym · {split[key]}", "start": s, "end": s + DURATION, "note": f"after class ending {end:%H:%M}",
                        "day": int(re.match(r"Day (\d)", split[key]).group(1))})
    return out, notes, generated


# ---------- AppleScript ----------
def osa(script):
    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=600)
    if res.returncode:
        sys.exit(res.stderr.strip())
    return res.stdout


def as_date(var, v):
    return (f'set {var} to current date\nset year of {var} to {v.year}\nset month of {var} to 1\nset day of {var} to 1\n'
            f'set month of {var} to {v.month}\nset day of {var} to {v.day}\nset time of {var} to {v.hour * 3600 + v.minute * 60}\n')


def existing_slow():
    """Ask Calendar for every event carrying the marker. Takes minutes on a full calendar (measured 2026-11-10: 4-5 min)."""
    out = osa(f'''tell application "Calendar"
set res to ""
repeat with e in (every event of calendar "{CALENDAR}" whose description is "{MARKER}")
set sd to start date of e
set res to res & (uid of e) & "|" & (year of sd) & "-" & (month of sd as integer) & "-" & (day of sd) & " " & (hours of sd) & ":" & (minutes of sd) & "|" & (summary of e) & linefeed
end repeat
return res
end tell''')
    evs = []
    for line in filter(None, (l.strip() for l in out.splitlines())):
        uid, start, title = line.split("|", 2)
        evs.append({"uid": uid, "start": datetime.strptime(start, "%Y-%m-%d %H:%M"), "title": title})
    return evs


def existing(max_age=timedelta(minutes=20)):
    """This script's events in the calendar. Read from the export when it is fresh (instant); such an event has no
    uid here and is addressed by its exact title and start instead. A stale export falls back to asking Calendar."""
    try:
        cal = json.loads((ROOT / "data/calendar.json").read_text())
        fresh = datetime.now().astimezone() - datetime.fromisoformat(cal["generated_at"]) < max_age
    except (OSError, ValueError, KeyError):
        fresh = False
    if not fresh:
        return existing_slow()
    return [{"uid": None, "start": datetime.fromisoformat(e["start"]).replace(tzinfo=None), "title": e["title"]}
            for e in cal["events"]
            if e["calendar"] == CALENDAR and not e["all_day"] and MARKER in (e.get("notes") or "")]


def create(ev):
    osa(f'''tell application "Calendar"
set c to calendar "{CALENDAR}"
{as_date("s", ev["start"])}{as_date("e", ev["end"])}make new event at end of events of c with properties {{summary:"{ev["title"]}", start date:s, end date:e, description:"{MARKER}"}}
end tell''')


def move(h, ev):
    """Move (and rename) one of this script's events to the planned slot. `h` is a row from existing(): found by uid,
    or by exact title and start, and then only when exactly one event matches."""
    if h.get("uid"):
        find = f'set m to first event of c whose uid is "{h["uid"]}"'
    else:
        find = (as_date("o", h["start"]) + f'set found to (every event of c whose summary is "{h["title"]}" and start date is o)\n'
                'if (count of found) is not 1 then error "gym event not found exactly once: " & (count of found)\n'
                "set m to item 1 of found")
    osa(f'''tell application "Calendar"
set c to calendar "{CALENDAR}"
{as_date("s", ev["start"])}{as_date("e", ev["end"])}{find}
set summary of m to "{ev["title"]}"
if (start date of m) < s then
set end date of m to e
set start date of m to s
else
set start date of m to s
set end date of m to e
end if
end tell''')


def sync(events):
    have = [e for e in existing() if e["start"].date() >= date.today()]
    todo = []
    for ev in events:
        match = next((h for h in have if h["start"] == ev["start"] and h["title"] == ev["title"]), None)
        if match:
            have.remove(match)
        else:
            todo.append(ev)
    # Reuse a leftover event of ours for each new slot (same week first, nearest in time) before creating.
    moves, creates = [], []
    for ev in todo:
        wk = ev["start"].isocalendar()[:2]
        near = sorted((h for h in have if h["start"].isocalendar()[:2] == wk), key=lambda h: abs((h["start"] - ev["start"]).total_seconds()))
        if near:
            h = near[0]
            have.remove(h)
            moves.append((h, ev))
        else:
            creates.append(ev)
    return moves, creates, have  # `have` is now: ours, no longer needed


def drift(events, cal_events, today):
    """(missing, extra): planned sessions that are not in the exported calendar, and this script's own events there
    that the plan no longer has. Pure; reads the export, not Calendar."""
    want = {(ev["start"].isoformat(timespec="minutes"), ev["title"]) for ev in events}
    have = {(e["start"][:16], e["title"]) for e in cal_events
            if e["calendar"] == CALENDAR and MARKER in (e.get("notes") or "") and e["start"][:10] >= today.isoformat()}
    return sorted(want - have), sorted(have - want)


def auto():
    """The unattended run. Does nothing unless the export is fresh, ok, and differs from the plan."""
    if pm_env.setting("PM_GYM_AUTOSYNC") != "1" or pm_env.DEMO:
        return
    cal = json.loads((ROOT / "data/calendar.json").read_text())
    try:
        status = json.loads((ROOT / "data/export_status.json").read_text())
    except (OSError, ValueError):
        status = {}
    age = datetime.now().astimezone() - datetime.fromisoformat(cal["generated_at"])
    if not status.get("ok") or age > timedelta(minutes=60):
        return   # never move events on the word of a stale or failed export
    events, _, _ = plan()
    missing, extra = drift(events, cal["events"], date.today())
    stamp = ROOT / "data/gym_autosync.json"
    key = json.dumps([missing, extra])
    try:
        last = json.loads(stamp.read_text())
    except (OSError, ValueError):
        last = {}
    if not (missing or extra):
        return
    # The export lags a write by up to 15 minutes: the same difference twice in a row was already handled.
    if last.get("key") == key and datetime.now() - datetime.fromisoformat(last["at"]) < timedelta(minutes=40):
        return
    moves, creates, unused = sync(events)
    for h, ev in moves:
        move(h, ev)
    for ev in creates:
        create(ev)
    stamp.write_text(json.dumps({"key": key, "at": datetime.now().isoformat(timespec="seconds")}))
    lines = [f'{h["start"]:%a %-d %b %H:%M} → {ev["start"]:%a %-d %b %H:%M} {ev["title"].split(" ", 2)[-1]}' for h, ev in moves]
    lines += [f'new {ev["start"]:%a %-d %b %H:%M} {ev["title"].split(" ", 2)[-1]}' for ev in creates]
    lines += [f'not needed any more, delete it: {h["start"]:%a %-d %b %H:%M} {h["title"]}' for h in unused]
    if lines:
        import notify
        text = "Gym plan changed: " + "; ".join(lines)
        print(text)
        notify.send(text, phone=True, key="gym-sync:" + key)


def main():
    if "--auto" in sys.argv:
        return auto()
    write = "--write" in sys.argv
    events, notes, generated = plan()
    print(f"calendar export: {generated}")
    for ev in events:
        print(f'{ev["start"]:%a %d %b  %H:%M}-{ev["end"]:%H:%M}  {ev["title"]}  ({ev["note"]})')
    for n in notes:
        print("note:", n)
    moves, creates, unused = sync(events)
    print()
    for h, ev in moves:
        print(f'move: {h["start"]:%a %d %b %H:%M} "{h["title"]}"  ->  {ev["start"]:%a %d %b %H:%M} "{ev["title"]}"')
    for ev in creates:
        print(f'create: {ev["start"]:%a %d %b %H:%M} "{ev["title"]}"')
    for h in unused:
        print(f'no longer needed (delete by hand in Calendar): {h["start"]:%a %d %b %H:%M} "{h["title"]}"')
    if not (moves or creates):
        print("calendar already matches the plan")
    if not write:
        print("\ndry run. Re-run with --write to apply.")
        return
    for h, ev in moves:
        move(h, ev)
    for ev in creates:
        create(ev)
    print(f"\nmoved {len(moves)}, created {len(creates)}, left for you to delete {len(unused)}")


if __name__ == "__main__":
    main()
