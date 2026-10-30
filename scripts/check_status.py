#!/usr/bin/env python3
"""Compare each registry entry's claimed status against what the folders show.

Read-only. Stdlib only. For every registry/*.md it finds the last activity
(newest commit across all branches if the path is a git repo, otherwise the
newest file mtime, ignoring node_modules/.venv/caches) and flags:

  STALE-ACTIVE      status active, nothing touched for > --stale days
  ACTIVE-ARCHIVED   status archived/completed, but touched within --fresh days
  REVISIT-DUE       status on-hold and revisit date reached
  NO-REVISIT        status on-hold with no revisit date or trigger
  NO-OUTCOME        status completed with no outcome written
  UNCONFIRMED       entry still marked confirmed: false
  NO-PATH           registry entry points at nothing on disk (fine for ideas)

Usage: check_status.py [--dev-root ~/Developer] [--stale 30] [--fresh 14] [--write]
  --write also saves the report to data/status_report.md
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", ".pytest_cache",
             ".tmp", "build", "dist", ".next", ".cache"}
SKIP_FILES = {".DS_Store"}


def parse_frontmatter(text: str) -> dict:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def last_commit(path: Path) -> date | None:
    try:
        r = subprocess.run(["git", "-C", str(path), "log", "--all", "-1", "--format=%cs"],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    s = r.stdout.strip()
    if r.returncode != 0 or not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def newest_file(path: Path) -> date | None:
    best = 0.0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            if f in SKIP_FILES or f.startswith("~$"):
                continue
            try:
                best = max(best, os.stat(os.path.join(dirpath, f)).st_mtime)
            except OSError:
                pass
    return datetime.fromtimestamp(best).date() if best else None


def activity(path: Path) -> tuple[date | None, str]:
    if not path.exists():
        return None, "missing"
    if (path / ".git").exists():
        d = last_commit(path)
        if d:
            return d, "commit"
    d = newest_file(path)
    return (d, "file") if d else (None, "empty")


def load_registry(reg_dir: Path) -> list[dict]:
    items = []
    for f in sorted(reg_dir.glob("*.md")):
        fm = parse_frontmatter(f.read_text(encoding="utf-8"))
        if fm.get("name"):
            fm["_file"] = f.name
            items.append(fm)
    return items


def check(item: dict, dev_root: Path, today: date, stale: int, fresh: int) -> dict:
    status = item.get("status", "unknown")
    rel = item.get("path", "")
    last, source = (None, "no path")
    if rel:
        last, source = activity(dev_root / rel)
    days = (today - last).days if last else None
    flags = []
    if rel and source == "missing":
        flags.append("NO-PATH")
    if status == "active" and days is not None and days > stale:
        flags.append("STALE-ACTIVE")
    if status in ("archived", "completed") and days is not None and days <= fresh:
        flags.append("ACTIVE-ARCHIVED")
    if status == "on-hold":
        rev = item.get("revisit", "")
        if not rev:
            flags.append("NO-REVISIT")
        else:
            try:
                if date.fromisoformat(rev) <= today:
                    flags.append("REVISIT-DUE")
            except ValueError:
                pass  # a trigger in words, not a date: fine
    if status == "completed" and not item.get("outcome"):
        flags.append("NO-OUTCOME")
    if item.get("confirmed", "false").lower() != "true":
        flags.append("UNCONFIRMED")
    return {"name": item["name"], "kind": item.get("kind", "?"), "status": status,
            "last": last.isoformat() if last else "-", "days": days if days is not None else "-",
            "source": source, "flags": flags}


def render(rows: list[dict], today: date) -> str:
    order = {"active": 0, "on-hold": 1, "idea": 2, "unknown": 3, "completed": 4, "archived": 5}
    rows = sorted(rows, key=lambda r: (order.get(r["status"], 3), r["name"]))
    out = [f"# Status check {today.isoformat()}", "",
           f"{'name':<30} {'kind':<11} {'status':<10} {'last':<11} {'days':>4}  flags"]
    for r in rows:
        out.append(f"{r['name']:<30} {r['kind']:<11} {r['status']:<10} {r['last']:<11} "
                   f"{str(r['days']):>4}  {' '.join(r['flags'])}")
    needs = [r for r in rows if set(r["flags"]) - {"UNCONFIRMED"}]
    out += ["", f"{len(needs)} entries with real mismatches, "
                f"{sum('UNCONFIRMED' in r['flags'] for r in rows)} still unconfirmed."]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dev-root", type=Path, default=Path("~/Developer").expanduser())
    ap.add_argument("--registry", type=Path, default=ROOT / "registry")
    ap.add_argument("--stale", type=int, default=30)
    ap.add_argument("--fresh", type=int, default=14)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)

    if not args.registry.is_dir():
        print(f"registry not found: {args.registry}", file=sys.stderr)
        return 2
    if not args.dev_root.is_dir():
        print(f"dev root not found: {args.dev_root}", file=sys.stderr)
        return 2
    items = load_registry(args.registry)
    if not items:
        print("registry is empty", file=sys.stderr)
        return 2
    today = date.today()
    text = render([check(i, args.dev_root, today, args.stale, args.fresh) for i in items], today)
    print(text)
    if args.write:
        out = ROOT / "data" / "status_report.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
