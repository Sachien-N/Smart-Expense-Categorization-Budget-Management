"""Integration-layer tests for Person A.

Covers: status probing (not configured / available), graceful degradation when
a peer is DOWN (connection refused), contract validation (wrong payload shape),
and idempotent imports using stable external identifiers.
"""
import pytest

TEST_MONTH = "2025-07"

B_EXPORT = {
    "service": "subscription-cost-tracker",
    "contract_version": "1.0",
    "generated_at": "2025-07-01T00:00:00Z",
    "subscriptions": [
        {
            "external_ref": "B-SUB-1",
            "name": "Netflix Premium",
            "category": "Streaming",
            "tags": ["family", "ott"],
            "billing_frequency": "monthly",
            "amount": 199.0,
            "monthly_cost": 199.0,
            "currency": "INR",
            "active": True,
            "next_renewal_date": "2025-07-15",
        },
        {
            "external_ref": "B-SUB-2",
            "name": "Adobe CC",
            "category": "Software",
            "tags": ["design"],
            "billing_frequency": "yearly",
            "amount": 12000.0,
            "monthly_cost": 1000.0,
            "currency": "INR",
            "active": True,
            "next_renewal_date": "2026-01-10",
        },
    ],
}

C_HISTORY = {
    "months": [
        {"month": "2025-07", "estimated_kwh": 120.0, "actual_kwh": None,
         "estimated_amount": 211.5, "actual_amount": None, "deviation_percent": None},
        {"month": "2025-06", "estimated_kwh": 150.0, "actual_kwh": 148.0,
         "estimated_amount": 299.75, "actual_amount": 305.0, "deviation_percent": 1.72},
    ]
}


@pytest.fixture()
def configure_peers(monkeypatch):
    """Point both peers at dead ports so 'unavailable' paths are exercised."""
    from config import settings

    monkeypatch.setattr(settings, "integration_b_base_url", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "integration_c_base_url", "http://127.0.0.1:9")
    return settings


def test_status_not_configured(client):
    response = client.get("/integrations/status")
    assert response.status_code == 200
    body = response.json()
    by_key = {svc["service_key"]: svc for svc in body["services"]}
    assert by_key["subscription_tracker"]["status"] == "not_configured"
    assert by_key["smart_home_energy"]["status"] == "not_configured"


def test_status_reports_available_peers(client, monkeypatch):
    """Both peers healthy -> status 'available' with latency and peer metadata."""
    from config import settings
    import services.integration_client as integration_client

    def fake_check(base_url, *, timeout, connect_timeout=None):
        return (
            {"status": "ok", "service": "peer", "version": "1.0.0",
             "database": "connected", "time": "2025-07-01T00:00:00Z"},
            None,
            "ok",
            4.2,
        )

    monkeypatch.setattr(settings, "integration_b_base_url", "http://peer-b.test")
    monkeypatch.setattr(settings, "integration_c_base_url", "http://peer-c.test")
    monkeypatch.setattr(integration_client, "check_service_health", fake_check)

    response = client.get("/integrations/status")
    assert response.status_code == 200
    by_key = {svc["service_key"]: svc for svc in response.json()["services"]}
    assert by_key["subscription_tracker"]["status"] == "available"
    assert by_key["subscription_tracker"]["latency_ms"] == 4.2
    assert by_key["subscription_tracker"]["peer_version"] == "1.0.0"
    assert by_key["smart_home_energy"]["status"] == "available"


def test_sync_when_peers_down_is_graceful(client, configure_peers):
    """A peer being down must NOT produce a 500 - only per-source status."""
    response = client.post("/integrations/sync")
    assert response.status_code == 200
    body = response.json()
    assert body["overall"] == "failed"
    assert all(result["status"] == "unavailable" for result in body["results"])


