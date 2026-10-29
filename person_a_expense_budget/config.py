"""Central configuration for Person A's service.

Twelve-factor style: every deployment-specific value comes from an
environment variable (optionally loaded from a local `.env` file).
Only placeholders live in `.env.example`; the real `.env` is gitignored.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_url(*names: str) -> str:
    """First non-empty env var among `names`, without a trailing slash."""
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value.rstrip("/")
    return ""


def is_valid_base_url(url: str) -> bool:
    return url.startswith(("http://", "https://")) and len(url) > len("https://")


class Settings:
    """Runtime settings for the expense/budget API."""

    service_name: str = os.getenv("SERVICE_NAME", "expense-budget-api")
    service_owner: str = "Person A - Sachien N (23MID0255)"
    version: str = "1.1.0"

    # Render injects PORT; local runs use APP_PORT.
    app_port: int = _get_int("APP_PORT", 8001)

    # Base URLs of the two peer services (Person B and Person C).
    # SUBSCRIPTION_API_URL / ELECTRICITY_API_URL are the preferred names;
    # the older INTEGRATION_B/C_BASE_URL names are still honoured.
    integration_b_base_url: str = _get_url("SUBSCRIPTION_API_URL", "INTEGRATION_B_BASE_URL")
    integration_c_base_url: str = _get_url("ELECTRICITY_API_URL", "INTEGRATION_C_BASE_URL")

    # Outbound HTTP behaviour: explicit connect/read timeouts + bounded retries.
    # Render free instances can take ~50 s to wake up, so the read timeout
    # is deliberately more generous than the connect timeout.
    integration_connect_timeout_seconds: float = _get_float("INTEGRATION_CONNECT_TIMEOUT_SECONDS", 3.0)
    integration_timeout_seconds: float = _get_float("INTEGRATION_TIMEOUT_SECONDS", 10.0)
    integration_max_retries: int = _get_int("INTEGRATION_MAX_RETRIES", 2)
    integration_retry_backoff_seconds: float = _get_float(
        "INTEGRATION_RETRY_BACKOFF_SECONDS", 0.5
    )


settings = Settings()
