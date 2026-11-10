"""Loads plugins/*.py once, for every program that uses them (dashboard, phone endpoint, health, hourly job, inbox).

The interface is in plugins/README.md. A file whose name starts with "_" is a template and is skipped. A plugin
that fails to import is skipped and reported on stderr: one broken plugin must not stop a background job.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_cache = None


def load(strict=False):
    global _cache
    if _cache is not None:
        return _cache
    out = []
    for f in sorted((ROOT / "plugins").glob("*.py")):
        if f.name.startswith("_"):
            continue
        name = f"pm_plugin_{f.stem}"
        try:
            spec = importlib.util.spec_from_file_location(name, f)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        except Exception as e:  # noqa: BLE001
            sys.modules.pop(name, None)
            if strict:
                raise
            print(f"plugin {f.name} not loaded: {e}", file=sys.stderr)
            continue
        out.append(mod)
    _cache = out
    return out


def each(hook):
    """(plugin, attribute) for every loaded plugin that defines `hook`."""
    return [(m, getattr(m, hook)) for m in load() if getattr(m, hook, None)]
