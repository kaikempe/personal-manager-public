#!/bin/bash
# Installs the mail suggestion check as a LaunchAgent that fires every 15 min and at load; the script skips unless the last good run is ~50 min old, and waits quietly when offline.
#
#   ./scripts/install_mail_suggest.sh            install or update
#   ./scripts/install_mail_suggest.sh --remove   stop and remove it
#
# Needs macOS to allow automation of Mail for the process that runs it. If the first run reports
# a permission error on the dashboard, allow it in System Settings > Privacy & Security > Automation.
set -euo pipefail

LABEL="$(python3 "$(dirname "$0")/pm_env.py" PM_LABEL_PREFIX).mail-suggest"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/mail-suggest.log"
PY="$(command -v python3)"
CLAUDE_BIN="$(command -v claude || echo "$HOME/.local/bin/claude")"

if [ "${1:-}" = "--remove" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "removed $LABEL"
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>$ROOT/scripts/mail_suggest.py</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CLAUDE_BIN</key><string>$CLAUDE_BIN</string>
    <key>PATH</key><string>$(dirname "$CLAUDE_BIN"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>900</integer>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $LABEL: every 15 min, script-throttled to hourly, log at $LOG"
