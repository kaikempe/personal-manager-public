# Contributing

Thanks for helping. A few rules keep this tool safe for people who run it on their own calendar and mail.

## Before you open a pull request

```
python3 -m unittest discover -s tests      # standard library only; no network, no model, no real calendar
python3 dashboard/server.py --demo         # look at your change with the sample data
```

- **Standard library only** for Python. The one exception is `pyobjc` for EventKit, which is optional.
- **No personal data in code**: no names, addresses, school or employer names, calendar names or links.
  Anything that differs per person is a setting in `scripts/pm_env.py` (with a default) and goes in `config.env`.
- **The model proposes; code decides.** A new action must be re-validated in code and must wait for the user's
  click or a code-checked "yes". Anything that deletes, pays or sends is never a voice action.
- New integrations should be a **plugin** (`plugins/README.md`) or a **calendar source** (`scripts/ics_source.py`
  shows the record shape) rather than changes all over the code.
- Add a test for each rule that must not break.

## Good first contributions

- More calendar sources: CalDAV, or Google through its API
- Linux support for the read-only parts (dashboard and ICS export already avoid macOS APIs)
- Plugins for booking systems, habit trackers and to-do apps
