"""Settings for every script and the dashboard, in one place.

config.env at the repo root (KEY=value lines, # comments) is loaded into os.environ; a real environment variable
with the same name wins. Import this module before reading os.environ. The defaults below are what a new install
gets; your own values go in config.env (created by setup.sh, never committed to the public repo).

    python3 scripts/pm_env.py KEY      # print one setting (used by the install_*.sh scripts)
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_f = ROOT / "config.env"
if _f.exists():
    for _line in _f.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            _v = _v.strip()
            if len(_v) >= 2 and _v[0] == _v[-1] and _v[0] in "\"'":
                _v = _v[1:-1]
            os.environ.setdefault(_k.strip(), _v)


def get(key, default=""):
    return os.environ.get(key) or default


def get_list(key, default=""):
    return [x.strip() for x in get(key, default).split(",") if x.strip()]


def path(key, default):
    return Path(os.path.expanduser(get(key, default)))


DEFAULTS = {
    "PM_HOME": str(ROOT),                       # where your files live: items.json, state.md, registry/, data/
    "PM_TIMEZONE": "UTC",                       # IANA name, e.g. Europe/Berlin
    "PM_OWNER_NAME": "",                        # your first name: tasks are filed for it, flights starting with it are yours
    "VAULT_DIR": "~/Documents/Vault",           # optional Obsidian vault
    "MAIL_ACCOUNTS": "iCloud",                  # Mail.app accounts read for suggestions, comma separated
    "MAIL_SCAN_ACCOUNTS": "",                   # accounts for the manual mail check (default: MAIL_ACCOUNTS)
    "PM_WRITE_CALENDAR": "Private",             # the one calendar the tools may create events in or delete from
    "PM_READONLY_CALENDARS": "",                # feeds you cannot edit (school, work); never touched, comma separated
    "PM_CLASS_CALENDARS": "",                   # calendars whose events are classes (gym planning), comma separated
    "PM_UNIVERSITY": "",                        # university name written into new course notes (vault sync)
    "PM_LABEL_PREFIX": "com.personal-manager",  # LaunchAgent label prefix
    "PM_REQUIRED_JOBS": "calendar-export",      # jobs whose absence is an error on the System page
    "BB_TRACKER_DATA": "~/Library/Application Support/BBTracker/data.json",  # optional BB Tracker app
    "PM_DEV_ROOT": "~/Developer",               # registry `path:` fields are relative to this
    "PM_CHAT_RULES": "config/chat_rules.md",    # your own extra rules for the dashboard chat (optional)
    "PM_SENSITIVE_EXTRA": "",                   # extra regex the chat must never save to the vault
    "PM_CALENDAR_SOURCES": "eventkit",          # eventkit (Apple Calendar), ics, or eventkit,ics
    "PM_ICS_FILE": "ics_feeds.txt",             # one "Name | URL-or-path" per line, for the ics source
    "GYM_SITE_URL": "",                         # your Netlify site for the gym sync
    "PM_PHONE_LIST": "",                        # Reminders list for alerts to your phone (scripts/notify.py); empty = Mac only
    "PM_QUIET_HOURS": "23:00-07:30",            # phone alerts raised in this window ring at its end
    "PM_PHONE_ALERT_HOURS": "48",               # phone alerts older than this are ticked off
    "PM_OFF_CAMPUS": r"^\s*(online day|off campus|no campus)\b",   # an event with such a title: no in-person class that day
    "PM_GYM_AUTOSYNC": "1",                     # 1 = the gym job keeps its own calendar events on the plan (add_gym.py --auto)
    "PM_DEMO": "",                              # 1 = demo data, no calendar writes, no model calls
}


def setting(key):
    return get(key, DEFAULTS.get(key, ""))


DATA = Path(os.path.expanduser(setting("PM_HOME")))
TIMEZONE = setting("PM_TIMEZONE")
OWNER = setting("PM_OWNER_NAME")
VAULT = path("VAULT_DIR", DEFAULTS["VAULT_DIR"])
WRITE_CALENDAR = setting("PM_WRITE_CALENDAR")
READONLY_CALENDARS = get_list("PM_READONLY_CALENDARS")
CLASS_CALENDARS = get_list("PM_CLASS_CALENDARS")
LABEL_PREFIX = setting("PM_LABEL_PREFIX")
BB_DATA = path("BB_TRACKER_DATA", DEFAULTS["BB_TRACKER_DATA"])
DEV_ROOT = path("PM_DEV_ROOT", DEFAULTS["PM_DEV_ROOT"])
DEMO = setting("PM_DEMO") == "1"


def chat_rules():
    """Your own lines for the dashboard chat's system prompt (config/chat_rules.md), or ''."""
    p = Path(os.path.expanduser(setting("PM_CHAT_RULES")))
    p = p if p.is_absolute() else ROOT / p
    try:
        return p.read_text().strip()
    except OSError:
        return ""


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: pm_env.py KEY")
    print(os.path.expanduser(setting(sys.argv[1])))
