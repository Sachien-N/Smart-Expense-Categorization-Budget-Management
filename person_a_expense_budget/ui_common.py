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
            response = _SESSION.get(base_url, params={"key": key, "type": record_type},
                                    timeout=DEFAULT_TIMEOUT)
        else:
            response = _SESSION.post(
                base_url,
                json={"key": key, "type": record_type, "id": str(record_id), "data": data},
                timeout=DEFAULT_TIMEOUT,
            )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or result.get("ok") is not True:
            return False, str(result.get("error", result) if isinstance(result, dict) else result)
        return True, result
    except requests.Timeout:
        return False, "Google Apps Script timed out. Please retry."
    except (requests.RequestException, ValueError) as exc:
        return False, f"Google Apps Script request failed ({exc.__class__.__name__}). Check API_URL and deployment access."


def _records(base_url: str, kind: str) -> tuple[bool, Any]:
    ok, response = _apps_request("GET", base_url, kind)
    if not ok:
        return False, response
    rows = response.get("records", [])
    if not isinstance(rows, list):
        return False, "Apps Script response 'records' must be a list."
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        data = row.get("data", {})
        if isinstance(data, str):
            try:
                import json
                data = json.loads(data)
            except (ValueError, TypeError):
                data = {}
        if not isinstance(data, dict):
            data = {}
        data = dict(data)
        data.setdefault("id", row.get("id", ""))
        data.setdefault("updated_at", row.get("updatedAt"))
        result.append(data)
    return True, result


def _save(base_url: str, kind: str, record_id: str, data: dict) -> tuple[bool, Any]:
    ok, result = _apps_request("POST", base_url, kind, record_id, data)
    if not ok:
        return False, result
    return True, result


def _visible_expenses(base_url: str) -> tuple[bool, Any]:
    ok, rows = _records(base_url, "expenses")
    if not ok:
        return False, rows
    visible = []
    for row in rows:
        if row.get("_deleted", False):
            continue
        try:
            row["id"] = int(row.get("id", 0))
            row["amount"] = float(row.get("amount", 0) or 0)
        except (TypeError, ValueError):
            continue
        row.setdefault("expense_date", date.today().isoformat())
        row.setdefault("merchant", "")
        row.setdefault("description", "")
        row.setdefault("category", "Uncategorized")
        row.setdefault("source", "manual")
        row.setdefault("origin", "manual")
        row.setdefault("external_id", None)
        row.setdefault("import_basis", None)
        row.setdefault("created_at", _now())
        visible.append(row)
    return True, visible


def _next_id(rows: list[dict]) -> int:
    ids = []
    for row in rows:
        try:
            ids.append(int(row.get("id", 0)))
        except (TypeError, ValueError):
            pass
    return max(ids, default=0) + 1


def _budgets(base_url: str) -> tuple[bool, Any]:
    ok, rows = _records(base_url, "budgets")
    if not ok:
        return False, rows
    return True, [row for row in rows if not row.get("_deleted", False)]


def _budget_out(budget: dict, expenses: list[dict]) -> dict:
    category, month = budget.get("category", ""), str(budget.get("month", ""))
    spent = round(sum(e["amount"] for e in expenses
                      if e["category"] == category and str(e["expense_date"])[:7] == month), 2)
    limit = float(budget.get("amount_limit", 0) or 0)
    remaining = round(limit - spent, 2)
    utilization = round(spent * 100 / limit, 2) if limit else 0.0
    return {"id": int(budget.get("id", 0) or 0), "category": category, "month": month,
            "amount_limit": limit, "spent": spent, "remaining": remaining,
            "utilization_percent": utilization, "over_budget": spent > limit}


