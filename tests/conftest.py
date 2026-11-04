"""Shared test tools: a real local HTTP server and a real subprocess run of the bot."""
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
CANARY = "CANARYTOKENabc123"
WEBHOOK_PATH = f"/api/webhooks/123/{CANARY}"


def fixture_bytes(name):
    return (FIXTURES / name).read_bytes()


def commlink_payload(ids):
    """A comm-link API body with the same shape as tests/fixtures/commlink.json."""
    data = [
        {
            "id": i,
            "title": f"Article {i}",
            "rsi_url": f"https://robertsspaceindustries.com/en/comm-link/transmission/{i}-Article",
            "channel": "Transmission",
            "category": "Undefined",
            "images": [],
            "created_at": "2026-11-02T20:00:00+00:00",
        }
        for i in ids
    ]
    return json.dumps({"data": data}).encode()


class FakeServer:
    """Routes map a path to a list of (status, headers, body, delay). The last entry repeats."""

    def __init__(self):
        self.routes = {}
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                path = self.path.split("?")[0]
                outer.requests.append(
                    {"method": self.command, "path": path, "full_path": self.path, "body": body, "at": time.monotonic()}
                )
                queue = outer.routes.get(path)
                if not queue:
                    status, headers, payload, delay = 404, {}, b"not found", 0
                else:
                    status, headers, payload, delay = queue.pop(0) if len(queue) > 1 else queue[0]
                if delay:
                    time.sleep(delay)
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = _serve

            def log_message(self, *args):
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def route(self, path, *responses):
        self.routes[path] = [
            (r + (0,))[:4] if len(r) == 3 else r for r in responses
        ]

    def posts(self, path=WEBHOOK_PATH):
        return [r for r in self.requests if r["method"] == "POST" and r["path"] == path]

    def all_posts(self):
        return [r for r in self.requests if r["method"] == "POST"]

    def gets(self, path):
        return [r for r in self.requests if r["method"] == "GET" and r["path"] == path]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    srv = FakeServer()
    yield srv
    srv.close()


class Bot:
    """Runs `python -m bot.main` as a real process against the fake server."""

    def __init__(self, tmp_path, srv):
        self.srv = srv
        self.state_path = tmp_path / "state.json"
        self.config_path = tmp_path / "config.yaml"
        self.webhook = srv.base + WEBHOOK_PATH
        self.config = {
            "schedule_minutes": 30,
            "timezone": "Asia/Bangkok",
            "batch_threshold": 5,
            "role_mention": "",
            "sources": {"sc_commlink": srv.base + "/commlink", "sc_status": srv.base + "/status"},
            "feeds": {
                "sc_commlink": {"enabled": True, "webhook": "SC_WEBHOOK"},
                "sc_status": {"enabled": True, "webhook": "SC_WEBHOOK"},
            },
        }
        srv.route("/commlink", (200, {"Content-Type": "application/json"}, fixture_bytes("commlink.json")))
        srv.route("/status", (200, {"Content-Type": "text/xml"}, fixture_bytes("status.xml")))
        srv.route(WEBHOOK_PATH, (204, {}, b""))

    def run(self, *args, webhook="default"):
        self.config_path.write_text(yaml.safe_dump(self.config), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "SC_WEBHOOK"}
        env["BOT_RETRY_BACKOFF"] = "0"
        if webhook is not None:
            env["SC_WEBHOOK"] = self.webhook if webhook == "default" else webhook
        return subprocess.run(
            [sys.executable, "-m", "bot.main", "--config", str(self.config_path), "--state", str(self.state_path), *args],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=60,
        )

    def state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def write_state(self, state):
        self.state_path.write_text(json.dumps(state), encoding="utf-8")

    def forget(self, feed, item_id):
        state = self.state()
        state["feeds"][feed]["seen"].remove(item_id)
        self.write_state(state)


@pytest.fixture
def bot(tmp_path, server):
    return Bot(tmp_path, server)
