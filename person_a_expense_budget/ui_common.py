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
