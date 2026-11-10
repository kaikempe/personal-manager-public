#!/usr/bin/env python3
"""Phone endpoint: Siri (or any shortcut) asks the personal manager a question and hears the answer.

    python3 scripts/phone_server.py          # 127.0.0.1:8766, kept alive by launchd (scripts/install_phone.sh)

POST /ask  {"text": "..."}  with  Authorization: Bearer <data/phone_token>   →  text/plain answer to speak.
POST /<route>  {...}  same token  →  a plugin's phone route (plugins/README.md), e.g. a one-phrase Siri shortcut
GET  /ping                                                                  →  "ok" (no data, no token)

Reach it from the phone only through a private network such as `tailscale serve` (your own tailnet; never expose it
to the internet). The dashboard itself stays local-only: this server is separate and only reuses its chat (`run_chat`,
same snapshot, same model rules) and its action runner (`act_chat`).

Actions: the chat can only propose (ACTION lines). The phone keeps ONE proposal pending for 5 minutes and asks
"Say yes to …". It runs only when the user's next message is a plain yes, decided by `confirm.is_yes` on their own
words, never by the model, so a web page or mail cannot approve anything. Allowed by voice: add_task, add_event, and
plugin actions marked `voice`. Deleting stays on the dashboard. `remember` follows the dashboard's autosave rule.
Five wrong tokens within an hour lock the endpoint for an hour (and post a notification).
Every exchange goes to data/phone_log.jsonl.
"""
import hmac
import json
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
import socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))
sys.path.insert(0, str(ROOT / "scripts"))
import confirm  # noqa: E402
import pm_env  # noqa: E402

PORT = int(pm_env.get("PM_PHONE_PORT", "8766"))
TOKEN_FILE = pm_env.DATA / "data" / "phone_token"
SESSION = pm_env.DATA / "data" / "phone_session.json"
LOG = pm_env.DATA / "data" / "phone_log.jsonl"
VOICE_ACTIONS = {"add_task", "add_event"}   # plus plugin actions marked "voice"
PENDING_S = 300        # a yes counts for 5 minutes after the question
CONVO_S = 15 * 60      # follow-up questions keep context for 15 minutes
MAX_BAD, LOCK_S = 5, 3600
_lock = threading.Lock()
_bad = []              # timestamps of wrong tokens
_locked_until = 0.0


def dash():
    import server  # the dashboard module: run_chat, act_chat, autosave, ACTION_LINE (imported late: it is heavy)
    return server


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def save_session(s):
    tmp = SESSION.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False))
    tmp.replace(SESSION)


def log(rec):
    with LOG.open("a") as f:
        f.write(json.dumps({"ts": datetime.now().astimezone().isoformat(timespec="seconds"), **rec}, ensure_ascii=False) + "\n")


def notify(text):
    # Results of something asked from the phone go back to the phone (scripts/notify.py), not only to the Mac.
    import notify as _n
    _n.send(text, phone=True)


def token_ok(header):
    """Constant-time token check with a lockout after repeated failures."""
    global _locked_until
    now = time.time()
    with _lock:
        if now < _locked_until:
            return False
        want = TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else ""
        got = header[7:].strip() if header.startswith("Bearer ") else ""
        if want and hmac.compare_digest(got.encode(), want.encode()):
            return True
        _bad[:] = [t for t in _bad if now - t < LOCK_S] + [now]
        if len(_bad) >= MAX_BAD:
            _locked_until = now + LOCK_S
            _bad.clear()
            notify("Phone endpoint locked for 1 hour after 5 wrong tokens.")
        return False


