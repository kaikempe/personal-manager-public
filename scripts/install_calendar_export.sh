#!/bin/bash
# Installs the calendar export as a LaunchAgent that runs every 15 minutes.
#
#   ./install_calendar_export.sh OUT_DIR [PYTHON]
#
# OUT_DIR  where calendar.json goes. For Claude to read it from any session, use a
#          folder inside Google Drive for desktop (My Drive/...).
# PYTHON   interpreter with pyobjc-framework-EventKit. Default: the BB Tracker venv.
set -euo pipefail

OUT="${1:?usage: install_calendar_export.sh OUT_DIR [PYTHON]}"
PY="${2:-$(command -v python3)}"
LABEL="com.personal-manager.calendar-export"
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/share/calendar-export"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/calendar-export.log"

[ -x "$PY" ] || { echo "python not found: $PY" >&2; exit 1; }
"$PY" -c "import EventKit" 2>/dev/null || { echo "$PY cannot import EventKit" >&2; exit 1; }

mkdir -p "$DEST" "$OUT" "$HOME/Library/LaunchAgents"
cp "$HERE/export_calendar.py" "$DEST/export_calendar.py"

echo "Step 1: permission check. Click Allow if macOS asks."
"$PY" "$DEST/export_calendar.py" --check

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$DEST/export_calendar.py</string>
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
echo "Uninstall: launchctl bootout gui/\$UID/$LABEL && rm \"$PLIST\""
