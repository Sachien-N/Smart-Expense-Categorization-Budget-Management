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

    def fake_check(base_url, *, timeout):
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
    """First sync imports B subs + C closed-month estimate; second skips all."""
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
    assert c_first["imported"] == 1
    assert c_first["basis"] == "actual"  # June has an actual bill -> preferred
    assert c_first["status"] == "ok"

    # Rows really landed as expenses with the right categories/amounts.
    subs = client.get("/expenses", params={"category": "Subscriptions", "source": "integration"}).json()
    assert {e["amount"] for e in subs} == {199.0, 1000.0}
    bills = client.get("/expenses", params={"category": "Bills", "source": "integration"}).json()
    assert any(e["amount"] == 305.0 for e in bills)

    # Idempotency: same external ids -> everything skipped, nothing duplicated.
    second = client.post("/integrations/sync").json()
    b_second = next(r for r in second["results"] if r["source"] == "subscription_tracker")
    c_second = next(r for r in second["results"] if r["source"] == "smart_home_energy")
    assert b_second["imported"] == 0
    assert b_second["skipped"] == 2
    assert c_second["imported"] == 0
    assert c_second["skipped"] == 1

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
