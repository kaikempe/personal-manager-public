#!/usr/bin/env python3
"""Review gym sessions: what was done, what was skipped, what to change next time.

    python3 scripts/gym_review.py             # what the ingest job does: review a new session, Sunday evening the week
    python3 scripts/gym_review.py --session   # review the latest session now
    python3 scripts/gym_review.py --weekly    # weekly review now
    python3 scripts/gym_review.py --apply ID  # accept a weight proposal: edits one cell in the Obsidian Gym.md
    python3 scripts/gym_review.py --dismiss ID
    add --no-llm to skip the wording pass (the numbers never come from the model)

Rules (double progression), applied to the exercise's last logged sessions against the plan's rep range:
  - every planned set at the same weight, all at the top of the range -> propose +1 step
  - a set under the bottom of the range in two sessions in a row     -> suggest holding or dropping a step
  - same top weight and no more reps for three sessions              -> flag as stuck
  - skipped in 3 of the last 4 sessions of that day                  -> flag
A session the user rated 1 or 2 ("how did you feel", saved with the workout) is a low day: its missed reps never count
as a stall or as "under the range", and the note says so instead. The same holds for an exercise done after
enough work on the same muscles earlier in that session (scripts/gym_load.py, tags in gym_muscles.json: prior load >= the
threshold; the saved order is the order trained): fatigue, not weight.
Only the +1 step is a proposal the user can accept; it changes the weight in Gym.md and nothing else.
Needs about 3 sessions per day before "stuck" means anything. Results: data/gym_review.json,
data/gym_proposals.json. A macOS notification is posted when a review is written.
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
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import gym_export  # noqa: E402
import gym_load  # noqa: E402

PLAN = ROOT / "gym/plan.json"
REVIEW = ROOT / "data/gym_review.json"
PROPOSALS = ROOT / "data/gym_proposals.json"
STATE = ROOT / "data/gym_review_state.json"
GYM_MD = Path(os.environ.get("VAULT_DIR") or Path.home() / "Documents/Vault") / "05 Areas/Gym.md"
CLAUDE = os.environ.get("CLAUDE_BIN") or str(Path.home() / ".local/bin/claude")


def read(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write(path, obj):
    path = Path(path)
    path.parent.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as f:
        f.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    os.replace(f.name, path)


def rep_range(reps):
    """'6–8' -> (6, 8); '12–15+' -> (12, 15); '15' -> (15, 15); 'Max' -> None."""
    n = [int(x) for x in re.findall(r"\d+", str(reps))]
    return (n[0], n[-1]) if n else None


DUMBBELL = re.compile(r"\b(db|dumbbell|hammer|zottman|forearm|reverse curls|lateral raises|bulgarian|pronation|leg curls)", re.I)


def step(name, w):
    """kg per step, the same rules as the phone app: leg press 5, cable and barbell/machines 2.5, dumbbells 2."""
    if re.search(r"leg press", name, re.I):
        return 5
    if re.search(r"cable|pulldown|pushdown", name, re.I):
        return 2.5
    return 2 if DUMBBELL.search(name) else 2.5


def fmt(w):
    return "BW" if w is None else f"{w:g}"


# ---------- analysis ----------
def plan_ex():
    days = read(PLAN, {}).get("days", {})
    return {(d, e["name"]): e for d, v in days.items() for e in v["exercises"]}


def history(log, day, name):
    """Chronological rows for one exercise on one day: {date, skipped, sets, low, fatigued, why}. `low` also covers `fatigued`."""
    rows = []
    for s in log:
        if s.get("day") != day:
            continue
        for i, ex in enumerate(s["exercises"]):
            if ex["name"] == name:
                p = gym_load.prior(s, i)
                ft = gym_load.fatigued(p)
                rows.append({"date": s["date"], "skipped": not ex["sets"], "sets": ex["sets"], "fatigued": ft,
                             "why": f"after {p['prior']:g} sets on {', '.join(p['via'])}" if ft else "",
                             "low": (s.get("feel") or 3) <= 2 or ft})
    return rows


def judge(day, name, rows, pe):
    """-> (note, proposal or None). `rows` ends with the session being reviewed."""
    done = [r for r in rows if r["sets"]]
    solid = [r for r in done if not r.get("low")]   # low-rated days never count towards a stall
    last4 = rows[-4:]
    if sum(r["skipped"] for r in last4) >= 3:
        return f"skipped in {sum(r['skipped'] for r in last4)} of the last {len(last4)} sessions: drop it from the plan or fix what stops you", None
    if not done or rows[-1]["skipped"]:
        return "skipped this time", None
    rr = rep_range(pe.get("reps")) if pe else None
    last = done[-1]["sets"]
    ws = {x.get("w") for x in last}
    top = max((x["w"] for x in last if x.get("w") is not None), default=None)
    planned = (pe or {}).get("sets") or len(last)
    if rr and top is not None and len(ws) == 1 and len(last) >= planned and all(x["reps"] >= rr[1] for x in last):
        to = round(top + step(name, top), 2)
        return f"all {len(last)} sets at {rr[1]}+ reps with {fmt(top)} kg: go to {fmt(to)} kg", {"from": top, "to": to, "reason": f"{len(last)}×{rr[1]}+ at {fmt(top)} kg"}
    if rows[-1].get("low") and rr and any(x["reps"] < rr[0] for x in last):
        why = rows[-1]["why"] if rows[-1].get("fatigued") else "low day"
        return f"{why}: not counted as a stall, repeat {fmt(max((x.get('w') for x in last), key=lambda w: (sum(y.get('w') == w for y in last), w or 0)))} kg", None
    if rr and len(solid) >= 2 and all(any(x["reps"] < rr[0] for x in r["sets"]) for r in solid[-2:]):
        w = top if top is not None else 0
        return f"under {rr[0]} reps in two sessions in a row at {fmt(w)} kg: hold the weight until you reach {rr[0]}, or drop to {fmt(max(0, w - step(name, w)))} kg", None
    if len(solid) >= 3 and top is not None:
        tops = [(max(x["w"] or 0 for x in r["sets"]), max(x["reps"] for x in r["sets"] if (x["w"] or 0) == max(y["w"] or 0 for y in r["sets"]))) for r in solid[-3:]]
        if len({t[0] for t in tops}) == 1 and tops[2][1] <= tops[0][1]:
            return f"stuck at {fmt(top)} kg for 3 sessions with no extra reps: change the rep target or add a set", None
    nxt = f"aim for {rr[0]}–{rr[1]} reps at {fmt(top)} kg" if rr and top is not None else "repeat"
    return nxt, None


def review_session(log, s):
    pe = plan_ex()
    day = s.get("day")
    prev_log = [x for x in log if (x["date"], x.get("started", "")) < (s["date"], s.get("started", ""))]
    exs, props, planned_total, done_total = [], [], 0, 0
    for ex in s["exercises"]:
        p = pe.get((day, ex["name"]))
        planned = (p or {}).get("sets") or len(ex["sets"])
        n = len(ex["sets"])
        planned_total += planned
        done_total += min(n, planned)
        rows = history(prev_log, day, ex["name"]) + [{"date": s["date"], "skipped": not n, "sets": ex["sets"], "low": (s.get("feel") or 3) <= 2}]
        note, prop = judge(day, ex["name"], rows, p)
        prev = [r for r in rows[:-1] if r["sets"]]
        cur = max((gym_export.e1rm(x) for x in ex["sets"]), default=None)
        old = [max(gym_export.e1rm(x) for x in r["sets"]) for r in prev]
        entry = {"name": ex["name"], "sets_done": n, "sets_planned": planned, "skipped": n == 0, "note": note,
                 "top": f'{fmt(max(ex["sets"], key=gym_export.e1rm).get("w"))}x{max(ex["sets"], key=gym_export.e1rm)["reps"]}' if n else None,
                 "pr": bool(cur and old and cur > max(old) + 0.05),
                 "change": round(cur - old[-1], 1) if cur and old else None}
        exs.append(entry)
        if prop:
            props.append({"day": day, "exercise": ex["name"], **prop})
    return {"kind": "session", "id": s["id"], "date": s["date"], "day": day, "sets_done": done_total, "sets_planned": planned_total,
            "skipped": [e["name"] for e in exs if e["skipped"]], "partial": [e["name"] for e in exs if not e["skipped"] and e["sets_done"] < e["sets_planned"]],
            "prs": [e["name"] for e in exs if e["pr"]], "exercises": exs,
            **({"feel": s["feel"]} if s.get("feel") else {}), **({"note": s["note"]} if s.get("note") else {})}, props


def review_week(log, today):
    monday = today - timedelta(days=today.weekday())
    week = [s for s in log if monday.isoformat() <= s["date"] <= today.isoformat()]
    cal = read(ROOT / "data/calendar.json", {"events": []})
    sched = sorted({e["start"][:10] for e in cal["events"]
                    if e.get("title", "").startswith("Gym") and monday.isoformat() <= e["start"][:10] <= today.isoformat()})
    logged = {s["date"] for s in week}
    month = [s for s in log if s["date"] >= (today - timedelta(days=28)).isoformat()]
    skips = {}
    for s in month:
        for ex in s["exercises"]:
            if not ex["sets"]:
                skips[ex["name"]] = skips.get(ex["name"], 0) + 1
    sess = [review_session(log, s)[0] for s in week]
    return {"kind": "weekly", "week_of": monday.isoformat(), "scheduled": len(sched), "logged": len(logged),
            "missed_dates": [d for d in sched if d not in logged and d < today.isoformat()],
            "sets_done": sum(r["sets_done"] for r in sess), "sets_planned": sum(r["sets_planned"] for r in sess),
            "prs": sorted({n for r in sess for n in r["prs"]}),
            "skipped_last_4_weeks": dict(sorted(skips.items(), key=lambda kv: -kv[1])), "sessions": [r["id"] for r in sess]}


def plain(r):
    if r["kind"] == "session":
        out = [f'{r["day"]} {r["date"]}: {r["sets_done"]}/{r["sets_planned"]} sets']
        if r["skipped"]:
            out.append("Skipped: " + ", ".join(r["skipped"]))
        if r["partial"]:
            out.append("Fewer sets than planned: " + ", ".join(r["partial"]))
        if r["prs"]:
            out.append("New best: " + ", ".join(r["prs"]))
        if r.get("feel") and (r["feel"] != 3 or r.get("note")):
            out.append(f'Felt {r["feel"]}/5' + (f': {r["note"]}' if r.get("note") else ""))
        out += [f'{e["name"]}: {e["note"]}' for e in r["exercises"] if not e["skipped"] and not e["note"].startswith("aim") and e["note"] != "repeat"]
        return "\n".join(out)
    out = [f'Week of {r["week_of"]}: {r["logged"]}/{r["scheduled"]} scheduled sessions logged, {r["sets_done"]}/{r["sets_planned"]} sets']
    if r["missed_dates"]:
        out.append("Not logged: " + ", ".join(r["missed_dates"]))
    if r["prs"]:
        out.append("New best: " + ", ".join(r["prs"]))
    sk = [f"{n} ({c}×)" for n, c in r["skipped_last_4_weeks"].items() if c >= 2]
    if sk:
        out.append("Skipped often (4 weeks): " + ", ".join(sk))
    return "\n".join(out)


def reword(r, text, use_llm):
    if not use_llm:
        return text
    prompt = ("You are the user's training log reviewer. Rewrite the facts below as at most 6 short plain lines: what he did, what he left out, "
              "what to change next time. Use only numbers and exercises that appear in the facts, invent nothing, no greeting, no emoji. "
              "Say it directly.\n\nFACTS (JSON):\n" + json.dumps(r, ensure_ascii=False) + "\n\nDETERMINISTIC SUMMARY:\n" + text)
    try:
        res = subprocess.run([CLAUDE, "-p", "--model", "sonnet"], input=prompt, capture_output=True, text=True, timeout=150)
        out = res.stdout.strip()
        return out if res.returncode == 0 and out else text
    except (OSError, subprocess.TimeoutExpired):
        return text


def notify(title, text):
    first = text.splitlines()[0] if text else ""
    subprocess.run(["osascript", "-e", f'display notification {json.dumps(first)} with title {json.dumps(title)}'], capture_output=True)


def store_proposals(day_props, session_id):
    data = read(PROPOSALS, {"proposals": []})
    keep = []
    for p in data["proposals"]:   # a newer session replaces an older pending proposal for the same exercise
        if p["status"] == "pending" and any(p["day"] == n["day"] and p["exercise"] == n["exercise"] for n in day_props):
            continue
        keep.append(p)
    for n in day_props:
        keep.append({"id": re.sub(r"\W+", "-", f'{n["day"]}-{n["exercise"]}-{n["to"]}').strip("-").lower(), **n,
                     "session": session_id, "status": "pending", "created": datetime.now().isoformat(timespec="seconds")})
    write(PROPOSALS, {"proposals": keep})


# ---------- accept / dismiss ----------
def set_status(pid, status):
    data = read(PROPOSALS, {"proposals": []})
    p = next((p for p in data["proposals"] if p["id"] == pid), None)
    if not p or p["status"] != "pending":
        raise ValueError("no such pending proposal")
    return data, p


def apply(pid):
    """Change one weight cell in Gym.md. Refuses if the note changed since the proposal."""
    data, p = set_status(pid, "applied")
    try:
        lines = GYM_MD.read_text().split("\n")
    except OSError as e:
        raise ValueError(f"cannot read Gym.md: {e}")
    day, hit = None, None
    for i, line in enumerate(lines):
        h = re.match(r"##\s+(Day \d+):", line)
        if h:
            day = h.group(1)
        elif day == p["day"] and line.startswith("|"):
            cells = line.strip().strip("|").split("|")
            if cells[0].strip() == p["exercise"]:
                hit = i
                break
    if hit is None:
        raise ValueError(f'{p["exercise"]} not found under {p["day"]} in Gym.md')
    cells = lines[hit].strip().strip("|").split("|")
    m = re.match(r"(\s*)(\d+(?:\.\d+)?)(\s*kg)", cells[2])
    if not m or float(m.group(2)) != p["from"]:
        raise ValueError(f'Gym.md says {cells[2].strip()} for {p["exercise"]}, not {fmt(p["from"])} kg: the plan changed, dismiss this one')
    cells[2] = m.group(1) + fmt(p["to"]) + m.group(3) + cells[2][m.end():]
    lines[hit] = "|" + "|".join(cells) + "|"
    tmp = GYM_MD.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lines))
    os.replace(tmp, GYM_MD)
    p["status"], p["handled"] = "applied", datetime.now().isoformat(timespec="seconds")
    write(PROPOSALS, data)
    try:
        import gym_plan_sync
        sys.argv = sys.argv[:1]
        gym_plan_sync.main()
    except SystemExit:
        pass


def dismiss(pid):
    data, p = set_status(pid, "dismissed")
    p["status"], p["handled"] = "dismissed", datetime.now().isoformat(timespec="seconds")
    write(PROPOSALS, data)


# ---------- driver ----------
def run_session(log, s, use_llm):
    r, props = review_session(log, s)
    r["text"] = reword(r, plain(r), use_llm)
    rev = read(REVIEW, {})
    rev["session"] = r
    write(REVIEW, rev)
    store_proposals(props, s["id"])
    notify(f'Gym review: {r["day"]}', r["text"])
    return r


def run_weekly(log, use_llm):
    r = review_week(log, date.today())
    r["text"] = reword(r, plain(r), use_llm)
    rev = read(REVIEW, {})
    rev["weekly"] = r
    write(REVIEW, rev)
    notify("Gym week review", r["text"])
    return r


def main():
    use_llm = "--no-llm" not in sys.argv
    args = sys.argv[1:]
    for flag, fn in (("--apply", apply), ("--dismiss", dismiss)):
        if flag in args:
            try:
                fn(args[args.index(flag) + 1])
            except (ValueError, IndexError) as e:
                sys.exit(str(e))
            print("ok")
            return
    log = gym_export.load()
    state = read(STATE, {"reviewed": [], "last_weekly": ""})
    if "--session" in args or "--weekly" in args:
        if "--session" in args and log:
            print(run_session(log, log[-1], use_llm)["text"])
        if "--weekly" in args:
            print(run_weekly(log, use_llm)["text"])
        return
    unreviewed = [s for s in log if s["id"] not in state["reviewed"]]
    if unreviewed:   # review only the newest; older ones (a backlog) are marked reviewed without noise
        run_session(log, unreviewed[-1], use_llm)
        state["reviewed"] += [s["id"] for s in unreviewed]
    now = datetime.now()
    if now.weekday() == 6 and now.hour >= 18 and state["last_weekly"] != now.date().isoformat() and log:
        run_weekly(log, use_llm)
        state["last_weekly"] = now.date().isoformat()
    write(STATE, state)


if __name__ == "__main__":
    main()
