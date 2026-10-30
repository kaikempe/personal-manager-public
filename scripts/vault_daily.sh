#!/bin/bash
# Daily vault upkeep, run by the LaunchAgent com.personal-manager.vault (scripts/install_vault.sh):
#   1. scripts/vault_sync.py: registry status, BB Tracker course facts and tech-hub links into the vault
#   2. the vault's _Meta/vault_check.py: anything it flags is logged (and shown as a notification)
#   3. commit every change to the vault's git history (~/Developer/vault-git/vault.git, never pushed)
# Log: ~/Library/Logs/personal-manager-vault.log. launchd has a minimal PATH, so every tool is absolute.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VAULT="${VAULT_DIR:-$HOME/Documents/Vault}"
PY="${PY:-/usr/bin/python3}"
GIT=/usr/bin/git

echo "== $(date '+%F %T')"
"$PY" "$ROOT/scripts/vault_sync.py"
flags="$("$PY" "$VAULT/_Meta/vault_check.py" | grep -v -e ': 0$' -e '^notes:')"
if [ -n "$flags" ]; then
  echo "$flags"
  /usr/bin/osascript -e 'display notification "vault_check.py flagged something; see ~/Library/Logs/personal-manager-vault.log" with title "Vault check"' || true
fi
"$GIT" -C "$VAULT" add -A
if ! "$GIT" -C "$VAULT" diff --cached --quiet; then
  "$GIT" -C "$VAULT" commit -q -m "Daily snapshot $(date +%F): vault_sync and edits since the last commit" && echo "committed"
fi