def test_sync_invalid_response_is_flagged(client, monkeypatch):
    """A peer answering with a foreign payload is reported, never imported."""
    from config import settings
    import services.integration_service as integration_service

    monkeypatch.setattr(settings, "integration_b_base_url", "http://peer-b.test")
    monkeypatch.setattr(
        integration_service,
        "fetch_json",
        lambda *args, **kwargs: ({"unexpected": True}, None, "ok"),
    )
    response = client.post("/integrations/sync")
    assert response.status_code == 200
    b_result = next(r for r in response.json()["results"] if r["source"] == "subscription_tracker")
    assert b_result["status"] == "invalid_response"


def test_sync_imports_and_is_idempotent(client, monkeypatch):
    """First sync imports B subs + both settled C months; second skips all."""
    from config import settings
    import services.integration_service as integration_service

    def fake_fetch_json(method, url, **kwargs):
        if "/integration/export" in url:
            return B_EXPORT, None, "ok"
        if "/history" in url:
            return C_HISTORY, None, "ok"
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(settings, "integration_b_base_url", "http://peer-b.test")
    monkeypatch.setattr(settings, "integration_c_base_url", "http://peer-c.test")
    monkeypatch.setattr(integration_service, "fetch_json", fake_fetch_json)

    first = client.post("/integrations/sync").json()
    assert first["overall"] in {"ok", "partial"}
    b_first = next(r for r in first["results"] if r["source"] == "subscription_tracker")
    c_first = next(r for r in first["results"] if r["source"] == "smart_home_energy")
    assert b_first["imported"] == 2  # Netflix 199 + Adobe monthly-equivalent 1000
    # 2025-07 is a closed month with only an estimate; 2025-06 has an actual bill.
    assert c_first["imported"] == 2
    assert c_first["status"] == "ok"
    by_ref = {d["external_ref"]: d for d in c_first["details"]}
    assert by_ref["C:2025-06"]["basis"] == "actual"
    assert by_ref["C:2025-07"]["basis"] == "estimated"

    # Rows really landed as expenses with the right categories/amounts.
    subs = client.get("/expenses", params={"category": "Subscriptions", "source": "integration"}).json()
    assert {e["amount"] for e in subs} == {199.0, 1000.0}
    bills = client.get("/expenses", params={"category": "Bills", "source": "integration"}).json()
    by_ext = {e["external_id"]: e for e in bills}
    assert by_ext["C:2025-06"]["amount"] == 305.0
    assert by_ext["C:2025-06"]["import_basis"] == "actual"
    assert by_ext["C:2025-06"]["origin"] == "smart_home_energy"
    assert by_ext["C:2025-07"]["import_basis"] == "estimated"
    assert subs[0]["origin"] == "subscription_tracker"

    # Idempotency: same external ids -> everything skipped, nothing duplicated.
    second = client.post("/integrations/sync").json()
    b_second = next(r for r in second["results"] if r["source"] == "subscription_tracker")
    c_second = next(r for r in second["results"] if r["source"] == "smart_home_energy")
    assert b_second["imported"] == 0
    assert b_second["skipped"] == 2
    assert c_second["imported"] == 0
    assert c_second["updated"] == 0
    assert c_second["skipped"] == 2

    subs_after = client.get("/expenses", params={"category": "Subscriptions", "source": "integration"}).json()
    assert len(subs_after) == 2


def test_sync_skips_inactive_and_malformed(client, monkeypatch):
    from config import settings
    import services.integration_service as integration_service

    payload = {
        "service": "subscription-cost-tracker",
        "subscriptions": [
            {"external_ref": "B-SUB-9", "name": "Old Service", "monthly_cost": 99.0, "active": False},
            {"external_ref": None, "name": "Broken", "monthly_cost": 10.0, "active": True},
            {"external_ref": "B-SUB-10", "name": "Zero Cost", "monthly_cost": 0, "active": True},
        ],
    }
    monkeypatch.setattr(settings, "integration_b_base_url", "http://peer-b.test")
    monkeypatch.setattr(settings, "integration_c_base_url", "")
    monkeypatch.setattr(
        integration_service,
        "fetch_json",
        lambda *args, **kwargs: (payload, None, "ok"),
    )
    result = client.post("/integrations/sync").json()
    b_result = next(r for r in result["results"] if r["source"] == "subscription_tracker")
    assert b_result["imported"] == 0
    assert b_result["skipped"] == 3


