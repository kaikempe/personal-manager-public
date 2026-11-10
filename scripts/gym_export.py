#!/usr/bin/env python3
"""Read data/gym_log.jsonl: Gemini text, CSV, and the summary the dashboard shows.

    python3 scripts/gym_export.py            # Gemini text (same format as the phone app's "Copy for Gemini")
    python3 scripts/gym_export.py --csv
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pm_env  # noqa: E402

LOG = pm_env.DATA / "data/gym_log.jsonl"


def load():
    """One entry per workout: files for the same date and day (e.g. an exercise logged afterwards) are merged."""
    if not LOG.exists():
        return []
    raw = sorted((json.loads(l) for l in LOG.read_text().splitlines() if l.strip()), key=lambda s: (s["date"], s.get("started", "")))
    merged = {}
    for s in raw:
        m = merged.setdefault((s["date"], s.get("day", "")), {**s, "exercises": []})
        for ex in s["exercises"]:
            same = next((x for x in m["exercises"] if x["name"] == ex["name"]), None)
            if same:
                same["sets"] = same["sets"] + ex["sets"]
                same["skipped"] = same.get("skipped") and ex.get("skipped")
            else:
                m["exercises"].append({**ex})
        m["note"] = m.get("note") or s.get("note")
        m["feel"] = m.get("feel") or s.get("feel")
    return list(merged.values())


def e1rm(s):  # Epley; bodyweight sets rank by reps
    return s["w"] * (1 + s["reps"] / 30) if s.get("w") else s["reps"]


def num(w):
    return "BW" if w is None else f"{w:g}"


def per_exercise(log):
    out = {}
    for s in log:
        for ex in s["exercises"]:
            out.setdefault(ex["name"], []).append({"date": s["date"], "day": s.get("day", ""), "skipped": bool(ex.get("skipped")) or not ex["sets"], "sets": ex["sets"]})
    return out


def gemini_text(log=None):  # keep identical to geminiText() in app/gym/index.html
    lines = ["My gym log (weight kg × reps), newest first, last 8 sessions per exercise. Compare my progress per exercise and say where I should add weight or reps."]
    for name, rows in sorted(per_exercise(load() if log is None else log).items()):
        done = [r for r in reversed(rows) if r["sets"]][:8]
        if done:
            lines.append(f"{name}: " + " | ".join(f'{r["date"]} ' + ", ".join(f'{num(x.get("w"))}x{x["reps"]}' for x in r["sets"]) for r in done))
    return "\n".join(lines)


def csv_text(log=None):
    rows = ["date,exercise,set,weight,reps"]
    for name, sess in per_exercise(load() if log is None else log).items():
        for r in sess:
            rows += [f'{r["date"]},"{name}",{i},{"" if x.get("w") is None else num(x["w"])},{x["reps"]}' for i, x in enumerate(r["sets"], 1)]
    return "\n".join([rows[0]] + sorted(rows[1:]))


def summary():
    log = load()
    exs = []
    for name, rows in per_exercise(log).items():
        done = [r for r in rows if r["sets"]]
        series = [round(max(e1rm(x) for x in r["sets"]), 1) for r in done]
        top = max((x for r in done for x in r["sets"]), key=e1rm, default=None)
        hist = [{"date": r["date"], "day": r["day"], "sets": [[x.get("w"), x["reps"]] for x in r["sets"]],
                 "strength": round(max(e1rm(x) for x in r["sets"]), 1),
                 "volume": round(sum((x.get("w") or 0) * x["reps"] for x in r["sets"]))} for r in done]
        exs.append({"name": name, "history": hist, "sessions": len(done), "skipped": sum(r["skipped"] for r in rows), "series": series[-12:],
                    "latest": series[-1] if series else None, "best": max(series, default=None),
                    "best_set": f'{num(top.get("w"))}x{top["reps"]}' if top else None})
    weeks = {}
    for s in log:
        y, w, _ = __import__("datetime").date.fromisoformat(s["date"]).isocalendar()
        weeks[f"{y}-W{w:02d}"] = weeks.get(f"{y}-W{w:02d}", 0) + 1
    return {"sessions": len(log), "last": log[-1]["date"] if log else None, "weeks": weeks,
            "exercises": sorted(exs, key=lambda e: e["name"])}


if __name__ == "__main__":
    print(csv_text() if "--csv" in sys.argv else gemini_text())
