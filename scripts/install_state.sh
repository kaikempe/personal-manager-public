#!/bin/bash
# Installs the LaunchAgent that refreshes the calendar-derived part of state.md every hour (scripts/state_refresh.py).
#   ./scripts/install_state.sh            install or update
#   ./scripts/install_state.sh --remove   stop and remove it
set -euo pipefail
LABEL="$(python3 "$(dirname "$0")/pm_env.py" PM_LABEL_PREFIX).state"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/personal-manager-state.log"
PY="$(command -v python3)"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
if [ "${1:-}" = "--remove" ]; then rm -f "$PLIST"; echo "removed $LABEL"; exit 0; fi
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$ROOT/scripts/state_refresh.py</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>3600</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLISTEOF
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $LABEL: hourly, log at $LOG"
