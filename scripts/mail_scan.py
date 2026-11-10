#!/usr/bin/env python3
"""Recent mail headers from every Mail.app account, for the "check mail" routine.

    python3 scripts/mail_scan.py [--days 7] [--per-account 80]

Writes data/mail_recent.tsv (account, received, sender, subject) and prints a summary.
Headers only: subject, sender, date. Bodies are read one message at a time by Claude,
only for mails that look like they belong in the calendar or need action.

Mail's AppleScript is slow, so each account is read with one bulk query and a timeout.
The unified `inbox` is NOT used: it missed the iCloud account.
"""
import argparse
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pm_env

ROOT = Path(__file__).resolve().parent.parent
# MAIL_SCAN_ACCOUNTS in config.env (Mail.app account names), else the suggestion accounts
ACCOUNTS = pm_env.get_list("MAIL_SCAN_ACCOUNTS") or pm_env.get_list("MAIL_ACCOUNTS", pm_env.DEFAULTS["MAIL_ACCOUNTS"])

SCRIPT = '''
with timeout of 90 seconds
tell application "Mail"
  set mb to missing value
  repeat with m in (mailboxes of account "{acct}")
    if (name of m) is "INBOX" or (name of m) is "Inbox" then set mb to m
  end repeat
  if mb is missing value then return ""
  set n to count of messages of mb
  if n > {n} then set n to {n}
  if n < 1 then return ""
  set subs to subject of (messages 1 thru n of mb)
  set snd to sender of (messages 1 thru n of mb)
  set dts to date received of (messages 1 thru n of mb)
  set out to ""
  repeat with i from 1 to n
    set d to item i of dts
    set stamp to (year of d as string) & "-" & text -2 thru -1 of ("0" & ((month of d) as integer)) & "-" & text -2 thru -1 of ("0" & (day of d)) & "T" & text -2 thru -1 of ("0" & (hours of d)) & ":" & text -2 thru -1 of ("0" & (minutes of d))
    set out to out & stamp & tab & (item i of snd) & tab & (item i of subs) & linefeed
  end repeat
  return out
end tell
end timeout
'''


def scan(acct, n):
    res = subprocess.run(["osascript", "-e", SCRIPT.format(acct=acct, n=n)], capture_output=True, text=True, timeout=120)
    if res.returncode:
        raise RuntimeError(res.stderr.strip()[:200])
    return [l.split("\t", 2) for l in res.stdout.splitlines() if l.count("\t") >= 2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--per-account", type=int, default=80)
    a = ap.parse_args()
    cutoff = (datetime.now() - timedelta(days=a.days)).strftime("%Y-%m-%dT%H:%M")
    rows, report = [], []
    for acct in ACCOUNTS:
        try:
            got = scan(acct, a.per_account)
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            report.append(f"{acct}: FAILED ({e})")
            continue
        recent = [(acct, *r) for r in got if r[0] >= cutoff]
        reached_cutoff = bool(got) and got[-1][0] < cutoff
        rows += recent
        report.append(f"{acct}: {len(recent)} in last {a.days}d" + ("" if reached_cutoff or not got else f" (WARNING: newest {a.per_account} are all newer than the cutoff, raise --per-account)"))
    rows.sort(key=lambda r: r[1], reverse=True)
    out = ROOT / "data" / "mail_recent.tsv"
    out.parent.mkdir(exist_ok=True)
    out.write_text("".join("\t".join(r) + "\n" for r in rows))
    print("\n".join(report))
    print(f"wrote {len(rows)} rows to {out.relative_to(ROOT)} at {datetime.now().isoformat(timespec='seconds')}")


if __name__ == "__main__":
    sys.exit(main())
