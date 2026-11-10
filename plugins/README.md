# Plugins: connect your own tools

A plugin is one Python file in this folder. The dashboard chat and the phone endpoint load every
`plugins/*.py` whose name does not start with `_`. A plugin can add **actions** that the chat proposes and
you confirm, extra **chat rules**, and **phone routes**. `_example.py` is a working template: copy it to
`my_tool.py` and edit it.

| name | type | what it does |
|---|---|---|
| `ACTIONS` | `dict` | `kind -> spec`. The chat may propose `ACTION {"kind": "<kind>", ...}`. Nothing runs until you click the button on the dashboard (or say yes on the phone, if `voice` is set) |
| `CHAT_RULES` | `str` | Extra lines for the chat's system prompt: when to propose your action, and how to fill it |
| `BROWSER_WORDS` | `str` | Regex fragment. Questions that match it start Chrome first, for the browser tools |
| `ROUTES` | `dict` | `"/path" -> fn(cmd, phone)` for the phone endpoint (`scripts/phone_server.py`). The request needs the phone token |
| `CHECKS` | `fn() -> [(level, name, detail)]` | Rows for `scripts/health.py` and the System page. `level` is `ok`, `warn` or `error` |
| `HOURLY` | `fn()` | Called once an hour by `scripts/state_refresh.py`, with no arguments. For reminders: use `notify.send(text, phone=True, key=...)`, the key keeps it to one alert |
| `INBOX_LINE`, `INBOX` | regex (compiled, or a string matched case-insensitively), `fn(text, created) -> str` | A Reminders inbox line that matches `INBOX_LINE` from its start is your command (e.g. filed by a phone shortcut while the Mac was unreachable). It is run in code, before any model, and its reminder is ticked first. `created` is a naive `datetime` or `None`. Return what happened; start with "Not ", "Could not" or "No " when it was refused, so it shows on the Inbox page as needing you |

An action spec has these keys:

| key | meaning |
|---|---|
| `run(action) -> str` | Does the work and returns a short message for the toast. **Re-validate every field**: the action comes from model output. Raise `ValueError` to refuse |
| `label` | Button text on the dashboard |
| `example` | One `ACTION {...}` line that shows the chat the exact shape |
| `voice` | `True`: a plain "yes" on the phone may run it. Leave it out for anything that deletes, pays or sends |
| `slow`, `slow_reply(action)` | For a run longer than about 10 s. The phone answers with `slow_reply` and runs the action in the background |

Rules that keep plugins safe:
- Only propose; never act from the prompt. The click or the "yes" is the user's consent.
- A plugin that writes to a calendar must use `scripts/cal_write.py`. It writes only to `PM_WRITE_CALENDAR` and refuses duplicates.
- Plugins run with your user's rights. Read a plugin before you drop it in.
- Demo mode (`PM_DEMO=1`) turns plugin actions off.
- `scripts/plugins_load.py` loads plugins for every program. A plugin that fails to import is skipped by the background
  jobs (and reported); the dashboard refuses to start with it, so you notice.
- An `INBOX` command may run hours after it was written: resolve "today" and "tomorrow" from `created`, and refuse what
  is no longer possible instead of doing the next best thing.
