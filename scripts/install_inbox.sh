#!/bin/bash
# Installs the automatic inbox as a LaunchAgent: runs every 5 minutes and whenever the iCloud
# "Manager Inbox" folder changes. scripts/inbox_process.py exits at once when nothing is new.
#
#   ./scripts/install_inbox.sh            install or update
#   ./scripts/install_inbox.sh --remove   stop and remove it
#
# Each run with something new starts a Claude Code session in this folder with a limited toolset
# (read, edit files, web search, scripts/cal_add.py). Reminders are read through scripts/reminders_io.py (EventKit, BB Tracker venv python; no Reminders.app launch).
# Needs macOS to allow Reminders access for that python, and automation of Calendar
# for the process that runs it: System Settings > Privacy & Security > Automation.
set -euo pipefail

LABEL="com.personal-manager.inbox"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/personal-manager-inbox.log"
PY="$(command -v python3)"
CLAUDE_BIN="$(command -v claude || echo "$HOME/.local/bin/claude")"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
if [ "${1:-}" = "--remove" ]; then
  rm -f "$PLIST"
  echo "removed $LABEL"
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>$ROOT/scripts/inbox_process.py</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CLAUDE_BIN</key><string>$CLAUDE_BIN</string>
    <key>PATH</key><string>$(dirname "$CLAUDE_BIN"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>300</integer>
  <key>WatchPaths</key><array><string>$ROOT/inbox/</string></array>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLISTEOF
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $LABEL: every 5 min and on changes in $ROOT/inbox/, log at $LOG"
