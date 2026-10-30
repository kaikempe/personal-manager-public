#!/usr/bin/env python3
"""Reads and ticks reminders of the list "Manager Inbox" through EventKit.

Replaces AppleScript, which launches Reminders.app and puts it in the Dock. Needs an interpreter
with pyobjc-framework-EventKit (default: the BB Tracker venv, as for the calendar export) and
Reminders access for it: run `reminders_io.py list` once by hand and click Allow.

  reminders_io.py list           JSON [{"id", "title", "notes"}] of open reminders
  reminders_io.py done ID        marks that reminder completed
"""
import json
import sys
import threading

LIST_NAME = "Manager Inbox"


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


def fetch(st, completed):
    from EventKit import EKEntityTypeReminder
    cals = [c for c in st.calendarsForEntityType_(EKEntityTypeReminder) if c.title() == LIST_NAME]
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


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    st = store()
    if cmd == "list":
        rems = fetch(st, False)
        print(json.dumps([{"id": r.calendarItemIdentifier(), "title": str(r.title() or ""),
                           "notes": str(r.notes() or "")} for r in rems]))
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
