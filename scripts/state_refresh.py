#!/usr/bin/env python3
"""Keeps the calendar-derived part of state.md current, so it never goes stale between weekly reviews.

state.md has two parts:
  * between <!-- auto:start --> and <!-- auto:end -->: regenerated here from live data (Blackboard deadlines,
    items.json tasks, calendar freshness). Never edit by hand.
  * everything else (waiting on, not in the calendar, open decisions, study plan): the user's and the weekly review's,
    kept untouched. `Last reviewed:` dates that part.

Runs hourly from launchd (scripts/install_state.sh). If the manual part was last reviewed more than 7 days ago it
sends one macOS notification per day (the weekly review is due). `--print` shows the block without writing.
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))
import server  # noqa: E402  (same data the dashboard shows)

START, END = "<!-- auto:start -->", "<!-- auto:end -->"
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
SMALL = {"of", "and", "for", "the", "in", "to", "on"}


def nice(s):
    if not s or re.search(r"[a-zà-ÿ]", s):
        return s or ""
    return " ".join(w.lower() if i and w.lower() in SMALL else w.capitalize() for i, w in enumerate(s.split()))


def day_label(d, today):
    dt = datetime.fromisoformat(d)
    if d == today.isoformat():
        return "Today"
    if d == (today + timedelta(days=1)).isoformat():
        return "Tomorrow"
    return f"{DAYS[dt.weekday()]} {dt.day} {MONTHS[dt.month - 1]}"


def build(o):
    now = datetime.fromisoformat(o["now"])
    today = now.date()
    horizon = (today + timedelta(days=7)).isoformat()
    cal = o["calendar"]
    out = [f"Auto-updated: {now:%Y-%m-%d %H:%M} by scripts/state_refresh.py (hourly). Do not edit between the markers.",
           f"Calendar: data/calendar.json generated {cal.get('generated_at')}, ok={cal.get('ok')}. "
           "University detail: BB Tracker data (graded deadlines below come from it).", ""]
    # Items due in the next 7 days, grouped per day; graded work first by the priority rule (graded > paid > own).
    by_day = {}
    for d in o["bb"]["deadlines"]:
        day = d["due"][:10]
        if today.isoformat() <= day <= horizon and datetime.fromisoformat(d["due"]) >= now - timedelta(hours=1):
            by_day.setdefault(day, []).append((d["due"], f"{d['title']} ({nice(d['course'])}) {d['due'][11:16]}"))
    for i in o["items"]:
        if i.get("type") == "task" and i.get("status") != "done" and i.get("due") and today.isoformat() <= i["due"][:10] <= horizon:
            by_day.setdefault(i["due"][:10], []).append((i["due"], f"{i['title']} (task)"))
    out.append("## This week's priorities (computed)")
    for n, day in enumerate(sorted(by_day)[:3], 1):
        items = [t for _, t in sorted(by_day[day])]
        out.append(f"{n}. {day_label(day, today)}: " + ("; ".join(items)))
    if not by_day:
        out.append("1. Nothing graded or due in the next 7 days.")
    out += ["", "## Deadlines (next 14 days, from BB Tracker)"]
    lim = (today + timedelta(days=14)).isoformat()
    rows = [d for d in o["bb"]["deadlines"] if d["due"][:10] <= lim]
    for d in rows:
        loc = f" | {d['location']}" if d.get("location") else ""
        out.append(f"- {d['due'][:10]} {d['due'][11:16]} | {nice(d['course'])}: {d['title']}{loc}")
    if not rows:
        out.append("- none")
    tasks = [i for i in o["items"] if i.get("type") == "task" and i.get("status") != "done"]
    out += ["", "## Open tasks (items.json)"]
    for i in tasks:
        due = f" | due {i['due']}" if i.get("due") else ""
        blk = f" | waiting on {i['blocked_by']}" if i.get("blocked_by") else ""
        out.append(f"- {i['title']}{due}{blk}")
    if not tasks:
        out.append("- none")
    return "\n".join(out)


def main():
    path = server.DATA / "state.md"
    text = path.read_text()
    block = f"{START}\n{build(server.overview())}\n{END}"
    if "--print" in sys.argv:
        print(block)
        return
    if START in text and END in text:
        new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda m: block, text, flags=re.S)
    else:  # first run: put the block after the header lines
        head, _, rest = text.partition("\n## ")
        new = f"{head}\n\n{block}\n\n## {rest}"
    if new != text:
        path.write_text(new)
    # one notification per day when the manual part is a week old
    m = re.search(r"Last reviewed:\s*(\d{4}-\d{2}-\d{2})", text)
    stamp = server.DATA / "data/state_refresh.json"
    st = json.loads(stamp.read_text()) if stamp.exists() else {}
    today = datetime.now().date().isoformat()
    if m and (datetime.now() - datetime.fromisoformat(m.group(1))).days > 7 and st.get("notified") != today:
        subprocess.run(["osascript", "-e", 'display notification "state.md manual sections are over a week old: run the weekly review" with title "Personal manager"'], check=False)
        st["notified"] = today
    st["ran_at"] = datetime.now().isoformat(timespec="seconds")
    stamp.write_text(json.dumps(st))


if __name__ == "__main__":
    main()
