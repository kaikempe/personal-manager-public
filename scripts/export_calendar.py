#!/usr/bin/env python3
"""Dump the next N days of Calendar.app events to calendar.json (read-only).

Sources (PM_CALENDAR_SOURCES in config.env, comma separated):
  eventkit  every calendar Calendar.app shows (iCloud, Exchange, Google, ...), through EventKit (needs pyobjc)
  ics       the feeds listed in ics_feeds.txt (Google, Outlook, school timetables), see scripts/ics_source.py

Writes three files into the output directory:

  calendar.json       events + generated_at; only replaced on a successful run
  export_status.json  always written: when it ran, ok or not, and why
  calendars.json      the calendars/accounts it can see (for debugging)

A reader must check generated_at in calendar.json and treat anything older than
~1 hour as stale.

Usage:
  export_calendar.py --out DIR [--days 30] [--back 1]
  export_calendar.py --check            # permission + calendar list, writes nothing
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import traceback
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pm_env  # noqa: E402
import ics_source  # noqa: E402

SCHEMA = 1
_NOT_DETERMINED = 0
_FULL_ACCESS = 3          # macOS 14+: full access; older systems: plain "authorized"
_CANCELED = 3             # EKEventStatusCanceled
_SOURCE_TYPES = {0: "local", 1: "exchange", 2: "caldav", 3: "mobileme",
                 4: "subscribed", 5: "birthdays"}


class ExportError(Exception):
    pass


def atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def shape_event(raw: dict, tz) -> dict:
    """Pure: turn plain values pulled off an EKEvent into the output record.

    raw keys: id, title, start_ts, end_ts, all_day, calendar, source, location
    """
    all_day = bool(raw["all_day"])
    start = datetime.fromtimestamp(raw["start_ts"], tz)
    end = datetime.fromtimestamp(raw["end_ts"], tz)
    if all_day:
        # EventKit ends an all-day event at 23:59:59 of its last day.
        s, e = start.date().isoformat(), end.date().isoformat()
    else:
        s, e = start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes")
    return {
        "id": f"{raw['id']}@{int(raw['start_ts'])}",
        "title": raw["title"] or "(no title)",
        "start": s,
        "end": e,
        "all_day": all_day,
        "calendar": raw["calendar"],
        "account": raw["source"],
        "location": raw["location"] or "",
        "notes": raw.get("notes", ""),
    }


def build_payload(raw_events: list[dict], raw_calendars: list[dict], now: datetime,
                  window_start: datetime, window_end: datetime) -> dict:
    tz = now.tzinfo
    events = [shape_event(r, tz) for r in raw_events]
    events.sort(key=lambda e: (e["start"], e["end"], e["title"]))
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(timespec="seconds"),
        "timezone": str(tz),
        "window": {"from": window_start.isoformat(timespec="minutes"),
                   "to": window_end.isoformat(timespec="minutes")},
        "event_count": len(events),
        "events": events,
        "calendars": raw_calendars,
    }


def _request_access(store, timeout: float = 90.0) -> bool:
    done = threading.Event()
    result = {"ok": False}

    def handler(ok, _err):
        result["ok"] = bool(ok)
        done.set()

    if hasattr(store, "requestFullAccessToEventsWithCompletion_"):
        store.requestFullAccessToEventsWithCompletion_(handler)
    else:
        store.requestAccessToEntityType_completion_(0, handler)
    if not done.wait(timeout):
        raise ExportError("Calendar permission prompt got no answer in "
                          f"{int(timeout)}s (no one to click it?)")
    return result["ok"]


def read_eventkit(window_start: datetime, window_end: datetime):
    """Return (raw_events, raw_calendars). Raises ExportError on permission problems."""
    try:
        from EventKit import EKEventStore
        from Foundation import NSDate
    except ImportError as exc:
        raise ExportError(f"EventKit not importable ({exc}). Use the python from setup.sh (.venv), "
                          "or: pip install pyobjc-framework-EventKit; or set PM_CALENDAR_SOURCES=ics") from exc

    status = EKEventStore.authorizationStatusForEntityType_(0)
    store = EKEventStore.alloc().init()
    if status == _NOT_DETERMINED:
        if not _request_access(store):
            raise ExportError("Calendar access was refused")
    elif status != _FULL_ACCESS:
        raise ExportError(
            f"Calendar access not granted (status {status}). System Settings > "
            "Privacy & Security > Calendars: allow the python binary or Terminal "
            "that runs this script, with Full Access.")

    cals = list(store.calendarsForEntityType_(0) or [])
    raw_calendars = [{
        "title": str(c.title()),
        "account": str(c.source().title()),
        "type": _SOURCE_TYPES.get(int(c.source().sourceType()), "other"),
        "writable": bool(c.allowsContentModifications()),
    } for c in cals]

    start = NSDate.dateWithTimeIntervalSince1970_(window_start.timestamp())
    end = NSDate.dateWithTimeIntervalSince1970_(window_end.timestamp())
    pred = store.predicateForEventsWithStartDate_endDate_calendars_(start, end, None)
    raw_events = []
    for ev in store.eventsMatchingPredicate_(pred) or []:
        if int(ev.status()) == _CANCELED:
            continue
        raw_events.append({
            "id": str(ev.eventIdentifier() or ev.calendarItemIdentifier() or ""),
            "title": str(ev.title() or ""),
            "start_ts": ev.startDate().timeIntervalSince1970(),
            "end_ts": ev.endDate().timeIntervalSince1970(),
            "all_day": bool(ev.isAllDay()),
            "calendar": str(ev.calendar().title()),
            "source": str(ev.calendar().source().title()),
            "location": str(ev.location() or ""),
            "notes": str(ev.notes() or "")[:800],
        })
    return raw_events, raw_calendars


def read_sources(w_start, w_end):
    sources = pm_env.get_list("PM_CALENDAR_SOURCES", pm_env.DEFAULTS["PM_CALENDAR_SOURCES"])
    events, calendars = [], []
    if "eventkit" in sources:
        e, c = read_eventkit(w_start, w_end)
        events, calendars = events + e, calendars + c
    if "ics" in sources:
        f = Path(os.path.expanduser(pm_env.setting("PM_ICS_FILE")))
        feeds = ics_source.read_feeds(f if f.is_absolute() else pm_env.ROOT / f)
        if not feeds:
            raise ExportError(f"PM_CALENDAR_SOURCES has ics, but {f} lists no feeds")
        e, c = ics_source.read_ics(feeds, w_start, w_end)
        events, calendars = events + e, calendars + c
    if not {"eventkit", "ics"} & set(sources):
        raise ExportError(f"PM_CALENDAR_SOURCES={','.join(sources)}: use eventkit, ics or both")
    return events, calendars


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path,
                    default=Path(os.environ.get("CAL_EXPORT_DIR", "~/calendar-export")).expanduser())
    ap.add_argument("--days", type=int, default=30, help="days ahead (default 30)")
    ap.add_argument("--back", type=int, default=1, help="days back (default 1)")
    ap.add_argument("--check", action="store_true",
                    help="print permission state and calendars, write nothing")
    args = ap.parse_args(argv)

    now = datetime.now().astimezone()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    w_start = midnight - timedelta(days=args.back)
    w_end = midnight + timedelta(days=args.days + 1)

    status_path = args.out / "export_status.json"
    try:
        raw_events, raw_calendars = read_sources(w_start, w_end)
        payload = build_payload(raw_events, raw_calendars, now, w_start, w_end)
    except Exception as exc:
        msg = str(exc) if isinstance(exc, ExportError) else "".join(
            traceback.format_exception_only(type(exc), exc)).strip()
        print(f"FAILED: {msg}", file=sys.stderr)
        if not args.check:
            try:
                atomic_write(status_path, {"ran_at": now.isoformat(timespec="seconds"),
                                           "ok": False, "error": msg})
            except Exception as werr:
                print(f"also could not write status: {werr}", file=sys.stderr)
        return 1

    if args.check:
        print(f"OK, {payload['event_count']} events in window "
              f"{payload['window']['from']} .. {payload['window']['to']}")
        for c in raw_calendars:
            print(f"  {c['account']:<28} {c['type']:<10} {c['title']}")
        return 0

    atomic_write(args.out / "calendar.json", payload)
    atomic_write(args.out / "calendars.json", {"generated_at": payload["generated_at"],
                                               "calendars": raw_calendars})
    atomic_write(status_path, {"ran_at": payload["generated_at"], "ok": True,
                               "events": payload["event_count"], "error": None})
    return 0


if __name__ == "__main__":
    sys.exit(main())
