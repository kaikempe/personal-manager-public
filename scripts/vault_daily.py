#!/usr/bin/env python3
"""Daily vault upkeep, run by the LaunchAgent <prefix>.vault (scripts/install_vault.sh):
  1. scripts/vault_sync.py: registry status, BB Tracker course facts and tech-hub links into the vault
  2. the vault's own _Meta/vault_check.py, if it has one: anything it flags is logged and shown as a notification
  2b. scripts/gemini_audit.py: what changed in the folders Gemini can write to since the last snapshot, checked
      against the vault rules (before the commit, so a flagged change is still visible as uncommitted)
  3. if the vault is a git repository: commit every change (never pushed)
Log: ~/Library/Logs/personal-manager-vault.log.

Python, not bash, on purpose. macOS lets only programs the user has allowed read iCloud Drive, where the vault
lives. Homebrew's python3 has that permission; /usr/bin/git and /bin/bash do not. Run by launchd from a bash
script, every git call failed with "Unable to read current working directory: Operation not permitted"
(2026-10-30 to 2026-11-04, no snapshot committed). Started as children of this python process, git runs under
its permission. A Homebrew upgrade to a new python path can lose the permission again, so any failing step
posts a notification instead of failing silently.
"""
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pm_env  # noqa: E402

VAULT = pm_env.VAULT
GIT = "/usr/bin/git"


def notify(title, text):
    script = f"display notification {text!r} with title {title!r}".replace("'", '"')
    subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True)


def run(cmd):
    """Run one step, echo its output into the log, return (exit code, stdout)."""
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.stdout:
        print(r.stdout, end="" if r.stdout.endswith("\n") else "\n")
    if r.stderr:
        print(r.stderr, end="" if r.stderr.endswith("\n") else "\n")
    return r.returncode, r.stdout


def main():
    print(f"== {datetime.now():%F %T}", flush=True)
    failed = []

    code, _ = run([sys.executable, str(ROOT / "scripts/vault_sync.py")])
    if code:
        failed.append(f"vault_sync.py exit {code}")

    if (VAULT / "_Meta/vault_check.py").exists():
        r = subprocess.run([sys.executable, str(VAULT / "_Meta/vault_check.py")], capture_output=True, text=True)
        flags = [l for l in r.stdout.splitlines() if l.strip() and not l.endswith(": 0") and not l.startswith("notes:")]
        if r.returncode:
            failed.append(f"vault_check.py exit {r.returncode}")
            print(r.stderr, end="")
        if flags:
            print("\n".join(flags))
            notify("Vault check", "vault_check.py flagged something; see ~/Library/Logs/personal-manager-vault.log")

    if (ROOT / "scripts/gemini_audit.py").exists():   # optional private add-on
        code, out = run([sys.executable, str(ROOT / "scripts/gemini_audit.py")])
        if code:
            notify("Gemini audit", "Gemini changed something the vault rules forbid; see data/gemini_audit.json "
                                   "and ~/Library/Logs/personal-manager-vault.log")

    if not (VAULT / ".git").exists():   # a failing git call on a real repo still counts as a failure below
        print("vault is not a git repository: no snapshot")
        return finish(failed)
    code, _ = run([GIT, "-C", str(VAULT), "add", "-A"])
    if code:
        failed.append(f"git add exit {code}")
    else:
        staged = subprocess.run([GIT, "-C", str(VAULT), "diff", "--cached", "--quiet"]).returncode
        if staged == 1:
            code, _ = run([GIT, "-C", str(VAULT), "commit", "-q", "-m",
                           f"Daily snapshot {date.today():%F}: vault_sync and edits since the last commit"])
            if code:
                failed.append(f"git commit exit {code}")
            else:
                print("committed")
        elif staged != 0:
            failed.append(f"git diff exit {staged}")

    return finish(failed)


def finish(failed):
    if failed:
        print("FAILED: " + "; ".join(failed))
        notify("Vault job failed", "; ".join(failed) + ". See ~/Library/Logs/personal-manager-vault.log")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
