"""Shared HTTP helpers for Person A's Streamlit frontend.

The UI is a pure REST client: it only talks to its own FastAPI backend over
HTTP (never imports backend database code). Every helper returns
(ok, data_or_error_message) and never raises, so one failing call cannot
crash unrelated parts of the page.

Configuration (first match wins):
  API_BASE_URL          env var, else Streamlit secret, else http://127.0.0.1:8001
  API_TIMEOUT_SECONDS   read timeout, default 60 (Render free instances can
                        take ~50 s to wake from sleep on the first request)
"""
import os
from typing import Any, Optional

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8001"


def _read_timeout() -> float:
    try:
        return float(os.getenv("API_TIMEOUT_SECONDS", "60"))
    except ValueError:
        return 60.0


DEFAULT_TIMEOUT = (5, _read_timeout())  # (connect, read) seconds

_session = requests.Session()
_session.headers.update({"Accept": "application/json"})


def resolve_api_base_url(secrets: Any = None, default: str = DEFAULT_BASE_URL) -> str:
    """Backend URL: env var (local / Render), then Streamlit secrets (Community
    Cloud), then the local default. Trailing slashes are removed."""
    value = (os.getenv("API_BASE_URL") or "").strip()
    if not value and secrets is not None:
        try:
            value = str(secrets.get("API_BASE_URL", "") or "").strip()
        except Exception:  # no secrets.toml in a plain local run
            value = ""
    return (value or default).rstrip("/")


def _url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _detail(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return (response.text or response.reason or "").strip()[:200]
    if isinstance(body, dict) and "detail" in body:
        detail = body["detail"]
        if isinstance(detail, list):  # FastAPI 422 validation errors
            return "; ".join(
                f"{'.'.join(str(p) for p in err.get('loc', [])[1:])}: {err.get('msg')}"
                if isinstance(err, dict) else str(err)
                for err in detail
            )
        return str(detail)
    return str(body)[:200]


def _request(method: str, base_url: str, path: str, **kwargs) -> tuple[bool, Any]:
    if not base_url.startswith(("http://", "https://")):
        return False, f"API_BASE_URL is not a valid http(s) URL: {base_url!r}"
    try:
        response = _session.request(method, _url(base_url, path), timeout=DEFAULT_TIMEOUT, **kwargs)
    except requests.Timeout:
        return False, (f"The API at {base_url} did not answer within {DEFAULT_TIMEOUT[1]:g} s. "
                       "If it is hosted on a free Render instance it may be waking up - retry in a minute.")
    except requests.ConnectionError:
        return False, f"Cannot reach the API at {base_url} - is the backend running?"
    except requests.RequestException as exc:
        return False, f"Request to the API failed ({exc.__class__.__name__})"
    if response.status_code >= 400:
        return False, f"HTTP {response.status_code}: {_detail(response)}"
    if not response.content:
        return True, {}
    try:
        return True, response.json()
    except ValueError:
        return False, f"The API at {base_url} returned a non-JSON response (HTTP {response.status_code})"


def api_get(base_url: str, path: str, params: Optional[dict] = None) -> tuple[bool, Any]:
    return _request("GET", base_url, path, params=params)


def api_post(base_url: str, path: str, json_body: dict) -> tuple[bool, Any]:
    return _request("POST", base_url, path, json=json_body)


def api_put(base_url: str, path: str, json_body: dict) -> tuple[bool, Any]:
    return _request("PUT", base_url, path, json=json_body)


def api_delete(base_url: str, path: str) -> tuple[bool, Any]:
    return _request("DELETE", base_url, path)


def money(value: Optional[float], currency: str = "INR") -> str:
    if value is None:
        return "-"
    return f"{currency} {value:,.2f}"
