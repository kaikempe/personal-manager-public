#!/usr/bin/env python3
"""Health of the personal manager: is every background job alive and is its data fresh?

    python3 scripts/health.py          # one line per check; exit 1 if anything is an error
    python3 scripts/health.py --json

The dashboard's System page shows the same checks (`checks()`). Read-only: it looks at launchctl, the status files
the jobs write and their logs. It changes nothing. Levels: ok, warn (look at it soon), error (something is broken).
"""
import json
import re
import socket
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pm_env  # noqa: E402

DATA = pm_env.DATA / "data"
STATE_MD = pm_env.DATA / "state.md"
LOGS = Path.home() / "Library/Logs"
AGENTS = Path.home() / "Library/LaunchAgents"
BB_DATA = pm_env.BB_DATA
PHONE_PORT = int(pm_env.get("PM_PHONE_PORT", "8766"))
P = pm_env.LABEL_PREFIX

# label -> (what it does, log file). KeepAlive jobs (dashboard, phone) run all the time; the others fire on a timer.
JOBS = {
    f"{P}.calendar-export": ("Calendar export (every 15 min)", None),
    f"{P}.mail-suggest": ("Mail suggestions (hourly)", "mail-suggest.log"),
    f"{P}.inbox": ("Inbox processing (every 5 min)", "personal-manager-inbox.log"),
    f"{P}.state": ("state.md refresh (hourly)", "personal-manager-state.log"),
    f"{P}.gym": ("Gym sync (every 15 min)", "personal-manager-gym.log"),
    f"{P}.vault": ("Vault sync (daily 21:30)", "personal-manager-vault.log"),
    f"{P}.dashboard": ("Dashboard server", "personal-manager-dashboard.log"),
    f"{P}.phone": ("Phone endpoint (Siri)", "personal-manager-phone.log"),
}
KEEPALIVE = {f"{P}.dashboard", f"{P}.phone"}
# A job that is not installed is an error only when config.env lists it in PM_REQUIRED_JOBS; the rest are optional.
REQUIRED = {f"{P}.{j}" for j in pm_env.get_list("PM_REQUIRED_JOBS", pm_env.DEFAULTS["PM_REQUIRED_JOBS"])}


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def parse_time(s):
    if not s:
        return None
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.astimezone()


def age(t, now):
    return (now - t).total_seconds() / 60 if t else None


def ago(minutes):
    if minutes is None:
        return "never"
    if minutes < 90:
        return f"{round(minutes)} min ago"
    if minutes < 48 * 60:
        return f"{round(minutes / 60)} h ago"
    return f"{round(minutes / 1440)} days ago"


def launchctl():
    """label -> (pid or None, last exit status or None) for every loaded job."""
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    jobs = {}
    for line in out.splitlines()[1:]:
        p = line.split("\t")
        if len(p) == 3:
            jobs[p[2]] = (None if p[0] == "-" else int(p[0]), None if p[1] == "-" else int(p[1]))
    return jobs


def job_checks(loaded):
    out = []
    for label, (what, log) in JOBS.items():
        installed = (AGENTS / f"{label}.plist").exists()
        if not installed:
            if label in REQUIRED:
                out.append(("error", what, f"not installed ({label}.plist missing)"))
            continue
        if label not in loaded:
            out.append(("error", what, "installed but not loaded in launchd"))
            continue
        pid, status = loaded[label]
        if label in KEEPALIVE:
            # -15 is SIGTERM from a restart (launchctl kickstart -k); launchd starts it again at once.
            if pid is None:
                out.append(("error", what, f"not running (last exit {status})"))
            else:
                out.append(("ok", what, f"running (pid {pid})"))
        elif status not in (0, None):
            tail = ""
            if log and (LOGS / log).exists():
                lines = [l for l in (LOGS / log).read_text(errors="replace").splitlines() if l.strip()]
                tail = f": {lines[-1][:120]}" if lines else ""
            out.append(("warn", what, f"last run exited with {status}{tail}"))
        else:
            out.append(("ok", what, "last run exited cleanly" if pid is None else f"running now (pid {pid})"))
    return out


