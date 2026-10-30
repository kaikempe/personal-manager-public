#!/usr/bin/env python3
"""Merge finished workouts from the phone into data/gym_log.jsonl, then refresh what the phone reads.

    python3 scripts/gym_ingest.py

The phone app saves one file per workout to gym/sessions/<id>.json (iCloud "Manager Gym").
Each file is validated and appended to data/gym_log.jsonl, deduplicated by `id`, then moved to
gym/sessions/done/. Invalid files go to gym/sessions/rejected/ with the reason in <id>.err.
Nothing is deleted. After that history.json (for "last time" in the app) and plan.json are rewritten.

Session: {id, date, day, started, ended, feel (1-5, optional), note (optional), exercises:[{name, skipped, sets:[{w, reps, same}]}]}
"""
import fcntl
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gym_load  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GYM = ROOT / "gym"
SESSIONS = GYM / "sessions"
LOG = ROOT / "data/gym_log.jsonl"
KEEP = 8  # sessions per exercise shipped to the phone


def read_log():
    if not LOG.exists():
        return []
    return [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]


def validate(s):
    if not isinstance(s, dict) or not isinstance(s.get("id"), str) or not re.fullmatch(r"[\w.-]{4,80}", s["id"]):
        return "bad id"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s.get("date", ""))):
        return "bad date"
    if not isinstance(s.get("exercises"), list) or not s["exercises"]:
        return "no exercises"
    if "feel" in s and not (isinstance(s["feel"], int) and not isinstance(s["feel"], bool) and 1 <= s["feel"] <= 5):
        return "bad feel"
    if "note" in s and not (isinstance(s["note"], str) and len(s["note"]) <= 300):
        return "bad note"
    for ex in s["exercises"]:
        if not isinstance(ex.get("name"), str) or not isinstance(ex.get("sets"), list):
            return "bad exercise"
        for st in ex["sets"]:
            if not isinstance(st.get("reps"), int) or not (st.get("w") is None or isinstance(st["w"], (int, float))):
                return f'bad set in {ex["name"]}'
    return None


def history(log):
    """exercise name -> newest-first list of {date, day, skipped, sets:[{w, reps}], pos, of}. pos/of: place in a session of 4+ exercises; prior/via: set-equivalents on the same muscles done earlier (gym_load)."""
    out = {}
    for s in sorted(log, key=lambda s: (s["date"], s.get("started", "")), reverse=True):
        n = len(s["exercises"])
        for i, ex in enumerate(s["exercises"]):
            rows = out.setdefault(ex["name"], [])
            if len(rows) < KEEP:
                row = {"id": s["id"], "date": s["date"], "day": s.get("day"), "skipped": bool(ex.get("skipped")),
                       "sets": [{"w": x.get("w"), "reps": x["reps"]} for x in ex["sets"]]}
                if n >= 4:   # when in the workout it was done (the saved order is the order trained); partial imports have no real position
                    row["pos"], row["of"] = i + 1, n
                    p = gym_load.prior(s, i)   # work on the same muscles earlier in the session
                    row["prior"], row["via"] = p["prior"], p["via"]
                rows.append(row)
    return out


def is_duplicate(s, log):
    """Same workout arriving under another id (for example re-sent after a hand import): every exercise is
    already logged on that date with identical sets."""
    key = lambda e: (e["name"], [(x.get("w"), x["reps"]) for x in e["sets"]])
    same_day = [key(e) for o in log if o["date"] == s["date"] for e in o["exercises"]]
    return all(key(e) in same_day for e in s["exercises"] if e["sets"])


def ingest():
    log = read_log()
    seen = {s["id"] for s in log}
    new = 0
    for sub in ("done", "rejected"):
        (SESSIONS / sub).mkdir(exist_ok=True)
    for f in sorted(SESSIONS.glob("*.json")):
        try:
            s = json.loads(f.read_text())
            err = validate(s)
        except (ValueError, OSError) as e:  # iCloud may still be writing it: try again next run
            if isinstance(e, ValueError) and f.stat().st_size > 0:
                err = f"not JSON: {e}"
            else:
                continue
        if err:
            shutil.move(f, SESSIONS / "rejected" / f.name)
            (SESSIONS / "rejected" / (f.name + ".err")).write_text(err + "\n")
            print(f"rejected {f.name}: {err}")
            continue
        if s["id"] not in seen and not is_duplicate(s, log):
            with LOG.open("a") as fh:
                fh.write(json.dumps(s, ensure_ascii=False) + "\n")
            seen.add(s["id"])
            log.append(s)
            new += 1
        shutil.move(f, SESSIONS / "done" / f.name)
    return log, new


def main():
    if not GYM.exists():
        sys.exit("gym/ missing: run scripts/install_gym.sh first")
    SESSIONS.mkdir(exist_ok=True)
    LOG.parent.mkdir(exist_ok=True)
    import gym_pull  # workouts posted by the phone to the Netlify inbox land in sessions/ first
    gym_pull.main()
    with open(ROOT / "data/.gym_ingest.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        log, new = ingest()
        (GYM / "history.json").write_text(json.dumps(history(log), indent=2, ensure_ascii=False) + "\n")
        if LOG.exists():  # the iCloud copy is the backup: data/ is not in git
            (GYM / "backup").mkdir(exist_ok=True)
            shutil.copyfile(LOG, GYM / "backup" / f"gym_log-{datetime.now():%Y-%m}.jsonl")
        print(f"{datetime.now():%F %T} ingested {new} new, {len(log)} total")
    try:  # keep plan.json fresh; a Notes/Calendar hiccup must not stop the ingest
        import gym_plan_sync
        sys.argv = sys.argv[:1]
        gym_plan_sync.main()
    except SystemExit as e:
        print("plan sync:", e)
    try:  # review new sessions (and the week, Sunday evening); never let it break the ingest
        import gym_review
        sys.argv = sys.argv[:1]
        gym_review.main()
    except Exception as e:  # noqa: BLE001
        print("review:", e)
    gym_pull.main_push()  # plan.json and history.json are final now: publish them to the app if they changed


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
