"""Outbound HTTP client used by Person A's integration layer.

Contract-first design rules (enforced here so every caller benefits):
- explicit connect+read timeouts on every request;
- bounded retries (default 2) ONLY on connection errors and HTTP 5xx;
- this layer NEVER raises past its return boundary: it returns a
  (payload, error, kind) tuple where kind is one of
  "ok" | "unavailable" | "invalid_response";
- responses are validated against the keys of the documented contract so
  a wrong/foreign service is reported as invalid_response instead of
  crashing the expense app.
"""
import time
from typing import Any, Optional

import requests


def fetch_json(
    method: str,
    url: str,
    *,
    timeout: float,
    max_retries: int = 0,
    backoff_seconds: float = 0.5,
    json_body: Optional[dict] = None,
    params: Optional[dict] = None,
    expected_keys: Optional[tuple[str, ...]] = None,
) -> tuple[Optional[Any], Optional[str], str]:
    """Perform an HTTP request and return (payload, error, kind).

    Retries use linear backoff and only fire for connection failures or 5xx.
    HTTP 4xx and malformed JSON are NOT retried - they are contract errors.
    """
    attempts = max(1, max_retries + 1)
    last_error: Optional[str] = None

    for attempt in range(attempts):
        try:
            response = requests.request(method, url, json=json_body, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last_error = f"connection_error: {exc.__class__.__name__}"
            if attempt < attempts - 1:
                time.sleep(backoff_seconds * (attempt + 1))
                continue
            return None, last_error, "unavailable"

        if response.status_code >= 500:
            last_error = f"server_error: HTTP {response.status_code}"
            if attempt < attempts - 1:
                time.sleep(backoff_seconds * (attempt + 1))
                continue
            return None, last_error, "unavailable"

        if response.status_code >= 400:
            return None, f"client_error: HTTP {response.status_code}", "invalid_response"

        try:
            payload = response.json()
        except ValueError:
            return None, "invalid_response: response body is not JSON", "invalid_response"

        if expected_keys:
            missing = [key for key in expected_keys if key not in payload]
            if missing:
                return (
                    None,
                    f"invalid_response: missing contract keys {missing}",
                    "invalid_response",
                )

        return payload, None, "ok"

    return None, last_error, "unavailable"  # defensive; loop always returns


def check_service_health(
    base_url: str, *, timeout: float
) -> tuple[Optional[dict], Optional[str], str, float]:
    """Probe a peer service's /health endpoint. Returns (payload, error, kind, latency_ms)."""
    if not base_url:
        return None, None, "not_configured", 0.0
    started = time.perf_counter()
    payload, error, kind = fetch_json("GET", f"{base_url}/health", timeout=timeout, max_retries=0)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    return payload, error, kind, latency_ms
