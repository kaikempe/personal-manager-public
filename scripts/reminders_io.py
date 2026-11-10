#!/usr/bin/env python3
"""Reads and ticks reminders of the list "Manager Inbox" through EventKit.

Replaces AppleScript, which launches Reminders.app and puts it in the Dock. Needs an interpreter
with pyobjc-framework-EventKit (default: the BB Tracker venv, as for the calendar export) and
Reminders access for it: run `reminders_io.py list` once by hand and click Allow.

  reminders_io.py list           JSON [{"id", "title", "notes", "created"}] of open reminders
  reminders_io.py done ID        marks that reminder completed

Alerts for the phone (scripts/notify.py): a reminder with an alarm in another list syncs through iCloud and
notifies on every device.

  reminders_io.py add LIST TITLE [NOTES] [ISO_TIME]   new reminder in LIST (created if missing); alarm at ISO_TIME
  reminders_io.py sweep LIST HOURS                    ticks off this tool's reminders in LIST older than HOURS
"""
import json
import sys
import threading
from datetime import datetime

LIST_NAME = "Manager Inbox"
MARK = "(from personal-manager)"   # last line of the notes of every reminder this tool creates


def store():
    from EventKit import EKEntityTypeReminder, EKEventStore
    st = EKEventStore.alloc().init()
    done = threading.Event()
    result = {}

    def cb(granted, err):
        result["ok"], result["err"] = granted, err
        done.set()

    if hasattr(st, "requestFullAccessToRemindersWithCompletion_"):
        st.requestFullAccessToRemindersWithCompletion_(cb)
    else:
        st.requestAccessToEntityType_completion_(EKEntityTypeReminder, cb)
    done.wait(60)
    if not result.get("ok"):
        sys.exit(f"Reminders access denied ({result.get('err')}). Privacy & Security > Reminders.")
    return st


def fetch(st, completed, name=None):
    from EventKit import EKEntityTypeReminder
    cals = [c for c in st.calendarsForEntityType_(EKEntityTypeReminder) if c.title() == (name or LIST_NAME)]
    if not cals:
        return []
    pred = (st.predicateForCompletedRemindersWithCompletionDateStarting_ending_calendars_(None, None, cals)
            if completed else st.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(None, None, cals))
    out, done = [], threading.Event()

    def cb(rems):
        out.extend(rems or [])
        done.set()

    st.fetchRemindersMatchingPredicate_completion_(pred, cb)
    done.wait(60)
    return out


def created(r):
    d = r.creationDate()
    return datetime.fromtimestamp(d.timeIntervalSince1970()).astimezone().isoformat(timespec="seconds") if d else ""


def add(st, name, title, notes="", when=""):
    """A reminder in list `name` (created in the default account if missing). `when` (ISO) sets due time and alarm."""
    from EventKit import EKAlarm, EKCalendar, EKEntityTypeReminder, EKReminder
    from Foundation import NSCalendar, NSDate
    cal = next((c for c in st.calendarsForEntityType_(EKEntityTypeReminder) if c.title() == name), None)
    if cal is None:
        cal = EKCalendar.calendarForEntityType_eventStore_(EKEntityTypeReminder, st)
        cal.setTitle_(name)
        cal.setSource_(st.defaultCalendarForNewReminders().source())
        ok, err = st.saveCalendar_commit_error_(cal, True, None)[:2]
        if not ok:
            sys.exit(f"could not create the list {name}: {err}")
    r = EKReminder.reminderWithEventStore_(st)
    r.setTitle_(title[:200])
    r.setNotes_((notes.strip() + "\n" if notes.strip() else "") + MARK)
    r.setCalendar_(cal)
    if when:
        date = NSDate.dateWithTimeIntervalSince1970_(datetime.fromisoformat(when).astimezone().timestamp())
        r.setDueDateComponents_(NSCalendar.currentCalendar().components_fromDate_(0x4 | 0x8 | 0x10 | 0x20 | 0x40, date))
        r.addAlarm_(EKAlarm.alarmWithAbsoluteDate_(date))
    ok, err = st.saveReminder_commit_error_(r, True, None)[:2]
    if not ok:
        sys.exit(f"save failed: {err}")
    return r.calendarItemIdentifier()


def sweep(st, name, hours):
    """Tick off this tool's own reminders in `name` that are older than `hours`. Never deletes, never touches others."""
    n = 0
    for r in fetch(st, False, name):
        d = r.creationDate()
        if MARK in str(r.notes() or "") and d and (datetime.now().timestamp() - d.timeIntervalSince1970()) > hours * 3600:
            r.setCompleted_(True)
            if st.saveReminder_commit_error_(r, False, None)[0]:
                n += 1
    if n:
        st.commit_(None)
    return n


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    st = store()
    if cmd == "list":
        rems = fetch(st, False)
        print(json.dumps([{"id": r.calendarItemIdentifier(), "title": str(r.title() or ""),
                           "notes": str(r.notes() or ""), "created": created(r)} for r in rems]))
    elif cmd == "add" and len(sys.argv) > 3:
        a = sys.argv[2:] + ["", ""]
        print(add(st, a[0], a[1], a[2], a[3]))
    elif cmd == "sweep" and len(sys.argv) > 3:
        print(sweep(st, sys.argv[2], float(sys.argv[3])))
    elif cmd == "done" and len(sys.argv) > 2:
        for r in fetch(st, False):
            if r.calendarItemIdentifier() == sys.argv[2]:
                r.setCompleted_(True)
                ok, err = st.saveReminder_commit_error_(r, True, None)[:2]
                if not ok:
                    sys.exit(f"save failed: {err}")
                return
        sys.exit("reminder not found (already ticked?)")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
