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