# --------------------------------------------------------------------------
# Synchronization semantics added in v1.1
# --------------------------------------------------------------------------
def _sync_with(client, monkeypatch, *, b_payload=None, c_payload=None):
    from config import settings
    import services.integration_service as integration_service

    def fake_fetch_json(method, url, **kwargs):
        if "/integration/export" in url:
            return b_payload, None, "ok"
        if "/history" in url:
            return c_payload, None, "ok"
        raise AssertionError(url)

    monkeypatch.setattr(settings, "integration_b_base_url", "http://peer-b.test" if b_payload else "")
    monkeypatch.setattr(settings, "integration_c_base_url", "http://peer-c.test" if c_payload else "")
    monkeypatch.setattr(integration_service, "fetch_json", fake_fetch_json)
    return client.post("/integrations/sync").json()


def _result(body, source):
    return next(r for r in body["results"] if r["source"] == source)


def _bills_for(client, external_id):
    rows = client.get("/expenses", params={"category": "Bills", "source": "integration", "limit": 200}).json()
    return [e for e in rows if e["external_id"] == external_id]


def test_estimate_is_upgraded_to_actual_without_double_counting(client, monkeypatch):
    month = "2024-03"
    estimate_only = {"months": [{"month": month, "estimated_amount": 410.0, "actual_amount": None}]}
    first = _result(_sync_with(client, monkeypatch, c_payload=estimate_only), "smart_home_energy")
    assert first["imported"] == 1
    assert _bills_for(client, f"C:{month}")[0]["import_basis"] == "estimated"

    with_actual = {"months": [{"month": month, "estimated_amount": 410.0, "actual_amount": 455.5}]}
    second = _result(_sync_with(client, monkeypatch, c_payload=with_actual), "smart_home_energy")
    assert second["imported"] == 0
    assert second["updated"] == 1
    assert second["details"][0]["action"] == "upgraded_estimate_to_actual"

    rows = _bills_for(client, f"C:{month}")
    assert len(rows) == 1  # one row per month: estimate replaced, not added to
    assert rows[0]["amount"] == 455.5
    assert rows[0]["import_basis"] == "actual"

    summary = client.get("/summary", params={"month": month}).json()
    electricity = next(s for s in summary["by_source"] if s["origin"] == "smart_home_energy")
    assert electricity == {"origin": "smart_home_energy", "total": 455.5, "count": 1}


def test_running_month_estimate_is_not_imported(client, monkeypatch):
    from datetime import date

    current = date.today().strftime("%Y-%m")
    payload = {"months": [{"month": current, "estimated_amount": 99.0, "actual_amount": None}]}
    result = _result(_sync_with(client, monkeypatch, c_payload=payload), "smart_home_energy")
    assert result["status"] == "empty"
    assert _bills_for(client, f"C:{current}") == []


def test_legacy_v1_electricity_ids_are_migrated_not_duplicated(client, monkeypatch):
    from crud import create_expense
    from database import SessionLocal

    month = "2024-01"
    db = SessionLocal()
    try:
        create_expense(
            db, expense_date=__import__("datetime").date(2024, 1, 1), merchant=f"Electricity bill {month}",
            amount=300.0, category_name="Bills", source="integration", external_id=f"C:actual:{month}",
        )
    finally:
        db.close()
    payload = {"months": [{"month": month, "estimated_amount": 280.0, "actual_amount": 300.0}]}
    result = _result(_sync_with(client, monkeypatch, c_payload=payload), "smart_home_energy")
    assert result["imported"] == 0
    rows = client.get("/expenses", params={"month": month, "source": "integration"}).json()
    assert [r["external_id"] for r in rows] == [f"C:{month}"]


