"""Outbound HTTP client used by Person A's integration layer.

Contract-first design rules (enforced here so every caller benefits):
- one pooled requests.Session (connection reuse across calls);
- explicit (connect, read) timeouts on every request;
- bounded retries with linear backoff ONLY for idempotent methods (GET/HEAD)
  and only on connection errors, timeouts and HTTP 5xx - never on 4xx;
- this layer NEVER raises past its return boundary: it returns a
  (payload, error, kind) tuple where kind is one of
  "ok" | "unavailable" | "timeout" | "unauthorized" | "invalid_response";
- responses are validated against the keys of the documented contract so
  a wrong/foreign service is reported as invalid_response instead of
  crashing the expense app;
- log lines carry method, URL path, status and timing only - never bodies.
"""
import logging
import time
from typing import Any, Optional
from urllib.parse import urlsplit

import requests

logger = logging.getLogger("expense_budget.integration")

RETRYABLE_METHODS = {"GET", "HEAD"}

_session: Optional[requests.Session] = None


def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"Accept": "application/json", "User-Agent": "expense-budget-api/1.1"})
    return _session


def _describe(url: str) -> str:
    """host + path only (no query string) for logs and error messages."""
    parts = urlsplit(url)
    return f"{parts.netloc}{parts.path}"


def fetch_json(
    method: str,
    url: str,
    *,
    timeout: float,
    connect_timeout: Optional[float] = None,
    max_retries: int = 0,
    backoff_seconds: float = 0.5,
    json_body: Optional[dict] = None,
    params: Optional[dict] = None,
    expected_keys: Optional[tuple[str, ...]] = None,
) -> tuple[Optional[Any], Optional[str], str]:
    """Perform an HTTP request and return (payload, error, kind).

    `timeout` is the read timeout; `connect_timeout` defaults to it.
    """
    method = method.upper()
    attempts = max(1, max_retries + 1) if method in RETRYABLE_METHODS else 1
    timeouts = (connect_timeout if connect_timeout is not None else timeout, timeout)
    target = _describe(url)
    last_error: Optional[str] = None
    last_kind = "unavailable"

    for attempt in range(attempts):
        started = time.perf_counter()
        try:
            response = get_session().request(method, url, json=json_body, params=params, timeout=timeouts)
        except requests.Timeout:
            last_error, last_kind = f"timeout: no response from {target} within {timeouts[1]:g}s", "timeout"
        except requests.ConnectionError:
            last_error, last_kind = f"unavailable: cannot connect to {target}", "unavailable"
        except requests.RequestException as exc:
            last_error, last_kind = f"unavailable: {exc.__class__.__name__} calling {target}", "unavailable"
        else:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info("%s %s -> HTTP %s in %.0f ms", method, target, response.status_code, elapsed_ms)
            if response.status_code >= 500:
                last_error, last_kind = f"unavailable: {target} returned HTTP {response.status_code}", "unavailable"
            elif response.status_code in (401, 403):
                return None, f"unauthorized: {target} returned HTTP {response.status_code}", "unauthorized"
            elif response.status_code >= 400:
                return None, f"invalid_response: {target} returned HTTP {response.status_code}", "invalid_response"
            else:
                try:
                    payload = response.json()
                except ValueError:
                    return None, f"invalid_response: {target} did not return JSON", "invalid_response"
                if expected_keys:
                    if not isinstance(payload, dict):
                        return None, "invalid_response: expected a JSON object", "invalid_response"
                    missing = [key for key in expected_keys if key not in payload]
                    if missing:
                        return None, f"invalid_response: missing contract keys {missing}", "invalid_response"
                return payload, None, "ok"

        logger.warning("%s %s failed (attempt %d/%d): %s", method, target, attempt + 1, attempts, last_error)
        if attempt < attempts - 1:
            time.sleep(backoff_seconds * (attempt + 1))

    return None, last_error, last_kind


def check_service_health(
    base_url: str, *, timeout: float, connect_timeout: Optional[float] = None
) -> tuple[Optional[dict], Optional[str], str, float]:
    """Probe a peer service's /health endpoint. Returns (payload, error, kind, latency_ms)."""
    if not base_url:
        return None, None, "not_configured", 0.0
    started = time.perf_counter()
    payload, error, kind = fetch_json(
        "GET", f"{base_url}/health", timeout=timeout, connect_timeout=connect_timeout,
        max_retries=0, expected_keys=("status", "service"),
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    return payload, error, kind, latency_ms
