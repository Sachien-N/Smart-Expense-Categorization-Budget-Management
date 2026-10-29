"""Core API tests for Person A: health, categories, expenses, budgets, summary, categorizer."""
import pytest

MONTH = "2025-07"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "expense-budget-api"
    assert body["database"] == "connected"


def test_canonical_categories_seeded(client):
    response = client.get("/categories")
    assert response.status_code == 200
    names = {item["name"] for item in response.json()}
    assert {"Food", "Travel", "Bills", "Entertainment", "Shopping", "Subscriptions", "Uncategorized"} <= names


def test_create_expense_auto_categorization(client):
    """Merchant 'Netflix' must land in Subscriptions (priority rule order)."""
    response = client.post(
        "/expenses",
        json={"merchant": "Netflix", "amount": 199.0, "expense_date": f"{MONTH}-05"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["category"] == "Subscriptions"
    assert body["source"] == "manual"
    assert body["external_id"] is None


def test_create_expense_with_explicit_category(client):
    response = client.post(
        "/expenses",
        json={"merchant": "A2B Restaurant", "amount": 340.0, "expense_date": f"{MONTH}-06", "category": "Food"},
    )
    assert response.status_code == 201
    assert response.json()["category"] == "Food"


def test_create_expense_rejects_nonpositive_amount(client):
    response = client.post("/expenses", json={"merchant": "X", "amount": 0})
    assert response.status_code == 422


def test_create_expense_fallback_category(client):
    response = client.post(
        "/expenses",
        json={"merchant": "Zyx Unknown Shop 42", "amount": 10.0, "expense_date": f"{MONTH}-07"},
    )
    assert response.status_code == 201
    assert response.json()["category"] == "Uncategorized"


def test_list_filter_and_get_by_id(client):
    client.post("/expenses", json={"merchant": "Uber", "amount": 120.0, "expense_date": f"{MONTH}-08"})
    listed = client.get("/expenses", params={"month": MONTH, "category": "Travel"}).json()
    assert any(item["merchant"] == "Uber" for item in listed)

    expense_id = listed[0]["id"]
    fetched = client.get(f"/expenses/{expense_id}")
    assert fetched.status_code == 200
    assert fetched.json()["merchant"] == "Uber"


def test_get_missing_expense_returns_404(client):
    assert client.get("/expenses/99999").status_code == 404


def test_update_and_delete_expense(client):
    created = client.post(
        "/expenses", json={"merchant": "Kiosk", "amount": 25.0, "expense_date": f"{MONTH}-09"}
    ).json()
    updated = client.put(f"/expenses/{created['id']}", json={"amount": 30.5})
    assert updated.status_code == 200
    assert updated.json()["amount"] == 30.5

    deleted = client.delete(f"/expenses/{created['id']}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True, "id": created["id"]}
    assert client.get(f"/expenses/{created['id']}").status_code == 404


def test_categorize_endpoint(client):
    response = client.get("/categorize", params={"merchant": "Swiggy dinner order"})
    assert response.status_code == 200
    body = response.json()
    assert body["suggested_category"] == "Food"
    assert body["confidence"] == "rule"
    assert body["matched_keyword"]


def test_categorize_endpoint_fallback(client):
    body = client.get("/categorize", params={"merchant": "totally-unknown-merchant"}).json()
    assert body["suggested_category"] == "Uncategorized"
    assert body["confidence"] == "fallback"
    assert body["matched_keyword"] is None


def test_category_detail_unknown_returns_404(client):
    assert client.get("/category/DoesNotExist").status_code == 404


def test_category_detail_totals(client):
    detail = client.get("/category/Food").json()
    assert detail["category"] == "Food"
    assert detail["expense_count"] >= 1
    assert detail["total_amount"] > 0


def test_budget_crud_and_duplicate_conflict(client):
    created = client.post(
        "/budgets", json={"category": "Travel", "month": MONTH, "amount_limit": 500.0}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["category"] == "Travel"
    assert body["spent"] > 0  # Uber expense created earlier in this file
    assert body["over_budget"] is (body["spent"] > 500.0)

    duplicate = client.post(
        "/budgets", json={"category": "Travel", "month": MONTH, "amount_limit": 900.0}
    )
    assert duplicate.status_code == 409


def test_budget_month_format_validated(client):
    bad = client.post("/budgets", json={"category": "Food", "month": "2025/07", "amount_limit": 100.0})
    assert bad.status_code == 422


def test_summary_endpoint(client):
    response = client.get("/summary", params={"month": MONTH})
    assert response.status_code == 200
    body = response.json()
    assert body["month"] == MONTH
    assert body["total_expenses"] > 0
    assert body["transaction_count"] >= 3
    shares = {row["category"]: row for row in body["by_category"]}
    assert "Subscriptions" in shares
    assert any(row["category"] == "Travel" for row in body["budget_comparison"])


def test_summary_empty_month_is_valid_zero(client):
    response = client.get("/summary", params={"month": "1999-01"})
    assert response.status_code == 200
    body = response.json()
    assert body["total_expenses"] == 0.0
    assert body["transaction_count"] == 0
    assert body["by_category"] == []
