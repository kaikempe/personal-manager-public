#!/usr/bin/env python3
"""Create ONE event in the writable calendar (PM_WRITE_CALENDAR), unless it is already in data/calendar.json.

    python3 scripts/cal_add.py --title "Dinner with Sam" --start 2026-10-30T20:00 [--end ...] [--location ...]
                               [--note ...] [--all-day]

Create-only (cal_write.create). The duplicate rule lives here, not in whoever calls it: an event
with the same title (case-insensitive, whitespace squeezed) on the same day is refused, so no
caller can file one thing twice. Prints the new event's uid, or "duplicate: ..." and exits 3.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cal_write  # noqa: E402
import pm_env  # noqa: E402

CAL = pm_env.DATA / "data" / "calendar.json"


def norm(t):
    return re.sub(r"\s+", " ", t or "").strip().lower()


def duplicate(title, start):
    """The existing calendar.json event with the same title on the same day, or None."""
    try:
        events = json.loads(CAL.read_text()).get("events", [])
    except (OSError, ValueError):
        return None
    return next((e for e in events if norm(e["title"]) == norm(title) and e["start"][:10] == start[:10]), None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--start", required=True, help="YYYY-MM-DDTHH:MM, or YYYY-MM-DD with --all-day")
    ap.add_argument("--end")
    ap.add_argument("--location")
    ap.add_argument("--note", default="")
    ap.add_argument("--all-day", action="store_true")
    a = ap.parse_args()
    e = duplicate(a.title, a.start)
    if e:
        print(f'duplicate: "{e["title"]}" already on {e["start"][:10]} ({e.get("calendar", "?")})')
        return 3
    print(cal_write.create({"title": a.title, "start": a.start, "end": a.end, "location": a.location,
                            "all_day": a.all_day}, note=a.note or "Added from the inbox by personal-manager"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
