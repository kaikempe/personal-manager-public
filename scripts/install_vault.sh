#!/bin/bash
# Installs the LaunchAgent that keeps the Obsidian vault in step once a day at 21:30:
# scripts/vault_daily.sh (vault_sync.py, the vault's health check, a git snapshot of the vault).
#
#   ./scripts/install_vault.sh            install or update
#   ./scripts/install_vault.sh --remove   stop and remove the LaunchAgent (vault and history stay)
set -euo pipefail

LABEL="com.personal-manager.vault"
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
  <array><string>/bin/bash</string><string>$ROOT/scripts/vault_daily.sh</string></array>
  <key>EnvironmentVariables</key><dict><key>PY</key><string>$PY</string></dict>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLISTEOF
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $LABEL: daily at 21:30, log at $LOG"
