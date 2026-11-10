#!/bin/bash
# Installs the LaunchAgent that keeps the Obsidian vault in step once a day at 21:30:
# scripts/vault_daily.py (vault_sync.py, the vault's health check, a git snapshot of the vault).
# The job's program is python3 itself: macOS allows it into iCloud Drive, and git then runs under that
# permission (see the docstring of vault_daily.py). Install with the same python3 that has the permission.
#
#   ./scripts/install_vault.sh            install or update
#   ./scripts/install_vault.sh --remove   stop and remove the LaunchAgent (vault and history stay)
set -euo pipefail

LABEL="$(python3 "$(dirname "$0")/pm_env.py" PM_LABEL_PREFIX).vault"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/personal-manager-vault.log"
PY="$(command -v python3)"

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
  <array><string>$PY</string><string>$ROOT/scripts/vault_daily.py</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLISTEOF
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $LABEL: daily at 21:30, log at $LOG"
