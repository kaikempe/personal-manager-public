#!/bin/bash
# Keeps the dashboard server running as a LaunchAgent (starts at login, restarts if it dies)
# and builds the "Personal Manager" app (own window, scripts/build_app.sh) in ~/Applications.
#
#   ./scripts/install_dashboard.sh            install or update
#   ./scripts/install_dashboard.sh --remove   stop and remove both
set -euo pipefail

LABEL="$(python3 "$(dirname "$0")/pm_env.py" PM_LABEL_PREFIX).dashboard"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/personal-manager-dashboard.log"
APP="$HOME/Applications/Personal Manager.app"
PY="$(command -v python3)"
URL="http://127.0.0.1:8765"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true

if [ "${1:-}" = "--remove" ]; then
  rm -f "$PLIST"
  rm -rf "$APP"
  echo "removed $LABEL and $APP"
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs" "$HOME/Applications"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>$ROOT/dashboard/server.py</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLISTEOF
launchctl bootstrap "gui/$(id -u)" "$PLIST"

"$ROOT/scripts/build_app.sh"
echo "installed $LABEL (log $LOG) and $APP"
