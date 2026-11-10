#!/usr/bin/env python3
"""One way for every script to tell the user something.

    notify.send("Booked: gym Thu 15:00")                       # this Mac only
    notify.send("Problem Set 4 is due today", phone=True, key="proposal:317283")   # the phone too, once per key

    python3 scripts/notify.py "text" [--phone] [--key K]       # the same from a shell
    python3 scripts/notify.py --sweep                          # tick off phone alerts older than PM_PHONE_ALERT_HOURS

A macOS notification is only seen by someone sitting at the Mac. With PM_PHONE_LIST set (the name of a Reminders
list, created on first use), `phone=True` also files a reminder with an alarm there; iCloud syncs it and the phone
shows it as a notification. Nothing leaves the user's own iCloud account. Rules, all in this file:
  - `key`: the same key is sent to the phone once (data/notify_sent.json, kept 30 days), so an hourly job can call
    send() every run.
  - Quiet hours (PM_QUIET_HOURS, default 23:00-07:30): the alarm is set for the end of the quiet time instead of now.
  - The list is this tool's outbox, not the inbox: scripts/inbox_process.py never reads it. Alerts older than
    PM_PHONE_ALERT_HOURS (default 48) are ticked off by `--sweep` (never deleted).
A failure to notify never raises: the caller's own work must not depend on it.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pm_env  # noqa: E402

SENT = pm_env.DATA / "data" / "notify_sent.json"
LOG = pm_env.DATA / "data" / "notify_log.jsonl"
REM_IO = str(Path(__file__).resolve().parent / "reminders_io.py")
LEAD = timedelta(minutes=2)    # iCloud needs a moment to carry the reminder to the phone before its alarm fires


def phone_list():
    return pm_env.setting("PM_PHONE_LIST")


def rem_py():
    return os.path.expanduser(pm_env.get("REMINDERS_PY") or sys.executable)


def alarm_time(now, quiet=None):
    """When the phone should ring: in two minutes, or at the end of the quiet hours when `now` is inside them."""
    quiet = pm_env.setting("PM_QUIET_HOURS") if quiet is None else quiet
    t = now + LEAD
    try:
        a, b = (datetime.strptime(x.strip(), "%H:%M").time() for x in quiet.split("-"))
    except ValueError:
        return t
    inside = (a <= t.time() or t.time() < b) if a > b else (a <= t.time() < b)
    if not inside:
        return t
    end = t.replace(hour=b.hour, minute=b.minute, second=0, microsecond=0)
    return end if end > t else end + timedelta(days=1)


def _read(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def already_sent(key, now):
    sent = {k: v for k, v in _read(SENT, {}).items() if v >= (now - timedelta(days=30)).isoformat()}
    return key in sent, sent


def mac(text, title):
    subprocess.run(["osascript", "-e", f"display notification {json.dumps(text[:240])} with title {json.dumps(title)}"],
                   capture_output=True, timeout=20)


def to_phone(text, notes, when, run=subprocess.run):
    res = run([rem_py(), REM_IO, "add", phone_list(), text, notes, when.isoformat(timespec="seconds")],
              capture_output=True, text=True, timeout=90)
    if res.returncode:
        raise RuntimeError((res.stderr or res.stdout or "reminders_io failed").strip()[:200])


def send(text, title="Personal manager", phone=False, key=None, notes="", now=None, _mac=mac, _phone=to_phone):
    """Returns what happened: {"mac": bool, "phone": "sent" | "off" | "duplicate" | "demo" | "error: ..."}."""
    now = now or datetime.now()
    out = {"mac": False, "phone": "off"}
    text = " ".join(str(text).split())
    if pm_env.DEMO or os.environ.get("PM_NO_NOTIFY") == "1":   # demo mode and the test suite never notify
        return {**out, "phone": "demo"}
    dup, sent = already_sent(key, now) if key else (False, {})
    if not dup:
        try:
            _mac(text, title)
            out["mac"] = True
        except (OSError, subprocess.SubprocessError):
            pass
    if phone and phone_list():
        if dup:
            out["phone"] = "duplicate"
        else:
            try:
                _phone(text, notes, alarm_time(now))
                out["phone"] = "sent"
            except (OSError, RuntimeError, subprocess.SubprocessError) as e:
                out["phone"] = f"error: {e}"
    elif dup:
        out["phone"] = "duplicate"
    if key and not dup and out["phone"] in ("sent", "off"):
        sent[key] = now.isoformat(timespec="seconds")
        try:
            SENT.parent.mkdir(exist_ok=True)
            SENT.write_text(json.dumps(sent, indent=1))
        except OSError:
            pass
    try:
        with LOG.open("a") as f:
            f.write(json.dumps({"ts": now.astimezone().isoformat(timespec="seconds"), "text": text, "key": key, **out},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass
    return out


def sweep(run=subprocess.run):
    if not phone_list() or pm_env.DEMO:
        return 0
    res = run([rem_py(), REM_IO, "sweep", phone_list(), pm_env.setting("PM_PHONE_ALERT_HOURS")],
              capture_output=True, text=True, timeout=90)
    return int(res.stdout.strip() or 0) if res.returncode == 0 else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--sweep"]:
        print(f"ticked off {sweep()} old alert(s)")
    elif args and not args[0].startswith("--"):
        key = args[args.index("--key") + 1] if "--key" in args else None
        print(send(args[0], phone="--phone" in args, key=key))
    else:
        sys.exit(__doc__)
