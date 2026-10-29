"""Real-HTTP tests for services.integration_client against a local stub server.

No external services are contacted: a throwaway http.server on 127.0.0.1
plays the peer and misbehaves on purpose (slow, 500, 401, non-JSON, wrong shape).
"""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from services.integration_client import fetch_json

CALLS: dict[str, int] = {}


class StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep pytest output clean
        pass

    def _send(self, status, body, content_type="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        CALLS[self.path] = CALLS.get(self.path, 0) + 1
        if self.path == "/ok":
            self._send(200, json.dumps({"service": "x", "subscriptions": []}))
        elif self.path == "/slow":
            time.sleep(1.0)
            self._send(200, "{}")
        elif self.path == "/boom":
            self._send(503, json.dumps({"detail": "down"}))
        elif self.path == "/flaky":
            if CALLS[self.path] == 1:
                self._send(502, "bad gateway", "text/plain")
            else:
                self._send(200, json.dumps({"service": "x", "subscriptions": []}))
        elif self.path == "/secret":
            self._send(401, json.dumps({"detail": "no"}))
        elif self.path == "/html":
            self._send(200, "<html>sleeping</html>", "text/html")
        elif self.path == "/list":
            self._send(200, "[1, 2, 3]")
        else:
            self._send(404, json.dumps({"detail": "nope"}))

    def do_POST(self):
        CALLS["POST" + self.path] = CALLS.get("POST" + self.path, 0) + 1
        self._send(503, "{}")


@pytest.fixture(scope="module")
def stub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_ok_payload(stub):
    payload, error, kind = fetch_json("GET", f"{stub}/ok", timeout=2, expected_keys=("service", "subscriptions"))
    assert kind == "ok" and error is None and payload["service"] == "x"


def test_timeout_is_distinguished(stub):
    payload, error, kind = fetch_json("GET", f"{stub}/slow", timeout=0.2, max_retries=0)
    assert kind == "timeout" and payload is None and "timeout" in error


def test_connection_refused_is_unavailable():
    payload, error, kind = fetch_json("GET", f"http://127.0.0.1:{_free_port()}/x", timeout=0.5, backoff_seconds=0)
    assert kind == "unavailable" and "cannot connect" in error


def test_5xx_is_retried_then_unavailable(stub):
    CALLS.pop("/boom", None)
    _, error, kind = fetch_json("GET", f"{stub}/boom", timeout=2, max_retries=2, backoff_seconds=0)
    assert kind == "unavailable" and "503" in error
    assert CALLS["/boom"] == 3


def test_transient_5xx_recovers_on_retry(stub):
    CALLS.pop("/flaky", None)
    payload, _, kind = fetch_json("GET", f"{stub}/flaky", timeout=2, max_retries=1, backoff_seconds=0)
    assert kind == "ok" and payload["service"] == "x"


def test_post_is_never_retried(stub):
    CALLS.pop("POST/anything", None)
    _, _, kind = fetch_json("POST", f"{stub}/anything", timeout=2, max_retries=3, backoff_seconds=0, json_body={})
    assert kind == "unavailable"
    assert CALLS["POST/anything"] == 1


def test_401_is_unauthorized_and_not_retried(stub):
    CALLS.pop("/secret", None)
    _, _, kind = fetch_json("GET", f"{stub}/secret", timeout=2, max_retries=2, backoff_seconds=0)
    assert kind == "unauthorized" and CALLS["/secret"] == 1


def test_404_is_invalid_response(stub):
    _, error, kind = fetch_json("GET", f"{stub}/missing", timeout=2)
    assert kind == "invalid_response" and "404" in error


def test_non_json_body_is_invalid_response(stub):
    _, error, kind = fetch_json("GET", f"{stub}/html", timeout=2)
    assert kind == "invalid_response" and "JSON" in error


def test_wrong_shape_is_invalid_response(stub):
    _, error, kind = fetch_json("GET", f"{stub}/list", timeout=2, expected_keys=("service",))
    assert kind == "invalid_response"
    _, error, kind = fetch_json("GET", f"{stub}/ok", timeout=2, expected_keys=("months",))
    assert kind == "invalid_response" and "months" in error
