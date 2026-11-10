#!/bin/bash
# One-time onboarding. Run: ./setup.sh   (safe to re-run; keeps what exists)
# Creates your private files from the examples, writes config.env, and installs the calendar export.
# Try it first without any setup:  python3 dashboard/server.py --demo
# Non-interactive (all defaults, installs nothing):  PM_SETUP_DEFAULTS=1 ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }
ask() {
  local r
  if [ -n "${PM_SETUP_DEFAULTS:-}" ]; then echo "$2"; return; fi
  read -r -p "$1 [$2] " r
  echo "${r:-$2}"
}

[ "$(uname)" = "Darwin" ] || { echo "Setup needs macOS (background jobs use launchd; Calendar, Reminders and Mail use Apple APIs)."; echo "The demo runs anywhere: python3 dashboard/server.py --demo"; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required (install the Xcode command line tools: xcode-select --install)."; exit 1; }

say "1/5  Your private files (gitignored: edit them freely)"
[ -f state.md ]    || sed "s/YYYY-MM-DD/$(date +%F)/" examples/state.md > state.md
[ -f items.json ]  || cp examples/items.json items.json
[ -d registry ]    || { mkdir registry; cp examples/registry/*.md registry/; }
[ -f CLAUDE.md ]   || cp CLAUDE.example.md CLAUDE.md
mkdir -p data config
echo "state.md, items.json, registry/, CLAUDE.md are ready."

say "2/5  Settings (config.env)"
SOURCES="eventkit"
if [ -f config.env ]; then
  echo "config.env exists, keeping it. Edit it by hand; scripts/pm_env.py lists every setting."
  SOURCES="$(python3 scripts/pm_env.py PM_CALENDAR_SOURCES)"
else
  NAME="$(ask 'Your first name (tasks are filed for it; flights starting with it are yours)' '')"
  TZ_GUESS="$(readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||')"
  TZNAME="$(ask 'Your timezone (IANA name)' "${TZ_GUESS:-UTC}")"
  echo "Calendars: 1 = Apple Calendar (everything Calendar.app shows), 2 = ICS feed links (Google, Outlook, school), 3 = both"
  case "$(ask 'Calendar source' '1')" in 2) SOURCES="ics" ;; 3) SOURCES="eventkit,ics" ;; *) SOURCES="eventkit" ;; esac
  WRITE="$(ask 'Apple calendar the tools may ADD events to (create-only)' 'Private')"
  RO="$(ask 'Calendars that must never be touched, comma separated (school, work feeds)' '')"
  MAIL="$(ask 'Mail.app accounts for mail suggestions, comma separated' 'iCloud')"
  cat > config.env <<CFG
# Your settings, read by scripts/pm_env.py (which lists every setting and its default). Never committed.
PM_OWNER_NAME=$NAME
PM_TIMEZONE=$TZNAME
PM_CALENDAR_SOURCES=$SOURCES
PM_WRITE_CALENDAR=$WRITE
PM_READONLY_CALENDARS=$RO
MAIL_ACCOUNTS=$MAIL
# Optional:
# VAULT_DIR=$HOME/Documents/Vault           Obsidian vault for vault sync, gym plan and chat memory
# PM_CLASS_CALENDARS=University              calendars whose events are classes (gym planning)
# GYM_SITE_URL=https://your-gym-log.netlify.app
CFG
  echo "Wrote config.env."
fi
if [[ "$SOURCES" == *ics* ]] && [ ! -f ics_feeds.txt ]; then
  cp ics_feeds.example.txt ics_feeds.txt
  echo "Created ics_feeds.txt: add one line per calendar link (it explains where to find them)."
fi

say "3/5  Your own chat rules (optional)"
[ -f config/chat_rules.md ] || cat > config/chat_rules.md <<'RULES'
- Travel: public transport (change to how you travel; the chat uses it for travel times).
RULES
echo "config/chat_rules.md is added to the dashboard chat's instructions. Plugins: see plugins/README.md."

say "4/5  Calendar export (every 15 minutes)"
if [ -n "${PM_SETUP_DEFAULTS:-}" ]; then
  echo "skipped (PM_SETUP_DEFAULTS)"
elif [ "$(ask 'Install it now? (y/n)' 'y')" = "y" ]; then
  PY="$(command -v python3)"
  if [[ "$SOURCES" == *eventkit* ]]; then
    echo "macOS will ask for Calendar access: click Allow."
    [ -x .venv/bin/python ] || python3 -m venv .venv
    .venv/bin/python -m pip install -q pyobjc-framework-EventKit
    PY="$PWD/.venv/bin/python"
    grep -q '^REMINDERS_PY=' config.env || echo "REMINDERS_PY=$PY" >> config.env
  fi
  ./scripts/install_calendar_export.sh "$PWD/data" "$PY" || echo "Calendar export failed; re-run: ./scripts/install_calendar_export.sh \"\$PWD/data\" \"$PY\""
fi

say "5/5  Claude (optional)"
if command -v claude >/dev/null; then
  echo "Claude Code found. The chat, mail suggestions and inbox use YOUR own Claude login."
else
  echo "Claude Code CLI not found. The dashboard works without it. To turn on the chat and suggestions, install it"
  echo "from https://claude.com/claude-code and run 'claude' once to log in."
fi

say "Done"
echo "Start the dashboard:  python3 dashboard/server.py     then open http://127.0.0.1:8765"
echo "Keep it running:      ./scripts/install_dashboard.sh"
echo "Check everything:     python3 scripts/health.py"
echo "Next: edit CLAUDE.md (your priorities) and registry/ (your projects). See README.md."
