#!/bin/bash
# One-time onboarding. Run: ./setup.sh
# Creates your private files from the examples, writes config.env, and (optionally) starts the dashboard.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }
ask() { local r; read -r -p "$1 [$2] " r; echo "${r:-$2}"; }

[ "$(uname)" = "Darwin" ] || { echo "This tool needs macOS (Calendar, Reminders and Mail are read through Apple APIs)."; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required (install Xcode command line tools: xcode-select --install)."; exit 1; }

say "1/4  Your private files"
[ -f state.md ]    || cp examples/state.md state.md
[ -f items.json ]  || cp examples/items.json items.json
[ -d registry ]    || { mkdir registry; cp examples/registry/*.md registry/; }
[ -f CLAUDE.md ]   || cp CLAUDE.example.md CLAUDE.md
mkdir -p data
echo "Created state.md, items.json, registry/, CLAUDE.md. They are gitignored; edit them freely."

say "2/4  Settings"
if [ -f config.env ]; then
  echo "config.env exists, keeping it."
else
  TZ_GUESS="$(readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||')"
  TZNAME="$(ask 'Your timezone (IANA name)' "${TZ_GUESS:-UTC}")"
  MAIL="$(ask 'Mail.app account names for mail suggestions, comma separated' 'iCloud')"
  cat > config.env <<CFG
# Read by the dashboard and scripts. Not committed.
PM_TIMEZONE=$TZNAME
MAIL_ACCOUNTS=$MAIL
# Optional: Obsidian vault folder, and your own Netlify site for gym sync
# VAULT_DIR=$HOME/Documents/Vault
# GYM_SITE_URL=https://your-gym-log.netlify.app
CFG
  echo "Wrote config.env."
fi

say "3/4  Calendar export (macOS will ask for Calendar access, click Allow)"
if [ "$(ask 'Install the 15-minute calendar export now? (y/n)' 'y')" = "y" ]; then
  if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
  .venv/bin/python -m pip install -q pyobjc-framework-EventKit
  echo "REMINDERS_PY=$PWD/.venv/bin/python" >> config.env
  ./scripts/install_calendar_export.sh "$PWD/data" "$PWD/.venv/bin/python" || echo "Calendar export failed; re-run ./scripts/install_calendar_export.sh \"\$PWD/data\" later."
fi

say "4/4  Claude (optional)"
if command -v claude >/dev/null; then
  echo "Claude Code found. The chat, mail suggestions and inbox use YOUR own Claude login."
else
  echo "Claude Code CLI not found. The dashboard works without it; install from https://claude.com/claude-code and run 'claude' once to log in to enable chat and suggestions."
fi

say "Done"
echo "Start the dashboard:  python3 dashboard/server.py   then open http://127.0.0.1:8765"
echo "Or keep it running:    ./scripts/install_dashboard.sh"
echo "Next: edit CLAUDE.md (your priorities) and registry/ (your projects). See README.md."
