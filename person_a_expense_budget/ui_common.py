"""Google Apps Script adapter for Person A's Streamlit expense app.

Streamlit Community Cloud secrets required:
    API_URL = "https://script.google.com/macros/s/YOUR_DEPLOYMENT_ID/exec"
    API_SECRET = "your_rotated_secret"

Apps Script must accept GET ?key=...&type=... and POST JSON:
{"key": "...", "type": "expenses|budgets", "id": "...", "data": {...}}

Records sheet columns: type | id | data | updatedAt
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timezone
from typing import Any, Optional
from urllib.parse import unquote

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8001"
DEFAULT_TIMEOUT = (10, 30)
_CONFIG: dict[str, str] = {"secret": ""}
_SESSION = requests.Session()
_SESSION.headers.update({"Accept": "application/json"})

CATEGORIES = [
    {"id": 1, "name": "Food", "description": "Meals, groceries and food delivery", "is_active": True},
    {"id": 2, "name": "Travel", "description": "Transport, fuel and travel", "is_active": True},
    {"id": 3, "name": "Bills", "description": "Utilities, rent and recurring bills", "is_active": True},
    {"id": 4, "name": "Entertainment", "description": "Movies, events and leisure", "is_active": True},
    {"id": 5, "name": "Shopping", "description": "Retail and personal purchases", "is_active": True},
    {"id": 6, "name": "Subscriptions", "description": "Streaming and software subscriptions", "is_active": True},
    {"id": 7, "name": "Uncategorized", "description": "Expenses without a matching rule", "is_active": True},
]

CATEGORY_RULES = [
    ("Subscriptions", ["netflix", "spotify", "prime", "hotstar", "jiocinema", "sonyliv", "zee5",
                       "youtube premium", "adobe", "microsoft 365", "office 365", "icloud", "google one",
                       "canva", "chatgpt", "notion", "subscription"]),
    ("Entertainment", ["bookmyshow", "pvr", "inox", "cinema", "movie", "steam", "playstation",
                       "xbox", "amusement", "concert", "event"]),
    ("Food", ["swiggy", "zomato", "restaurant", "cafe", "coffee", "starbucks", "domino", "pizza",
              "burger", "kfc", "mcdonald", "dunzo", "grocery", "supermarket", "aavin", "bakery", "food"]),
    ("Travel", ["uber", "ola", "rapido", "irctc", "redbus", "abhibus", "indigo", "air india",
                "metro", "petrol", "fuel", "toll", "fastag", "parking"]),
    ("Bills", ["electricity", "tneb", "tangedco", "water bill", "gas bill", "broadband", "act fibernet",
               "jiofiber", "airtel", "recharge", "mobile bill", "rent", "maintenance"]),
    ("Shopping", ["amazon", "flipkart", "myntra", "ajio", "nykaa", "decathlon", "croma",
                  "reliance digital", "vijay sales", "ikea", "pepperfry", "shopping", "mall", "tata cliq"]),
]


def _secret(secrets: Any, key: str) -> str:
    try:
        return str(secrets.get(key, "") or "").strip() if secrets is not None else ""
    except Exception:
        return ""


def resolve_api_base_url(secrets: Any = None, default: str = DEFAULT_BASE_URL) -> str:
    """Resolve Apps Script URL from API_URL, retaining local API_BASE_URL support."""
    value = (os.getenv("API_URL") or os.getenv("API_BASE_URL") or "").strip()
    if not value:
        value = _secret(secrets, "API_URL") or _secret(secrets, "API_BASE_URL")
    return (value or default).rstrip("/")


def configure(secrets: Any = None) -> None:
    """Call configure(st.secrets) once in app.py."""
    _CONFIG["secret"] = os.getenv("API_SECRET", "").strip() or _secret(secrets, "API_SECRET")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _categorize(merchant: str) -> tuple[str, Optional[str], str]:
    text = (merchant or "").strip().lower()
    for category, keywords in CATEGORY_RULES:
        for keyword in keywords:
            if keyword in text:
                return category, keyword, "rule"
    return "Uncategorized", None, "fallback"


def _apps_request(method: str, base_url: str, record_type: str, record_id: str = "",
                  data: Any = None) -> tuple[bool, Any]:
    if not base_url.startswith(("https://", "http://")):
        return False, "Invalid API URL. Set API_URL in Streamlit Secrets."
    key = _CONFIG.get("secret", "")
    if not key:
        return False, "API_SECRET is missing. Add it under Streamlit Community Cloud → App settings → Secrets."
    try:
        if method == "GET":
