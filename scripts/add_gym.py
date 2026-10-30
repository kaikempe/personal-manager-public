#!/usr/bin/env python3
"""Keep the gym sessions in the Apple Calendar "Private" calendar in sync with the class timetable.

    python3 scripts/add_gym.py            # dry run: print the plan and what would change
    python3 scripts/add_gym.py --write    # apply it

Rules (items.json, gym-weekly):
  - Normal week: Mon, Tue, Thu, Fri, each starting 10 min after the last class that day, 1.5h.
  - Monday off (no class Monday): the first two class days Tue-Thu get Day 1 and Day 2, the third
    rests. Fri stays legs.
  - A week with no class at all (holidays): no gym.
  - Spanish and asynchronous sessions do not count as "last class".

Never deletes. Events this script made carry a marker in their notes; when the plan changes, such
an event is moved or renamed to the new slot instead. Nothing else in the calendar is touched. An
event that is no longer needed is reported, and the user deletes it by hand. Safe to re-run.
"""
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CALENDAR = "Private"
WEEKS = 4
DURATION = timedelta(minutes=90)
GAP = timedelta(minutes=10)
MARKER = "Created by personal-manager (scripts/add_gym.py)"


def gym_item():
    items = json.loads((ROOT / "items.json").read_text())["items"]
    return next(i for i in items if i["id"] == "gym-weekly")


FIRST_DAY = ""


def class_ends():
    cal = json.loads((ROOT / "data/calendar.json").read_text())
    ends = {}
    for e in cal["events"]:
        if e["all_day"] or e["calendar"] not in ("IE University", "Calendar"):
            continue
        if not re.search(r"\(Ses|\s-\s\d+-\d+", e["title"], re.I):
            continue
        if re.search(r"espa[nñ]ol", e["title"], re.I):
            continue
        start, end = (datetime.fromisoformat(e[k]).replace(tzinfo=None) for k in ("start", "end"))
        # Asynchronous sessions are exported as whole-day events; they are not a class to wait for.
        if "asynchronous" in e["title"].lower() or end - start > timedelta(hours=5):
            continue
        day = e["start"][:10]
        ends[day] = max(ends.get(day, end), end)
    last_day = max((e["start"][:10] for e in cal["events"] if not e["all_day"]), default="")
    global FIRST_DAY
    FIRST_DAY = min((e["start"][:10] for e in cal["events"] if not e["all_day"]), default="")
    return ends, cal["generated_at"], last_day


def plan():
    g = gym_item()
    days, split, off_rule = g["recurrence"]["days"], g["details"]["split"], g["details"]["monday_off"]
    ends, generated, last_day = class_ends()
    today = date.today()
    out, notes = [], []
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
        # The export starts mid-week: Monday is not in it, which says nothing about class, so a week that began
        # before the export keeps the standard pattern instead of the Monday-off shift (which would re-number Thu).
        monday_off = monday.isoformat() not in ends and monday.isoformat() >= FIRST_DAY
        chosen = {}  # date -> split key
        if not monday_off:
            for d in week:
                if d.strftime("%a") in days:
                    chosen[d] = d.strftime("%a")
        else:
            notes.append(f"week of {monday}: Monday off")
            mid = [d for d in week[1:4] if d.isoformat() in ends][:2]
            chosen.update(zip(mid, off_rule["sessions"]))
            if week[4].isoformat() in ends:
                chosen[week[4]] = "Fri"
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
    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
    if res.returncode:
        sys.exit(res.stderr.strip())
    return res.stdout


def as_date(var, v):
    return (f'set {var} to current date\nset year of {var} to {v.year}\nset month of {var} to 1\nset day of {var} to 1\n'
            f'set month of {var} to {v.month}\nset day of {var} to {v.day}\nset time of {var} to {v.hour * 3600 + v.minute * 60}\n')


def existing():
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


def create(ev):
    osa(f'''tell application "Calendar"
set c to calendar "{CALENDAR}"
{as_date("s", ev["start"])}{as_date("e", ev["end"])}make new event at end of events of c with properties {{summary:"{ev["title"]}", start date:s, end date:e, description:"{MARKER}"}}
end tell''')


def move(uid, ev):
    osa(f'''tell application "Calendar"
set c to calendar "{CALENDAR}"
{as_date("s", ev["start"])}{as_date("e", ev["end"])}set m to first event of c whose uid is "{uid}"
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


def main():
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
        move(h["uid"], ev)
    for ev in creates:
        create(ev)
    print(f"\nmoved {len(moves)}, created {len(creates)}, left for you to delete {len(unused)}")


if __name__ == "__main__":
    main()
