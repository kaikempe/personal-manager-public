#!/bin/bash
# Phone endpoint for Siri: keeps scripts/phone_server.py running (127.0.0.1:8766) and creates its token.
#
#   ./scripts/install_phone.sh            install or update
#   ./scripts/install_phone.sh --token    print the token again (to paste into the shortcut)
#   ./scripts/install_phone.sh --remove   stop and remove
#
# The phone reaches it only through Tailscale (a private network you install and sign in to yourself):
#   1. Mac:    brew install --cask tailscale   (or the Mac App Store), open it, sign in.
#   2. iPhone: install Tailscale from the App Store, sign in with the same account.
#   3. Mac:    tailscale serve --bg 8766       → prints https://<mac-name>.<tailnet>.ts.net
#   4. iPhone shortcut "Ask Planner" (not "Ask Manager": Siri hears that as the Reminders list "Manager Inbox"):
#      Dictate Text → Get Contents of URL (POST https://<that address>/ask,
#      header Authorization: Bearer <token>, JSON body {"text": Dictated Text}) → Speak Text (Contents of URL).
set -euo pipefail

LABEL="$(python3 "$(dirname "$0")/pm_env.py" PM_LABEL_PREFIX).phone"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/personal-manager-phone.log"
TOKEN="$ROOT/data/phone_token"
PY="$(command -v python3)"

if [ "${1:-}" = "--token" ]; then cat "$TOKEN"; echo; exit 0; fi

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
if [ "${1:-}" = "--remove" ]; then
  rm -f "$PLIST"
  echo "removed $LABEL (token kept in $TOKEN)"
  exit 0
fi

mkdir -p "$ROOT/data" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
if [ ! -s "$TOKEN" ]; then
  (umask 077; "$PY" -c "import secrets; print(secrets.token_urlsafe(32))" > "$TOKEN")
  echo "new token in $TOKEN"
fi
chmod 600 "$TOKEN"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>$ROOT/scripts/phone_server.py</string></array>
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
echo "installed $LABEL (log $LOG). Next: Tailscale and the shortcut, see the top of this script."
