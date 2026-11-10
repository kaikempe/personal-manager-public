# Security

personal-manager runs on your own Mac and reads your calendar, reminders and mail. Please treat security
problems seriously and privately.

## Reporting a vulnerability

Use GitHub's **private vulnerability reporting** (Security tab > "Report a vulnerability"). Please don't open a
public issue. Include the steps to reproduce it and what an attacker gains. You should get a first answer
within a week.

## What the design already assumes

- **The dashboard is local only.** It listens on 127.0.0.1. Each request must name the dashboard as its Host
  (this blocks DNS rebinding). A POST that carries another site's Origin is refused, so other web pages cannot
  write. Local programs can still call it, so never put it behind a tunnel or a reverse proxy.
- **The model only proposes.** Calendar writes, deletes and plugin actions run only after your click, or after a
  plain "yes" on the phone that is checked by code, never by a model. Mail and web pages are passed to the model as
  data, never as instructions. Calendar writes go only to `PM_WRITE_CALENDAR`, and duplicates are refused.
- **The phone endpoint** (`scripts/phone_server.py`, optional) needs a Bearer token. Five wrong tokens lock it for an
  hour. Reach it only through a private network such as Tailscale `serve`, never `funnel` or a public port.
- **Secrets stay out of git.** `config.env`, `data/` (tokens, logs), `ics_feeds.txt` (secret calendar links) and
  your own files are gitignored. CI scans the history for secrets.
- **Plugins** (`plugins/*.py`) run with your user's rights. Read a plugin before you install it.

## What leaves your Mac

See [Privacy](README.md#privacy). In short: the AI features send their input to Anthropic through your own
Claude Code login. The optional gym sync goes to your own Netlify site. Nothing else leaves your Mac.
