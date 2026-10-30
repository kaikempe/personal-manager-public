#!/usr/bin/env python3
"""How much work on the same muscles came BEFORE an exercise in one session (tags: scripts/gym_muscles.json).

    python3 scripts/gym_load.py            # prior load of every exercise in the latest session

prior(session, i) -> {"prior": set-equivalents, "via": [muscles that overlapped, biggest first]}. Only for sessions of 4+
exercises (a partial import has no real order). Used by gym_ingest (shipped to the phone) and gym_review (fatigue rule).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((Path(__file__).parent / "gym_muscles.json").read_text())
THRESHOLD = CFG["fatigue_threshold"]


def _weights(a, b):
    """-> {muscle: overlap weight} between the tags of exercise a (earlier) and b (this one)."""
    W, out = CFG["overlap"], {}
    for m in set(a["primary"]) | set(a["secondary"]):
        ap, bp = m in a["primary"], m in b["primary"]
        if m not in b["primary"] and m not in b["secondary"]:
            continue
        out[m] = W["pp"] if ap and bp else W["ps"] if ap or bp else W["ss"]
    return out


def prior(session, i):
    exs = session["exercises"]
    if len(exs) < 4:
        return None
    tags = CFG["exercises"]
    me = tags.get(exs[i]["name"])
    if not me:
        return {"prior": 0, "via": []}
    total, by_m = 0.0, {}
    for e in exs[:i]:
        t = tags.get(e["name"])
        if not t or e.get("skipped"):
            continue
        sets = len(e["sets"])
        for m, w in _weights(t, me).items():
            by_m[m] = by_m.get(m, 0) + sets * w
            total += sets * w
    return {"prior": round(total, 1), "via": [m for m, _ in sorted(by_m.items(), key=lambda x: -x[1])][:3]}


def fatigued(p):
    return bool(p) and p["prior"] >= THRESHOLD


if __name__ == "__main__":
    log = [json.loads(l) for l in (ROOT / "data/gym_log.jsonl").read_text().splitlines() if l.strip()]
    log = [s for s in log if len(s["exercises"]) >= 4]
    s = max(log, key=lambda s: (s["date"], s.get("started", "")))
    print(s["date"], s.get("day"))
    for i, e in enumerate(s["exercises"]):
        p = prior(s, i)
        print(f'  {i + 1}. {e["name"]:36} prior {p["prior"]:>4}  {", ".join(p["via"])}{"  <- fatigued" if fatigued(p) else ""}')
