"""Integration orchestration for Person A.

A is the integration CONSUMER: it pulls data from
  - Person B (subscription tracker) via GET /integration/export
  - Person C (smart home energy) via GET /history?months=6

Hard rules implemented here:
- communication is real HTTP REST only; A never reads B's or C's database;
- every import is idempotent thanks to a stable external identifier
  ("B:<external_ref>:<month>" / "C:<basis>:<month>") with a UNIQUE
  constraint on expenses.external_id - re-running a sync never duplicates;
- zero values vs missing data vs unavailable services are distinguished;
- a partial failure of one source never blocks the other source, and it
  never turns into a 500 for the caller.
"""
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from config import settings
from crud import create_expense, get_expense_by_external_id
from services.integration_client import fetch_json

B_EXPORT_KEYS = ("service", "subscriptions")
C_HISTORY_KEYS = ("months",)


def _month_of(day: date) -> str:
    return day.strftime("%Y-%m")


def _first_day(month: str) -> date:
    year, mon = (int(part) for part in month.split("-"))
    return date(year, mon, 1)


# ------------------------------------------------------------------ Person B
def _sync_subscription_tracker(db: Session, sync_month: str) -> dict:
    source = "subscription_tracker"
    if not settings.integration_b_base_url:
        return {"source": source, "status": "not_configured", "imported": 0, "skipped": 0}

    payload, error, kind = fetch_json(
        "GET",
        f"{settings.integration_b_base_url}/integration/export",
        timeout=settings.integration_timeout_seconds,
        max_retries=settings.integration_max_retries,
        backoff_seconds=settings.integration_retry_backoff_seconds,
        expected_keys=B_EXPORT_KEYS,
    )
    if kind != "ok":
        return {"source": source, "status": kind, "error": error, "imported": 0, "skipped": 0}

    subscriptions = payload.get("subscriptions")
    if not isinstance(subscriptions, list):
        return {
            "source": source,
            "status": "invalid_response",
            "error": "subscriptions is not a list",
            "imported": 0,
            "skipped": 0,
        }

    imported = skipped = 0
    details: list[dict] = []
    for entry in subscriptions:
        if not isinstance(entry, dict):
            skipped += 1
            details.append({"external_ref": None, "action": "skipped_malformed_entry"})
            continue
        external_ref = entry.get("external_ref")
        name = entry.get("name")
        monthly_cost = entry.get("monthly_cost")

        if entry.get("active") is False:
            skipped += 1
            details.append({"external_ref": external_ref, "action": "skipped_inactive"})
            continue
        if not external_ref or not name or not isinstance(monthly_cost, (int, float)) or monthly_cost <= 0:
            skipped += 1
            details.append({"external_ref": external_ref, "action": "skipped_invalid_payload"})
            continue

        external_id = f"B:{external_ref}:{sync_month}"
        if get_expense_by_external_id(db, external_id):
            skipped += 1
            details.append({"external_ref": external_ref, "action": "already_imported"})
            continue

        create_expense(
            db,
            expense_date=_first_day(sync_month),
            merchant=str(name),
            amount=round(float(monthly_cost), 2),
            category_name="Subscriptions",
            description=f"Synced from subscription-tracker ({external_ref})",
            source="integration",
            external_id=external_id,
        )
        imported += 1
        details.append({"external_ref": external_ref, "action": "imported"})

    status = "ok" if imported or skipped else "empty"
    return {"source": source, "status": status, "imported": imported, "skipped": skipped, "details": details}


# ------------------------------------------------------------------ Person C
def _pick_energy_history_entry(history: list) -> tuple[Optional[dict], Optional[str]]:
    """Choose which C history month to import.

    Preference: the most recent month with an ACTUAL recorded bill; if none,
    the most recent completed month (< current month) that has an estimate.
    Returns (entry, basis) where basis is "actual" | "estimated" | None.
    """
    current_month = _month_of(date.today())
    if not isinstance(history, list):
        return None, None

    for entry in history:  # history is ordered most-recent-first
        if not isinstance(entry, dict) or not entry.get("month"):
            continue
        if isinstance(entry.get("actual_amount"), (int, float)) and entry["actual_amount"] > 0:
            return entry, "actual"

    for entry in history:
        if not isinstance(entry, dict) or not entry.get("month"):
            continue
        if entry["month"] >= current_month:
            continue  # current month still running - estimate not settled
        if isinstance(entry.get("estimated_amount"), (int, float)) and entry["estimated_amount"] > 0:
            return entry, "estimated"
    return None, None


