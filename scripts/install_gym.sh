#!/bin/bash
# Sets up the gym tracker on the Mac: the iCloud folder "Manager Gym", the gym/ symlink in this repo,
# and a LaunchAgent that runs scripts/gym_ingest.py every 15 minutes and whenever a workout file
# lands in gym/sessions/. The same run refreshes plan.json (from Notes) and history.json.
#
#   ./scripts/install_gym.sh            install or update
#   ./scripts/install_gym.sh --remove   stop and remove the LaunchAgent (folder and data stay)
#
# Needs macOS to allow automation of Notes and Calendar for the process that runs it:
# System Settings > Privacy & Security > Automation.
set -euo pipefail

LABEL="$(python3 "$(dirname "$0")/pm_env.py" PM_LABEL_PREFIX).gym"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/personal-manager-gym.log"
PY="$(command -v python3)"
ICLOUD="$HOME/Library/Mobile Documents/com~apple~CloudDocs/Manager Gym"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
if [ "${1:-}" = "--remove" ]; then
  rm -f "$PLIST"
  echo "removed $LABEL"
  exit 0
fi

mkdir -p "$ICLOUD/sessions" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
[ -e "$ROOT/gym" ] || ln -s "$ICLOUD" "$ROOT/gym"
grep -qx 'gym' "$ROOT/.gitignore" || echo 'gym' >> "$ROOT/.gitignore"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>$ROOT/scripts/gym_ingest.py</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>900</integer>
  <key>WatchPaths</key><array><string>$ICLOUD/sessions/</string></array>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLISTEOF
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $LABEL: every 15 min and on new files in $ICLOUD/sessions/, log at $LOG"
