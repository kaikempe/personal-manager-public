"""Loads config.env from the repo root into os.environ (existing variables win). Imported for its side effect."""
import os
from pathlib import Path

_f = Path(__file__).resolve().parent.parent / "config.env"
if _f.exists():
    for _line in _f.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