def api_get(base_url: str, path: str, params: Optional[dict] = None) -> tuple[bool, Any]:
    params = params or {}
    route = path.split("?", 1)[0].rstrip("/") or "/"

    if route == "/categories":
        return True, CATEGORIES

    if route == "/categorize":
        merchant = str(params.get("merchant", ""))
        category, keyword, confidence = _categorize(merchant)
        return True, {"merchant": merchant, "suggested_category": category,
                      "matched_keyword": keyword, "confidence": confidence,
                      "reason": f"Matched keyword: {keyword}" if keyword else "No known merchant keyword matched."}

    if route == "/expenses":
        ok, rows = _visible_expenses(base_url)
        if not ok:
            return False, rows
        month, category, source = (str(params.get(k, "") or "") for k in ("month", "category", "source"))
        if month:
            rows = [e for e in rows if str(e["expense_date"])[:7] == month]
        if category:
            rows = [e for e in rows if e["category"] == category]
        if source:
            rows = [e for e in rows if e["source"] == source]
        try:
            limit = max(1, min(int(params.get("limit", 100)), 1000))
        except (ValueError, TypeError):
            limit = 100
        rows.sort(key=lambda e: (str(e["expense_date"]), int(e["id"])), reverse=True)
        return True, rows[:limit]

    if route == "/budgets":
        ok, budgets = _budgets(base_url)
        if not ok:
            return False, budgets
        ok, expenses = _visible_expenses(base_url)
        if not ok:
            return False, expenses
        month = str(params.get("month", "") or "")
        if month:
            budgets = [b for b in budgets if str(b.get("month", "")) == month]
        return True, [_budget_out(b, expenses) for b in budgets]

    if route == "/summary":
        month = str(params.get("month") or date.today().strftime("%Y-%m"))
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            return False, "Month must be in YYYY-MM format."
        ok, expenses = _visible_expenses(base_url)
        if not ok:
            return False, expenses
        expenses = [e for e in expenses if str(e["expense_date"])[:7] == month]
        total = round(sum(e["amount"] for e in expenses), 2)
        category_groups: dict[str, list] = {}
        source_groups: dict[str, list] = {}
        for e in expenses:
            category_groups.setdefault(e["category"], []).append(e)
            source_groups.setdefault(e["origin"], []).append(e)
        by_category = []
        for name, group in sorted(category_groups.items()):
            subtotal = round(sum(e["amount"] for e in group), 2)
            by_category.append({"category": name, "total": subtotal, "count": len(group),
                                "share_percent": round(subtotal * 100 / total, 2) if total else 0.0})
        by_source = [{"origin": name, "total": round(sum(e["amount"] for e in group), 2),
                      "count": len(group)} for name, group in sorted(source_groups.items())]
        ok, budgets = _budgets(base_url)
        if not ok:
            return False, budgets
        comparisons = []
        for budget in budgets:
            if str(budget.get("month", "")) == month:
                b = _budget_out(budget, expenses)
                comparisons.append({"category": b["category"], "budget": b["amount_limit"],
                                    "spent": b["spent"], "remaining": b["remaining"],
                                    "utilization_percent": b["utilization_percent"],
                                    "over_budget": b["over_budget"]})
        return True, {"month": month, "total_expenses": total, "transaction_count": len(expenses),
                      "by_category": by_category, "by_source": by_source,
                      "budget_comparison": comparisons}

    if route.startswith("/category/"):
        name = unquote(route[len("/category/"):])
        ok, expenses = _visible_expenses(base_url)
        if not ok:
            return False, expenses
        matched = [e for e in expenses if e["category"].lower() == name.lower()]
        matched.sort(key=lambda e: (str(e["expense_date"]), int(e["id"])), reverse=True)
        dates = [str(e["expense_date"])[:10] for e in matched]
        return True, {"category": name, "expense_count": len(matched),
                      "total_amount": round(sum(e["amount"] for e in matched), 2),
                      "first_expense_date": min(dates) if dates else None,
                      "last_expense_date": max(dates) if dates else None, "expenses": matched}

    if route == "/integrations/status":
        return True, {"checked_at": _now(), "services": [
            {"service_key": "subscription_tracker", "base_url": None, "status": "not_configured",
             "peer_service_name": "Person B Subscription Tracker", "peer_version": None,
             "latency_ms": None, "error": "Person B API integration is not connected."},
            {"service_key": "smart_home_energy", "base_url": None, "status": "not_configured",
             "peer_service_name": "Person C Electricity Manager", "peer_version": None,
             "latency_ms": None, "error": "Person C API integration is not connected."},
        ]}
    return False, f"Unsupported GET route: {path}"


