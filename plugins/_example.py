"""Example plugin: "log a reading" into data/readings.jsonl. Copy to plugins/readings.py to turn it on.

Shows the whole interface (plugins/README.md): one confirmable chat action, a chat rule, and a phone route.
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import pm_env  # noqa: E402

LOG = pm_env.DATA / "data" / "readings.jsonl"


def run(a):
    """The action text comes from the model: check every field before writing anything."""
    title = re.sub(r"[\x00-\x1f]", " ", str(a.get("title") or "")).strip()[:120]
    pages = a.get("pages")
    if not title or not isinstance(pages, int) or not 0 < pages < 2000:
        raise ValueError("need a title and a page count between 1 and 1999")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps({"date": date.today().isoformat(), "title": title, "pages": pages}) + "\n")
    return f"Logged {pages} pages of {title}"


ACTIONS = {"log_reading": {
    "label": "Log reading",
    "example": 'ACTION {"kind":"log_reading","title":"<book>","pages":12,"summary":"Log 12 pages of <book>"}',
    "run": run,
    "voice": True,
}}

CHAT_RULES = "Reading log: when the user says they read pages of a book, propose one log_reading action."


def today_total(cmd, phone):
    """POST /reading (phone token required) → pages read today, spoken back."""
    rows = [json.loads(l) for l in LOG.read_text().splitlines()] if LOG.exists() else []
    n = sum(r["pages"] for r in rows if r["date"] == date.today().isoformat())
    return f"You read {n} pages today."


ROUTES = {"/reading": today_total}
