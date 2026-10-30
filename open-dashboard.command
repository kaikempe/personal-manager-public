#!/bin/zsh
# Starts the dashboard server if it is not running, then opens it in the browser.
cd "$(dirname "$0")" || exit 1
URL=http://127.0.0.1:8765
if ! curl -s -o /dev/null "$URL"; then
  nohup python3 dashboard/server.py >> /tmp/personal-manager-dashboard.log 2>&1 &
  for _ in {1..20}; do curl -s -o /dev/null "$URL" && break; sleep 0.25; done
fi
open "$URL"