def test_manual_electricity_expense_blocks_import(client):
    from datetime import date
    from unittest import mock

    month = "2024-02"
    manual = client.post(
        "/expenses", json={"merchant": "TNEB electricity", "amount": 520.0, "expense_date": f"{month}-14"}
    ).json()
    assert manual["origin"] == "manual" and manual["category"] == "Bills"
    payload = {"months": [{"month": month, "estimated_amount": 500.0, "actual_amount": 520.0}]}
    with mock.patch("services.integration_service.date") as fake_date:
        fake_date.today.return_value = date(2024, 6, 1)
        fake_date.side_effect = lambda *a, **k: date(*a, **k)
        from config import settings
        import services.integration_service as integration_service

        with mock.patch.object(settings, "integration_c_base_url", "http://peer-c.test"), \
                mock.patch.object(settings, "integration_b_base_url", ""), \
                mock.patch.object(integration_service, "fetch_json", lambda *a, **k: (payload, None, "ok")):
            body = client.post("/integrations/sync").json()
    result = _result(body, "smart_home_energy")
    assert result["details"][0]["action"] == "skipped_manual_duplicate"
    assert _bills_for(client, f"C:{month}") == []


def test_subscription_price_change_updates_same_row(client, monkeypatch):
    def export(amount):
        return {"service": "subscription-cost-tracker", "subscriptions": [
            {"external_ref": "B-SUB-77", "name": "Spotify Duo", "monthly_cost": amount, "amount": amount,
             "billing_frequency": "monthly", "currency": "INR", "active": True},
        ]}

    first = _result(_sync_with(client, monkeypatch, b_payload=export(149.0)), "subscription_tracker")
    assert first["imported"] == 1
    second = _result(_sync_with(client, monkeypatch, b_payload=export(179.0)), "subscription_tracker")
    assert second["imported"] == 0 and second["updated"] == 1
    rows = [e for e in client.get("/expenses", params={"source": "integration", "limit": 200}).json()
            if e["external_id"] and e["external_id"].startswith("B:B-SUB-77:")]
    assert len(rows) == 1 and rows[0]["amount"] == 179.0
    assert rows[0]["import_basis"] == "monthly_normalized"


def test_manual_subscription_expense_blocks_import(client, monkeypatch):
    from datetime import date

    client.post("/expenses", json={"merchant": "Zee5 Premium", "amount": 99.0,
                                   "expense_date": date.today().isoformat()})
    payload = {"service": "subscription-cost-tracker", "subscriptions": [
        {"external_ref": "B-SUB-88", "name": "Zee5", "monthly_cost": 99.0, "amount": 99.0,
         "currency": "INR", "active": True},
    ]}
    result = _result(_sync_with(client, monkeypatch, b_payload=payload), "subscription_tracker")
    assert result["imported"] == 0
    assert result["details"][0]["action"] == "skipped_manual_duplicate"


def test_non_inr_subscription_is_skipped(client, monkeypatch):
    payload = {"service": "subscription-cost-tracker", "subscriptions": [
        {"external_ref": "B-SUB-99", "name": "Foreign SaaS", "monthly_cost": 20.0, "currency": "USD", "active": True},
    ]}
    result = _result(_sync_with(client, monkeypatch, b_payload=payload), "subscription_tracker")
    assert result["imported"] == 0
    assert result["details"][0]["action"] == "skipped_unsupported_currency"


def test_misconfigured_url_is_reported(client, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "integration_b_base_url", "peer-b-without-scheme")
    monkeypatch.setattr(settings, "integration_c_base_url", "")
    status = {s["service_key"]: s for s in client.get("/integrations/status").json()["services"]}
    assert status["subscription_tracker"]["status"] == "misconfigured"
    sync = _result(client.post("/integrations/sync").json(), "subscription_tracker")
    assert sync["status"] == "misconfigured"