def api_post(base_url: str, path: str, json_body: dict) -> tuple[bool, Any]:
    route = path.split("?", 1)[0].rstrip("/") or "/"
    body = json_body or {}

    if route == "/expenses":
        merchant = str(body.get("merchant", "")).strip()
        try:
            amount = float(body.get("amount", 0))
        except (TypeError, ValueError):
            amount = 0
        if not merchant:
            return False, "Merchant is required."
        if amount <= 0:
            return False, "Amount must be greater than zero."
        expense_date = str(body.get("expense_date") or date.today().isoformat())[:10]
        try:
            date.fromisoformat(expense_date)
        except ValueError:
            return False, "Expense date must use YYYY-MM-DD."
        category = str(body.get("category") or _categorize(merchant)[0])
        if category not in [c["name"] for c in CATEGORIES]:
            return False, f"Unknown category: {category}"
        ok, rows = _visible_expenses(base_url)
        if not ok:
            return False, rows
        record_id = str(_next_id(rows))
        record = {"id": int(record_id), "expense_date": expense_date, "merchant": merchant,
                  "description": str(body.get("description") or "").strip(), "amount": round(amount, 2),
                  "category": category, "source": "manual", "origin": "manual",
                  "external_id": body.get("external_id"), "import_basis": None,
                  "created_at": _now(), "_deleted": False}
        ok, result = _save(base_url, "expenses", record_id, record)
        if not ok:
            return False, result
        return True, {k: v for k, v in record.items() if not k.startswith("_")}

    if route == "/budgets":
        category = str(body.get("category", "")).strip()
        month = str(body.get("month", "")).strip()
        try:
            amount_limit = float(body.get("amount_limit", 0))
        except (TypeError, ValueError):
            amount_limit = 0
        if category not in [c["name"] for c in CATEGORIES]:
            return False, "Choose a valid category."
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            return False, "Month must be in YYYY-MM format."
        if amount_limit <= 0:
            return False, "Budget amount must be greater than zero."
        ok, rows = _budgets(base_url)
        if not ok:
            return False, rows
        if any(b.get("category") == category and b.get("month") == month for b in rows):
            return False, f"A budget already exists for {category} in {month}."
        record_id = str(_next_id(rows))
        record = {"id": int(record_id), "category": category, "month": month,
                  "amount_limit": round(amount_limit, 2), "_deleted": False}
        ok, result = _save(base_url, "budgets", record_id, record)
        if not ok:
            return False, result
        return True, record

    if route == "/integrations/sync":
        return True, {"synced_at": _now(), "overall": "failed", "results": [
            {"source": "subscription_tracker", "status": "not_configured", "imported": 0, "updated": 0,
             "skipped": 0, "error": "Person B API is not configured.", "details": []},
            {"source": "smart_home_energy", "status": "not_configured", "imported": 0, "updated": 0,
             "skipped": 0, "error": "Person C API is not configured.", "details": []},
        ]}
    return False, f"Unsupported POST route: {path}"


def api_put(base_url: str, path: str, json_body: dict) -> tuple[bool, Any]:
    return False, "Updating records is not supported by this adapter yet."


def api_delete(base_url: str, path: str) -> tuple[bool, Any]:
    match = re.fullmatch(r"/expenses/(\d+)/?", path)
    if not match:
        return False, f"Unsupported DELETE route: {path}"
    record_id = match.group(1)
    ok, rows = _records(base_url, "expenses")
    if not ok:
        return False, rows
    for row in rows:
        if str(row.get("id")) == record_id and not row.get("_deleted", False):
            row["_deleted"] = True
            ok, result = _save(base_url, "expenses", record_id, row)
            if not ok:
                return False, result
            return True, {"ok": True, "id": record_id, "deleted": True}
    return False, f"Expense #{record_id} was not found."


def money(value: Optional[float], currency: str = "INR") -> str:
    if value is None:
        return "-"
    return f"{currency} {value:,.2f}"