def spoken(text):
    """Plain text for Siri: no ACTION lines, no markdown symbols."""
    text = re.sub(r"^ACTION \{.*\}[ \t]*$", "", text, flags=re.M)
    text = re.sub(r"[*_`#>|]", "", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def plugin_actions():
    return dash().PLUGIN_ACTIONS


def routes():
    return {p: fn for m in dash().PLUGINS for p, fn in getattr(m, "ROUTES", {}).items()}


def voice_actions():
    return VOICE_ACTIONS | {k for k, v in plugin_actions().items() if v.get("voice")}


def proposals(reply):
    out = []
    for m in dash().ACTION_LINE.finditer(reply):
        try:
            a = json.loads(m.group(1))
        except ValueError:
            continue
        if a.get("kind") in voice_actions():
            out.append(a)
    return out


_session_lock = threading.Lock()


def background(fn):
    threading.Thread(target=fn, daemon=True).start()


def answer(text, chat=None, act=None, save=None, run_bg=background):
    """One turn. chat(messages) -> reply text; act(action) -> message. Injectable for tests."""
    with _session_lock:
        s = read_json(SESSION, {})
        news = s.pop("result", None)   # a background action that finished since the last question
        if news:
            save_session(s)
    say = _answer(text, chat or (lambda msgs: run_chat(msgs)), act or (lambda a: dash().act_chat(a)), save, run_bg)
    return f"Earlier: {news}\n{say}" if news else say


def run_later(pending, act):
    """A slow plugin action takes longer than Siri waits: run it after answering, tell the result next time."""
    try:
        out = act(pending)
    except (ValueError, KeyError, RuntimeError, OSError) as e:
        out = f"{pending.get('summary') or pending.get('kind')} did not work: {e}"
    with _session_lock:
        s = read_json(SESSION, {})
        s["result"] = out
        save_session(s)
    log({"background": pending, "reply": out})
    notify(out)


def _answer(text, chat, act, save, run_bg):
    now = time.time()
    s = read_json(SESSION, {})
    if now - s.get("updated", 0) > CONVO_S:
        s = {k: v for k, v in s.items() if k == "result"}
    msgs = s.get("messages", [])
    pending = s.get("pending") if now - s.get("pending_at", 0) < PENDING_S else None

    spec = plugin_actions().get(pending.get("kind"), {}) if pending else {}
    if pending and spec.get("slow") and confirm.is_yes(text):
        out = spec["slow_reply"](pending) if spec.get("slow_reply") else \
            f'Working on it: {pending.get("summary") or pending["kind"]}. I\'ll tell you the result next time you ask.'

        s.update(messages=(msgs + [{"role": "user", "content": text}, {"role": "assistant", "content": out}])[-12:],
                 pending=None, updated=now)
        save_session(s)
        log({"text": text, "did": pending, "reply": out})
        run_bg(lambda: run_later(pending, act))
        return out
    if pending and confirm.is_yes(text):
        try:
            out = act(pending)
        except (ValueError, KeyError, RuntimeError, OSError) as e:
            out = f"That did not work: {e}"
        s.update(messages=(msgs + [{"role": "user", "content": text}, {"role": "assistant", "content": out}])[-12:],
                 pending=None, updated=now)
        save_session(s)
        log({"text": text, "did": pending, "reply": out})
        return out
    if pending and confirm.is_no(text):
        s.update(pending=None, updated=now)
        save_session(s)
        log({"text": text, "dropped": pending})
        return "OK, I won't do it."

    msgs = (msgs + [{"role": "user", "content": text}])[-12:]
    reply = chat(msgs)
    acts = proposals(reply)
    if save is None:
        try:
            saved = dash().autosave(reply, text)
        except Exception:  # noqa: BLE001  (saving to the vault must never break the answer)
            saved = []
    else:
        saved = save(reply, text)
    say = spoken(reply)
    if saved:
        say += "\nSaved that to your notes."
    if acts:
        say += f'\nSay yes to: {acts[0].get("summary") or acts[0].get("title") or acts[0]["kind"]}.'
        if len(acts) > 1:
            say += f" ({len(acts) - 1} more on the dashboard.)"
    s.update(messages=msgs + [{"role": "assistant", "content": reply}], pending=acts[0] if acts else None,
             pending_at=now if acts else 0, updated=now)
    save_session(s)
    log({"text": text, "reply": say, "proposed": acts})
    return say


def run_chat(msgs):
    parts = []
    dash().run_chat(msgs, "smart", parts.append)
    return "".join(parts)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def send(self, code, text):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send(200, "ok") if self.path == "/ping" else self.send(404, "not found")

    def do_POST(self):
        extra = routes()
        if self.path != "/ask" and self.path not in extra:
            return self.send(404, "not found")
        if self.headers.get("Origin"):   # a web page in a browser; the phone shortcut sends none
            return self.send(403, "forbidden")
        if not token_ok(self.headers.get("Authorization", "")):
            return self.send(401, "wrong or missing token")
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 20000)
            raw = self.rfile.read(n).decode("utf-8", "replace")
            if self.path in extra:
                try:
                    cmd = json.loads(raw)
                    assert isinstance(cmd, dict)
                except (ValueError, AssertionError):
                    return self.send(400, "The shortcut sent no command.")
                try:
                    return self.send(200, extra[self.path](cmd, sys.modules[__name__]))
                except ValueError as e:
                    log({"route": self.path, "cmd": cmd, "refused": str(e)})
                    return self.send(200, f"Not done: {e}")
            try:
                text = str(json.loads(raw).get("text", ""))
            except (ValueError, AttributeError):
                text = raw   # a shortcut may send the dictated text as the plain body
            text = text.strip()[:2000]
            if not text:
                return self.send(400, "Say something after the shortcut starts.")
            self.send(200, answer(text))
        except Exception as e:  # noqa: BLE001  (Siri should hear what went wrong, not time out)
            log({"error": str(e)[:300]})
            self.send(500, f"Something went wrong: {str(e)[:200]}")


class LocalServer(ThreadingHTTPServer):
    """Binds without HTTPServer's reverse DNS lookup (socket.getfqdn), which stalled startup for over 20 s on GitHub's
    macOS runners. It only listens on 127.0.0.1, so the name is not needed."""
    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


if __name__ == "__main__":
    srv = LocalServer(("127.0.0.1", PORT), Handler)
    print(f"phone endpoint on http://127.0.0.1:{PORT}", file=sys.stderr)
    srv.serve_forever()
