"""data/proposals.json: suggestions pulled from mail, waiting for the user's yes.

Written by mail_suggest.py (launchd) and by the dashboard server, so every change goes
through update(), which holds a file lock and writes atomically.
"""
import fcntl
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "proposals.json"
LOCK = ROOT / "data" / ".proposals.lock"


def load():
    try:
        return json.loads(PATH.read_text())
    except (OSError, ValueError):
        return {"proposals": []}


def update(fn):
    """fn(doc) mutates the document; it is saved afterwards. Returns fn's result."""
    PATH.parent.mkdir(exist_ok=True)
    with open(LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        doc = load()
        result = fn(doc)
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
        os.replace(tmp, PATH)
        return result
