#!/usr/bin/env python3
"""Read the Obsidian note "05 Areas/Gym.md" and publish plan.json for the phone app.

    python3 scripts/gym_plan_sync.py --dry-run   # print what would be written
    python3 scripts/gym_plan_sync.py             # write gym/plan.json (+ history.json)

The note has one "## Day N: ..." heading per day, each followed by a Markdown table
(Exercise | Sets x Reps | Weight). The parse is deterministic; if the note stops matching that
shape the previous plan.json is kept and the problem is printed. Read-only: the vault is never written here.

gym/ is a symlink to the iCloud folder "Manager Gym" (see scripts/install_gym.sh).
plan.json also carries the next weeks' gym dates from add_gym.plan() so the phone knows which
day it is training, including the Monday-off weeks.
"""
import json
import os
import sys as _sys
from pathlib import Path as _P
for _d in (_P(__file__).resolve().parent, _P(__file__).resolve().parent.parent / "scripts"):
    if (_d / "pm_env.py").exists():
        _sys.path.insert(0, str(_d))
import pm_env  # noqa: E402,F401  (loads config.env)
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
GYM = ROOT / "gym"
NOTE = Path(os.environ.get("VAULT_DIR") or Path.home() / "Documents/Vault") / "05 Areas/Gym.md"


def note_body():
    try:
        return NOTE.read_text()
    except OSError as e:
        sys.exit(f"cannot read {NOTE}: {e}")


def parse(body):
    days, current = {}, None
    for line in body.splitlines():
        head = re.match(r"##\s+Day (\d+):\s*(.+?)\s*$", line)
        if head:
            current = f"Day {head.group(1)}"
            days[current] = {"title": head.group(2), "exercises": []}
            continue
        if current is None or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] == "Exercise" or set(cells[0]) <= set("-: "):
            continue
        name, sr, weight = cells[:3]
        sets = re.match(r"(\d+)\s*x\s*(.+)$", sr)
        w = re.match(r"(\d+(?:\.\d+)?)\s*kg(?:\s*(.*))?$", weight)
        days[current]["exercises"].append({
            "name": name,
            "sets": int(sets.group(1)) if sets else None,
            "reps": sets.group(2).strip() if sets else sr,
            "weight": float(w.group(1)) if w else None,
            "weight_note": (w.group(2) or "").strip("() ") if w else weight,
        })
    return days


def schedule():
    import add_gym
    events, _, generated = add_gym.plan()
    return [{"date": e["start"].strftime("%Y-%m-%d"), "start": e["start"].strftime("%H:%M"),
             "end": e["end"].strftime("%H:%M"), "day": f'Day {e["day"]}'} for e in events], generated


def main():
    dry = "--dry-run" in sys.argv
    days = parse(note_body())
    bad = [d for d, v in days.items() if not v["exercises"]]
    if len(days) < 1 or bad:
        sys.exit(f"note did not parse as expected (days={list(days)}, empty={bad}); plan.json not touched")
    sched, generated = schedule()
    out = {"days": days, "schedule": sched, "calendar_export": generated}
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    if dry:
        print(text)
        return
    if not GYM.exists():
        sys.exit("gym/ missing: run scripts/install_gym.sh first")
    (GYM / "plan.json").write_text(text)
    print(f"wrote {GYM / 'plan.json'}: {sum(len(v['exercises']) for v in days.values())} exercises, {len(sched)} sessions")


if __name__ == "__main__":
    main()
