#!/bin/bash
# Installs the calendar export as a LaunchAgent that runs every 15 minutes.
#
#   ./install_calendar_export.sh OUT_DIR [PYTHON]
#   ./install_calendar_export.sh --remove
#
# OUT_DIR  where calendar.json goes (normally the repo's data/ folder).
# PYTHON   interpreter for the job. With the eventkit source it needs pyobjc-framework-EventKit
#          (setup.sh makes .venv); ics alone needs nothing. Default: REMINDERS_PY from config.env, else python3.
# The job runs export_calendar.py in place, so it always uses this repo's code and config.env.
set -euo pipefail

if [ "${1:-}" = "--remove" ]; then
  LABEL="$(python3 "$(dirname "$0")/pm_env.py" PM_LABEL_PREFIX).calendar-export"
  launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
  echo "removed $LABEL"
  exit 0
fi
OUT="${1:?usage: install_calendar_export.sh OUT_DIR [PYTHON] | --remove}"
PY="${2:-$(python3 "$(dirname "$0")/pm_env.py" REMINDERS_PY)}"; PY="${PY:-$(command -v python3)}"
LABEL="$(python3 "$(dirname "$0")/pm_env.py" PM_LABEL_PREFIX).calendar-export"
HERE="$(cd "$(dirname "$0")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/calendar-export.log"

[ -x "$PY" ] || { echo "python not found: $PY" >&2; exit 1; }
if [[ "$(python3 "$HERE/pm_env.py" PM_CALENDAR_SOURCES)" == *eventkit* ]]; then
  "$PY" -c "import EventKit" 2>/dev/null || { echo "$PY cannot import EventKit (pip install pyobjc-framework-EventKit, or use the ics source)" >&2; exit 1; }
fi

mkdir -p "$OUT" "$HOME/Library/LaunchAgents"

echo "Step 1: check the sources. Click Allow if macOS asks for Calendar access."
"$PY" "$HERE/export_calendar.py" --check

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$HERE/export_calendar.py</string>
    <string>--out</string><string>$OUT</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>900</integer>
  <!-- also run whenever the network changes (wifi reconnects, wake, new network) -->
  <key>LaunchEvents</key>
  <dict>
    <key>com.apple.notifyd.matching</key>
    <dict>
      <key>network-change</key>
      <dict>
        <key>Notification</key><string>com.apple.system.config.network_change</string>
      </dict>
    </dict>
  </dict>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"
launchctl kickstart -k "gui/$UID/$LABEL"

echo "Step 2: waiting for the background job's first run..."
sleep 8
cat "$OUT/export_status.json" 2>/dev/null || echo "no export_status.json yet; see $LOG"
echo
echo "Uninstall: $0 --remove"
