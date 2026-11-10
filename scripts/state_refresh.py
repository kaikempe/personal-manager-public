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
sys.path.insert(0, str(ROOT / "scripts"))
import notify  # noqa: E402

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


UNDATED_DAYS = 7   # a task this old without a due date is called out: without a date nothing ever makes it urgent


def undated_days(item, today):
    """Days an open task has existed without a due date, or None (it has a date, waits on someone, or no created date)."""
    if item.get("due") or item.get("blocked_by") or not item.get("created"):
        return None
    if str(item.get("start") or "")[:10] > today.isoformat():   # "can start from" a later day: nothing is late yet
        return None
    try:
        return (today - datetime.fromisoformat(str(item["created"])[:10]).date()).days
    except ValueError:
        return None


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
    unclear = o["bb"].get("unclear", [])
    for d in unclear:   # no day: listed apart, never in the priorities
        u = d["unclear"]
        out.append(f"- DATE UNCLEAR | {nice(d['course'])}: {d['title']} | timetable said {u['timetable'][:10]} {u['timetable'][11:16]}, "
                   f"announcement \"{u.get('announcement')}\" changed it | read it; no calendar event settles it")
    for d in rows:
        loc = f" | {d['location']}" if d.get("location") else ""
        flag = f" | NOTE: {d['flag']}" if d.get("flag") else ""
        out.append(f"- {d['due'][:10]} {d['due'][11:16]} | {nice(d['course'])}: {d['title']}{loc}{flag}")
    if not rows and not unclear:
        out.append("- none")
    tasks = [i for i in o["items"] if i.get("type") == "task" and i.get("status") != "done"]
    out += ["", "## Open tasks (items.json)"]
    for i in tasks:
        due = f" | due {i['due']}" if i.get("due") else (f" | {(i.get('when') or {}).get('hint')}" if (i.get("when") or {}).get("hint") else "")
        blk = f" | waiting on {i['blocked_by']}" if i.get("blocked_by") else ""
        age = undated_days(i, today)
        old = f" | no date, open {age} days" if age is not None and age >= UNDATED_DAYS else ""
        out.append(f"- {i['title']}{due}{blk}{old}")
    if not tasks:
        out.append("- none")
    return "\n".join(out)


def alerts(o, now, prev_errors=(), send=None):
    """What the hourly run tells the phone (scripts/notify.py; every key is sent once). Returns the names of the
    health errors seen now, for the next run.

      - a mail suggestion that is still unanswered and falls due within 48 hours: the Suggestions page is only seen
        at the Mac, and one due the same day sat there for 12 hours (2026-11-09);
      - a deadline whose date needs a second look (`flag` starting "date unclear");
      - a health error that is still there an hour later (one run can catch a Mac that just woke up)."""
    send = send or notify.send
    soon = (now + timedelta(hours=48)).isoformat()[:16]
    for p in o.get("proposals", []):
        it = p.get("item") or {}
        when = str(it.get("start") or "")
        if p.get("status") != "new" or not when or not now.date().isoformat() <= when[:10] or when[:16] > soon:
            continue
        day = day_label(when[:10], now.date())
        what = "Due" if it.get("type") == "task" else "On"
        send(f'{what} {day.lower() if day in ("Today", "Tomorrow") else day}: {it.get("title")}. '
             "A suggestion from your mail, waiting on the dashboard.", phone=True, key=f'proposal:{p.get("id")}')
    for d in o["bb"].get("unclear", []):   # open_deadlines drops a row the user's calendar settled
        u = d["unclear"]
        was = datetime.fromisoformat(u["timetable"])
        send(f'{nice(d["course"])} {d["title"].lower()}: the date is unclear (timetable says '
             f'{DAYS[was.weekday()]} {was.day} {MONTHS[was.month - 1]} {u["timetable"][11:16]}, an announcement changed it). '
             "Read the announcement.", phone=True, key=f'deadline-flag:{d["course"]}:{d["title"]}:{u["timetable"][:10]}')
    if now.weekday() == 6 and now.hour >= 17:   # Sunday evening, with the weekly review: tasks that never got a date
        old = [i["title"] for i in o.get("items", []) if i.get("type") == "task" and i.get("status") not in ("done", "dropped")
               and (undated_days(i, now.date()) or 0) >= 2 * UNDATED_DAYS]
        if old:
            send(f'{len(old)} task{"s" if len(old) != 1 else ""} without a date for two weeks or more: ' + ", ".join(old[:4]) +
                 ". Give each a day or drop it.", phone=True, key=f"undated:{now.date().isocalendar()[1]}")
    errors = [r for r in o.get("health", []) if r.get("level") == "error"]
    for r in errors:
        if r["name"] in prev_errors:
            send(f'{r["name"]}: {r["detail"]}', phone=True, key=f'health:{r["name"]}:{now.date()}')
    return [r["name"] for r in errors]


def plugin_hourly():
    """Plugins with HOURLY() get one call per run (plugins/README.md). A failure is printed, never raised."""
    import plugins_load
    for mod, fn in plugins_load.each("HOURLY"):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(f"{mod.__name__}: hourly hook failed: {e}", file=sys.stderr)


def main():
    path = server.DATA / "state.md"
    text = path.read_text()
    o = server.overview()
    block = f"{START}\n{build(o)}\n{END}"
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
        notify.send("The weekly review is over a week old: state.md's manual sections need a look.", phone=True, key=f"review:{today}")
        st["notified"] = today
    if not server.pm_env.DEMO:
        try:
            st["errors"] = alerts(o, datetime.now(), st.get("errors", []))
            plugin_hourly()
            notify.sweep()
        except Exception as e:  # noqa: BLE001  (telling the user must never stop the refresh)
            print(f"alerts failed: {e}", file=sys.stderr)
    st["ran_at"] = datetime.now().isoformat(timespec="seconds")
    stamp.write_text(json.dumps(st))


if __name__ == "__main__":
    main()
