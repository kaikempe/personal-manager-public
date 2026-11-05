"""The dashboard serves only its own page: not another site's page, not a rebound domain.

Starts the real server on a free port and talks to it over HTTP. Standard library only:
    python3 -m unittest discover -s tests
"""
import http.client
import json
import os
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class DashboardSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        env = {**os.environ, "PM_PORT": str(cls.port)}
        cls.proc = subprocess.Popen([sys.executable, str(ROOT / "dashboard/server.py")], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.1)
        cls.proc.kill()
        raise RuntimeError("dashboard did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)

    def request(self, method, path, host=None, origin=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest(method, path, skip_host=True)
        if host is not None:
            conn.putheader("Host", host)
        if origin is not None:
            conn.putheader("Origin", origin)
        data = json.dumps(body).encode() if body is not None else b""
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(len(data)))
        conn.endheaders(data)
        r = conn.getresponse()
        r.read()
        conn.close()
        return r.status

    def test_own_addresses_are_served(self):
        self.assertEqual(self.request("GET", "/api/version", host=f"127.0.0.1:{self.port}"), 200)
        self.assertEqual(self.request("GET", "/api/version", host=f"localhost:{self.port}"), 200)
        self.assertEqual(self.request("GET", "/", host=f"127.0.0.1:{self.port}"), 200)

    def test_rebound_domain_cannot_read(self):
        # DNS rebinding: the browser connects to 127.0.0.1 but names the attacker's domain in Host.
        for path in ("/", "/api/overview", "/api/inbox", "/api/version"):
            self.assertEqual(self.request("GET", path, host=f"evil.example:{self.port}"), 403, path)

    def test_missing_or_portless_host_is_refused(self):
        self.assertEqual(self.request("GET", "/api/version"), 403)
        self.assertEqual(self.request("GET", "/api/version", host="127.0.0.1"), 403)

    def test_rebound_domain_cannot_write(self):
        # Browsers send Origin on a POST, so the Origin check already stops this; kept so neither check regresses.
        origin = f"http://evil.example:{self.port}"
        self.assertEqual(self.request("POST", "/api/items", host=f"evil.example:{self.port}", origin=origin,
                                      body={"title": "x"}), 403)

    def test_other_site_cannot_write(self):
        self.assertEqual(self.request("POST", "/api/items", host=f"127.0.0.1:{self.port}",
                                      origin="https://evil.example", body={"title": "x"}), 403)


if __name__ == "__main__":
    unittest.main()
