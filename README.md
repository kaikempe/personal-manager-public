# personal-manager

A local planning system for macOS: a dashboard over your Apple Calendar, a project registry,
mail and inbox intake, and a phone gym tracker. State lives in plain files; a Claude Code session
in this folder acts as the planner. Everything runs on your Mac. Nothing is uploaded except the
optional gym sync to your own Netlify site.

macOS only (Calendar, Reminders and Mail are read through EventKit and AppleScript). Python 3 and
the [Claude Code](https://claude.com/claude-code) CLI are needed for the AI parts.

## Quick start

```
git clone <this repo> personal-manager && cd personal-manager
./setup.sh
python3 dashboard/server.py        # then open http://127.0.0.1:8765
```

`setup.sh` creates your private `state.md`, `items.json`, `registry/` and `CLAUDE.md` from the
examples, asks for your timezone and Mail accounts (saved in `config.env`), and installs the
calendar export (macOS asks for Calendar access once). It is safe to re-run.

Then edit `CLAUDE.md` (your priorities) and add one file per project in `registry/`.
The chat, mail suggestions and inbox processing call the `claude` CLI, so they use **your own**
Claude Code login. Without it the dashboard still works. Optional extras (inbox, mail suggestions,
gym tracker, Obsidian vault sync) each have an `scripts/install_*.sh`.

## Configuration (`config.env`, or environment variables)

| variable | meaning |
|---|---|
| `PM_TIMEZONE` | your IANA timezone, e.g. `Europe/Berlin` (default `UTC`) |
| `MAIL_ACCOUNTS` | comma-separated Mail.app account names for mail suggestions (default `iCloud`) |
| `VAULT_DIR` | optional Obsidian vault folder (default `~/Documents/Vault`) for vault sync and gym plan |
| `GYM_SITE_URL` | your Netlify site for gym sync, e.g. `https://my-gym-log.netlify.app` |
| `GYM_TOKEN` | Netlify env var for `app/gym-functions`; keep the same value in `data/gym_token` |

## Layout

```
dashboard/   local web dashboard (server.py + index.html)
scripts/     calendar export, inbox and mail intake, gym ingest/review, vault sync
app/         gym PWA (app/gym) and its Netlify functions (app/gym-functions)
examples/    starter state.md, items.json and a registry entry
```

Your own `state.md`, `items.json`, `registry/`, `cv/` and `data/` are gitignored so personal data
never gets committed.

## Optional integrations

`BB Tracker` (university deadlines read from `~/Library/Application Support/BBTracker/`) and the Obsidian vault
scripts are specific to the original author's setup. Everything works without them; they stay silent when absent.

## Privacy

Scripts read your calendar, reminders and mail headers locally. Review `scripts/mail_filter.json`
and the prompts in `scripts/` and `dashboard/server.py` before running them against your accounts.

## License

MIT, see `LICENSE`.
