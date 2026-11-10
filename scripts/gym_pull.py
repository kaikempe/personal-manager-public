#!/usr/bin/env python3
"""Fetch finished workouts the phone app posted to the Netlify inbox and drop them into gym/sessions/.

    python3 scripts/gym_pull.py

gym_ingest.py then validates and logs them as usual (it dedupes by id, so a repeat is harmless).
A session is deleted from the inbox only after its file is written. Token: data/gym_token (not in git).

The same two calls carry the review to the phone and the answer back (since 2026-11-10):
  push   also sends `notes`: the last session review, the weekly review and the open weight proposals
         (data/gym_review.json, data/gym_proposals.json), so the app shows them where the training happens.
  pull   an inbox entry with "kind": "decision" is the user's tap on Accept / Not now for one proposal. It runs
         gym_review.apply / dismiss, exactly as the dashboard button does (apply still refuses when Gym.md no
         longer shows the old weight), and is logged to data/gym_decisions.jsonl. It is never written to sessions/.
"""
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSIONS = ROOT / "gym/sessions"
TOKEN_FILE = ROOT / "data/gym_token"
sys.path.insert(0, str(ROOT / "scripts"))
import pm_env  # noqa: E402

SITE = pm_env.get("GYM_SITE_URL").rstrip("/")   # your Netlify site, e.g. https://my-gym-log.netlify.app (config.env)
URL = f"{SITE}/api/session"
PLAN_URL = f"{SITE}/api/plan"


def call(method, url, token):
    req = urllib.request.Request(url, method=method, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def decide(d, review=None, tell=None):
    """One tap from the phone on a weight proposal. Returns what happened; never raises."""
    if review is None:
        import gym_review as review
    pid, accept = str(d.get("proposal") or ""), d.get("accept") is True
    try:
        (review.apply if accept else review.dismiss)(pid)
        out = "applied" if accept else "dismissed"
    except ValueError as e:
        out = f"refused: {e}"
    try:
        with (ROOT / "data/gym_decisions.jsonl").open("a") as f:
            f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "proposal": pid, "accept": accept,
                                "result": out}, ensure_ascii=False) + "\n")
    except OSError:
        pass
    if out.startswith("refused") and accept:
        if tell is None:
            import notify
            tell = notify.send
        tell(f"Gym: the weight change was not applied ({out[9:]}).", phone=True)
    return out


def notes():
    """What the phone shows next to the plan: the last reviews and the weight proposals still waiting."""
    def read(name, default):
        try:
            return json.loads((ROOT / "data" / name).read_text())
        except (OSError, ValueError):
            return default
    rev = read("gym_review.json", {})
    out = {"proposals": [{k: p.get(k) for k in ("id", "day", "exercise", "from", "to", "reason")}
                         for p in read("gym_proposals.json", {"proposals": []}).get("proposals", []) if p.get("status") == "pending"]}
    s, w = rev.get("session") or {}, rev.get("weekly") or {}
    if s.get("text"):
        out["session"] = {"date": s.get("date"), "day": s.get("day"), "text": str(s["text"])[:1500]}
    if w.get("text"):
        out["week"] = {"week_of": w.get("week_of"), "text": str(w["text"])[:1500]}
    return out


def pull():
    if not TOKEN_FILE.exists():
        return 0
    token = TOKEN_FILE.read_text().strip()
    SESSIONS.mkdir(parents=True, exist_ok=True)
    n = 0
    for s in call("GET", URL, token)["sessions"]:
        if s.get("kind") == "decision":
            print(f'gym proposal {s.get("proposal")}: {decide(s)}')
            call("DELETE", f"{URL}?id={s['id']}", token)
            continue
        tmp = SESSIONS / f".{s['id']}.part"
        tmp.write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, SESSIONS / f"{s['id']}.json")
        call("DELETE", f"{URL}?id={s['id']}", token)
        n += 1
    return n


def push():
    """Publish plan.json + history.json to the app, only when they changed since the last push."""
    if not TOKEN_FILE.exists():
        return False
    gym = ROOT / "gym"
    plan, hist = gym / "plan.json", gym / "history.json"
    if not plan.exists():
        return False
    body = json.dumps({"plan": json.loads(plan.read_text()), "history": json.loads(hist.read_text()) if hist.exists() else {},
                       "notes": notes()}, ensure_ascii=False, sort_keys=True).encode()
    digest = hashlib.sha256(body).hexdigest()
    stamp = ROOT / "data/.gym_push_hash"
    if stamp.exists() and stamp.read_text().strip() == digest:
        return False
    req = urllib.request.Request(PLAN_URL, data=body, method="PUT",
                                 headers={"Authorization": f"Bearer {TOKEN_FILE.read_text().strip()}", "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20).read()
    stamp.write_text(digest + "\n")
    return True


def main():
    try:
        n = pull()
        if n:
            print(f"pulled {n} session(s) from Netlify")
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:  # offline or inbox hiccup: try next run
        print("gym pull:", e)


def main_push():
    try:
        if push():
            print("published plan and history to the app")
    except (urllib.error.URLError, OSError, ValueError) as e:
        print("gym push:", e)


if __name__ == "__main__":
    main()
    main_push()