def _sync_smart_home_energy(db: Session) -> dict:
    source = "smart_home_energy"
    if not settings.integration_c_base_url:
        return {"source": source, "status": "not_configured", "imported": 0, "skipped": 0}

    payload, error, kind = fetch_json(
        "GET",
        f"{settings.integration_c_base_url}/history",
        params={"months": 6},
        timeout=settings.integration_timeout_seconds,
        max_retries=settings.integration_max_retries,
        backoff_seconds=settings.integration_retry_backoff_seconds,
        expected_keys=C_HISTORY_KEYS,
    )
    if kind != "ok":
        return {"source": source, "status": kind, "error": error, "imported": 0, "skipped": 0}

    entry, basis = _pick_energy_history_entry(payload.get("months") or [])
    if entry is None:
        return {
            "source": source,
            "status": "empty",
            "imported": 0,
            "skipped": 0,
            "error": "no settled bill and no closed-month estimate available yet",
        }

    month = entry["month"]
    amount = float(entry["actual_amount"] if basis == "actual" else entry["estimated_amount"])
    external_id = f"C:{basis}:{month}"
    if get_expense_by_external_id(db, external_id):
        return {
            "source": source,
            "status": "ok",
            "imported": 0,
            "skipped": 1,
            "basis": basis,
            "details": [{"external_ref": external_id, "action": "already_imported"}],
        }

    create_expense(
        db,
        expense_date=_first_day(month),
        merchant=f"Electricity bill {month}",
        amount=round(amount, 2),
        category_name="Bills",
        description=(
            f"Synced from smart-home-energy-monitor ({basis} bill for {month}; "
            "estimate is derived from configured tariff slabs)"
        ),
        source="integration",
        external_id=external_id,
    )
    return {
        "source": source,
        "status": "ok",
        "imported": 1,
        "skipped": 0,
        "basis": basis,
        "details": [{"external_ref": external_id, "action": "imported"}],
    }


# -------------------------------------------------------------------- public
def sync_all(db: Session) -> dict:
    """Run both pulls; each source is isolated - one failing never blocks the other."""
    today_month = _month_of(date.today())
    results = [
        _sync_subscription_tracker(db, today_month),
        _sync_smart_home_energy(db),
    ]
    statuses = {result["status"] for result in results}
    if all(status in {"not_configured", "unavailable", "invalid_response"} for status in statuses):
        overall = "failed"
    elif any(status in {"not_configured", "unavailable", "invalid_response", "empty"} for status in statuses):
        overall = "partial"
    else:
        overall = "ok"
    return results, overall


def build_status_report() -> tuple[list[dict], str]:
    """Probe B and C /health endpoints for the status dashboard."""
    from services.integration_client import check_service_health

    peers = [
        ("subscription_tracker", "Person B - Subscription Cost Tracker", settings.integration_b_base_url),
        ("smart_home_energy", "Person C - Smart Home Energy Monitor", settings.integration_c_base_url),
    ]
    services: list[dict] = []
    for key, label, base_url in peers:
        payload, error, kind, latency_ms = check_service_health(
            base_url, timeout=settings.integration_timeout_seconds
        )
        # fetch_json reports "ok" for a successful call; the status contract
        # exposes that as "available".
        status = "available" if kind == "ok" else kind
        peer_name = peer_version = None
        if kind == "ok" and isinstance(payload, dict):
            peer_name = payload.get("service")
            peer_version = payload.get("version")
        services.append(
            {
                "service_key": key,
                "base_url": base_url or None,
                "status": status,
                "peer_service_name": peer_name or (label if status == "not_configured" else None),
                "peer_version": peer_version,
                "latency_ms": latency_ms if status == "available" else None,
                "error": error,
            }
        )
    from datetime import datetime, timezone

    return services, datetime.now(timezone.utc).isoformat()