def data_checks(now):
    out = []
    # Calendar: the planning rules refuse to plan silently from a calendar older than 60 minutes.
    st = read_json(DATA / "export_status.json", {})
    gen = parse_time((read_json(DATA / "calendar.json", {}) or {}).get("generated_at"))
    m = age(gen, now)
    if not st.get("ok", False):
        out.append(("error", "Calendar data", f"last export failed: {st.get('error') or 'unknown error'}"))
    elif m is None or m > 60:
        out.append(("error", "Calendar data", f"calendar.json generated {ago(m)} (stale after 60 min)"))
    else:
        out.append(("ok", "Calendar data", f"generated {ago(m)}, {st.get('events', '?')} events"))

    # Mail: a run counts only when it really read mail (the hourly no-ops do not touch the status file).
    ms = read_json(DATA / "mail_status.json", {})
    m = age(parse_time(ms.get("last_ok")), now)
    if not ms and not (AGENTS / f"{P}.mail-suggest.plist").exists():
        pass   # mail suggestions are optional and not set up
    elif ms and not ms.get("ok", True) and re.search(r"\b(usage|session|\d+-hour) limit\b", str(ms.get("error")), re.I):
        # The model's usage limit, not a fault: unseen mails are retried every hour until it resets.
        out.append(("warn", "Mail check", f"paused by the model's usage limit, retried hourly ({str(ms.get('error'))[:80]})"))
    elif ms and not ms.get("ok", True):
        out.append(("error", "Mail check", f"last run failed: {ms.get('error')}"))
    elif ms.get("offline_at"):
        out.append(("warn", "Mail check", f"offline since {ms['offline_at'][11:16]}; last good run {ago(m)}"))
    elif m is None or m > 180:
        out.append(("warn", "Mail check", f"last good run {ago(m)}"))
    else:
        out.append(("ok", "Mail check", f"last good run {ago(m)}: {ms.get('new_mail', 0)} new, {ms.get('picked', 0)} read, "
                                        f"{ms.get('proposed', 0)} suggested"))
    skipped = (read_json(DATA / "mail_skipped.json", {"mails": []}) or {}).get("mails", [])
    if skipped:
        out.append(("ok", "Mails not read", f"{len(skipped)} passed over in 14 days; listed on Suggestions"))

    m = age(parse_time((read_json(DATA / "state_refresh.json", {}) or {}).get("ran_at")), now)
    if m is not None or (AGENTS / f"{P}.state.plist").exists():
        out.append(("ok" if m is not None and m <= 150 else "warn", "state.md auto block", f"refreshed {ago(m)}"))

    rev = re.search(r"^Last reviewed:\s*(\d{4}-\d{2}-\d{2})", STATE_MD.read_text(), re.M) if STATE_MD.exists() else None
    if rev:
        days = (now.date() - datetime.fromisoformat(rev.group(1)).date()).days
        out.append(("warn" if days > 7 else "ok", "Weekly review", f"last {rev.group(1)} ({days} days ago)"))
    else:
        out.append(("warn", "Weekly review", "no 'Last reviewed:' line in state.md"))

    bb = read_json(BB_DATA, None)
    if bb is None:
        if BB_DATA.exists():   # BB Tracker is optional: silent when it is not installed
            out.append(("warn", "BB Tracker data", "data.json not readable"))
    else:
        m = age(parse_time(bb.get("timestamp")), now)
        if bb.get("error"):
            out.append(("warn", "BB Tracker data", f"error: {str(bb['error'])[:120]}"))
        else:
            out.append(("ok" if m is not None and m <= 24 * 60 else "warn", "BB Tracker data", f"updated {ago(m)}"))

    for name, job, log, limit in (("Gym sync", "gym", "personal-manager-gym.log", 60),
                                  ("Vault sync", "vault", "personal-manager-vault.log", 26 * 60)):
        if not (AGENTS / f"{P}.{job}.plist").exists():
            continue   # optional job, not installed
        p = LOGS / log
        m = age(datetime.fromtimestamp(p.stat().st_mtime).astimezone(), now) if p.exists() else None
        out.append(("ok" if m is not None and m <= limit else "warn", name, f"log written {ago(m)}"))

    gp = read_json(DATA / "gym_proposals.json", {}) or {}
    open_gp = [p for p in gp.get("proposals", []) if p.get("status") == "pending"] if isinstance(gp, dict) else []
    if open_gp:
        out.append(("ok", "Gym proposals", f"{len(open_gp)} weight change(s) waiting on the Gym page and in the phone app"))
    return out


def plugin_checks():
    """Rows from plugins that define CHECKS() -> [(level, name, detail)] (plugins/README.md). A plugin that fails
    is one warning row, never a crash."""
    if pm_env.DEMO:
        return []
    try:
        import plugins_load
        hooks = plugins_load.each("CHECKS")
    except Exception as e:  # noqa: BLE001
        return [("warn", "Plugins", f"could not load: {str(e)[:120]}")]
    out = []
    for mod, fn in hooks:
        try:
            out += [(str(lv), str(n), str(d)) for lv, n, d in fn() if lv in ("ok", "warn", "error")]
        except Exception as e:  # noqa: BLE001
            out.append(("warn", f"Plugin {mod.__name__.replace('pm_plugin_', '')}", f"check failed: {str(e)[:120]}"))
    return out


def phone_checks():
    if not (AGENTS / f"{P}.phone.plist").exists():
        return []
    out = []
    try:
        socket.create_connection(("127.0.0.1", PHONE_PORT), timeout=1).close()
        out.append(("ok", "Phone endpoint port", f"listening on 127.0.0.1:{PHONE_PORT}"))
    except OSError:
        out.append(("error", "Phone endpoint port", f"nothing listening on 127.0.0.1:{PHONE_PORT}"))
    ts = next((p for p in ("/usr/local/bin/tailscale", "/opt/homebrew/bin/tailscale",
                           "/Applications/Tailscale.app/Contents/MacOS/Tailscale") if Path(p).exists()), None)
    if not ts:
        out.append(("warn", "Tailscale", "not installed: Siri cannot reach the Mac (see scripts/install_phone.sh)"))
    else:
        try:
            r = subprocess.run([ts, "serve", "status"], capture_output=True, text=True, timeout=8)
            served = str(PHONE_PORT) in r.stdout
            out.append(("ok" if served else "warn", "Tailscale", "serving the phone endpoint" if served else
                        f"installed, but not serving port {PHONE_PORT} (run: tailscale serve --bg {PHONE_PORT})"))
        except (OSError, subprocess.TimeoutExpired):
            out.append(("warn", "Tailscale", "installed, status unknown"))
    return out


def checks(now=None):
    now = now or datetime.now().astimezone()
    rows = job_checks(launchctl()) + data_checks(now) + phone_checks() + plugin_checks()
    return [{"level": lv, "name": n, "detail": d} for lv, n, d in rows]


def main():
    rows = checks()
    if "--json" in sys.argv:
        print(json.dumps(rows, indent=1))
    else:
        mark = {"ok": "  ok ", "warn": " WARN", "error": "ERROR"}
        for r in rows:
            print(f'{mark[r["level"]]}  {r["name"]:28} {r["detail"]}')
    return 1 if any(r["level"] == "error" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
