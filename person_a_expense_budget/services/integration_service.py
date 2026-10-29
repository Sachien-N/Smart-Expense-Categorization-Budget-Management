"""Integration orchestration for Person A.

A is the integration CONSUMER: it pulls data from
  - Person B (subscription tracker) via GET /integration/export
  - Person C (smart home energy) via GET /history?months=6

Synchronization semantics (documented in README "Integration contract"):
- B: one SYNCHRONIZED row per active INR subscription per calendar month,
  identity "B:<external_ref>:<YYYY-MM>", amount = B's monthly-normalized
  cost (yearly 12000 -> 1000.00). A re-sync in the same month updates the
  amount if B's price changed; it never adds a second row.
- C: one SYNCHRONIZED row per electricity month, identity "C:<YYYY-MM>".
  A month is imported once it is settled: an ACTUAL bill always wins; a
  closed month without an actual bill is imported as an ESTIMATE and is
  upgraded in place when the actual bill is recorded later - estimate and
  actual are never both counted. import_basis records which one it is.
- A manual expense that already covers the same cost in the same month
  (same subscription name and amount / an electricity bill) blocks the
  import, so a cost typed by hand is not counted twice.

Hard rules implemented here:
- communication is real HTTP REST only; A never reads B's or C's database;
- the UNIQUE constraint on expenses.external_id backs up the identity check;
- zero values vs missing data vs unavailable services are distinguished;
- a partial failure of one source never blocks the other source, and it
  never turns into a 500 for the caller.
"""
import re
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import is_valid_base_url, settings
from crud import create_expense, get_expense_by_external_id, manual_expenses_in_month
from models import Expense
from services.integration_client import fetch_json

B_EXPORT_KEYS = ("service", "subscriptions")
C_HISTORY_KEYS = ("months",)
SUPPORTED_CURRENCY = "INR"
FAILURE_STATUSES = {"not_configured", "misconfigured", "unavailable", "timeout", "unauthorized", "invalid_response"}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
ELECTRICITY_KEYWORDS = ("electric", "tneb", "tangedco", "eb bill", "power bill")


def _month_of(day: date) -> str:
    return day.strftime("%Y-%m")


def _first_day(month: str) -> date:
    year, mon = (int(part) for part in month.split("-"))
    return date(year, mon, 1)


def _config_problem(source: str, base_url: str) -> Optional[dict]:
    if not base_url:
        return {"source": source, "status": "not_configured", "imported": 0, "skipped": 0}
    if not is_valid_base_url(base_url):
        return {
            "source": source,
            "status": "misconfigured",
            "error": "base URL must start with http:// or https://",
            "imported": 0,
            "skipped": 0,
        }
    return None


def _fetch(url: str, *, params: Optional[dict] = None, expected_keys: tuple[str, ...]):
    return fetch_json(
        "GET",
        url,
        params=params,
        timeout=settings.integration_timeout_seconds,
        connect_timeout=settings.integration_connect_timeout_seconds,
        max_retries=settings.integration_max_retries,
        backoff_seconds=settings.integration_retry_backoff_seconds,
        expected_keys=expected_keys,
    )


def _insert(db: Session, **fields) -> bool:
    """Create an imported expense; False if a concurrent sync won the race."""
    try:
        create_expense(db, source="integration", **fields)
    except IntegrityError:
        return False
    return True


def _update(db: Session, expense: Expense, **changes) -> None:
    for field, value in changes.items():
        setattr(expense, field, value)
    db.commit()


# ------------------------------------------------------------------ Person B
def _manual_subscription_duplicate(manual: list[Expense], name: str, amounts: set[float]) -> Optional[Expense]:
    needle = name.lower().strip()
    for expense in manual:
        merchant = expense.merchant.lower()
        if (needle in merchant or merchant in needle) and any(abs(expense.amount - a) < 0.01 for a in amounts):
            return expense
    return None


def _sync_subscription_tracker(db: Session, sync_month: str) -> dict:
    source = "subscription_tracker"
    problem = _config_problem(source, settings.integration_b_base_url)
    if problem:
        return problem

    payload, error, kind = _fetch(f"{settings.integration_b_base_url}/integration/export", expected_keys=B_EXPORT_KEYS)
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

    manual = manual_expenses_in_month(db, sync_month)
    imported = updated = skipped = 0
    details: list[dict] = []
    for entry in subscriptions:
        if not isinstance(entry, dict):
            skipped += 1
            details.append({"external_ref": None, "action": "skipped_malformed_entry"})
            continue
        external_ref = entry.get("external_ref")
        name = entry.get("name")
        monthly_cost = entry.get("monthly_cost")
        currency = entry.get("currency", SUPPORTED_CURRENCY)

        if entry.get("active") is False:
            skipped += 1
            details.append({"external_ref": external_ref, "action": "skipped_inactive"})
            continue
        if (
            not external_ref
            or not name
            or isinstance(monthly_cost, bool)
            or not isinstance(monthly_cost, (int, float))
            or monthly_cost <= 0
        ):
            skipped += 1
            details.append({"external_ref": external_ref, "action": "skipped_invalid_payload"})
            continue
        if currency != SUPPORTED_CURRENCY:
            # A's ledger is INR-only; converting would need an FX rate we do not have.
            skipped += 1
            details.append({"external_ref": external_ref, "action": "skipped_unsupported_currency", "currency": currency})
            continue

        amount = round(float(monthly_cost), 2)
        external_id = f"B:{external_ref}:{sync_month}"
        existing = get_expense_by_external_id(db, external_id)
        if existing:
            if abs(existing.amount - amount) >= 0.01:
                _update(db, existing, amount=amount, merchant=str(name))
                updated += 1
                details.append({"external_ref": external_ref, "action": "updated_amount", "amount": amount})
            else:
                skipped += 1
                details.append({"external_ref": external_ref, "action": "already_imported"})
            continue

        period_amount = entry.get("amount")
        amounts = {amount} | ({float(period_amount)} if isinstance(period_amount, (int, float)) else set())
        duplicate = _manual_subscription_duplicate(manual, str(name), amounts)
        if duplicate:
            skipped += 1
            details.append(
                {"external_ref": external_ref, "action": "skipped_manual_duplicate", "manual_expense_id": duplicate.id}
            )
            continue

        created = _insert(
            db,
            expense_date=_first_day(sync_month),
            merchant=str(name),
            amount=amount,
            category_name="Subscriptions",
            description=(
                f"Synced from subscription-tracker ({external_ref}, "
                f"{entry.get('billing_frequency', 'unknown')} billing, monthly-normalized)"
            ),
            external_id=external_id,
            import_basis="monthly_normalized",
        )
        if created:
            imported += 1
            details.append({"external_ref": external_ref, "action": "imported", "amount": amount})
        else:
            skipped += 1
            details.append({"external_ref": external_ref, "action": "already_imported"})

    status = "ok" if subscriptions else "empty"
    return {
        "source": source,
        "status": status,
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "basis": "monthly_normalized",
        "period": sync_month,
        "details": details,
    }


# ------------------------------------------------------------------ Person C
def _settled_amount(entry: dict, current_month: str) -> tuple[Optional[float], Optional[str]]:
    """(amount, basis) for one C history month, or (None, None) if not importable.

    An actual bill always wins. Without one, only a CLOSED month's estimate is
    used - the running month's estimate keeps changing as readings arrive.
    """
    actual = entry.get("actual_amount")
    if isinstance(actual, (int, float)) and not isinstance(actual, bool) and actual > 0:
        return float(actual), "actual"
    estimate = entry.get("estimated_amount")
    if (
        entry["month"] < current_month
        and isinstance(estimate, (int, float))
        and not isinstance(estimate, bool)
        and estimate > 0
    ):
        return float(estimate), "estimated"
    return None, None


def _find_electricity_row(db: Session, month: str) -> Optional[Expense]:
    """Current identity "C:<month>"; migrates v1.0 ids ("C:actual:<month>" /
    "C:estimated:<month>") to it so old imports are not duplicated."""
    row = get_expense_by_external_id(db, f"C:{month}")
    if row:
        return row
    for legacy_basis in ("actual", "estimated"):
        legacy = get_expense_by_external_id(db, f"C:{legacy_basis}:{month}")
        if legacy:
            _update(db, legacy, external_id=f"C:{month}", import_basis=legacy.import_basis or legacy_basis)
            return legacy
    return None


def _manual_electricity_duplicate(db: Session, month: str) -> Optional[Expense]:
    for expense in manual_expenses_in_month(db, month):
        text = f"{expense.merchant} {expense.description}".lower()
        if any(keyword in text for keyword in ELECTRICITY_KEYWORDS):
            return expense
    return None


def _electricity_description(month: str, basis: str) -> str:
    if basis == "actual":
        return f"Synced from smart-home-energy-monitor: ACTUAL electricity bill for {month}"
    return (
        f"Synced from smart-home-energy-monitor: ESTIMATED electricity cost for {month} "
        "(derived from logged appliance usage and unverified tariff slabs - not an official bill; "
        "replaced automatically when the actual bill is recorded)"
    )


def _sync_smart_home_energy(db: Session) -> dict:
    source = "smart_home_energy"
    problem = _config_problem(source, settings.integration_c_base_url)
    if problem:
        return problem

    payload, error, kind = _fetch(
        f"{settings.integration_c_base_url}/history", params={"months": 6}, expected_keys=C_HISTORY_KEYS
    )
    if kind != "ok":
        return {"source": source, "status": kind, "error": error, "imported": 0, "skipped": 0}
    history = payload.get("months")
    if not isinstance(history, list):
        return {"source": source, "status": "invalid_response", "error": "months is not a list", "imported": 0, "skipped": 0}

    current_month = _month_of(date.today())
    imported = updated = skipped = 0
    details: list[dict] = []
    for entry in history:
        if not isinstance(entry, dict) or not MONTH_RE.match(str(entry.get("month", ""))):
            skipped += 1
            details.append({"external_ref": None, "action": "skipped_malformed_entry"})
            continue
        month = entry["month"]
        amount, basis = _settled_amount(entry, current_month)
        if amount is None:
            continue  # no data, or the running month - nothing settled to import
        amount = round(amount, 2)
        external_id = f"C:{month}"

        existing = _find_electricity_row(db, month)
        if existing:
            if existing.import_basis == "actual" and basis == "estimated":
                skipped += 1  # never downgrade an actual bill to an estimate
                details.append({"external_ref": external_id, "action": "already_imported", "basis": "actual"})
            elif existing.import_basis != basis or abs(existing.amount - amount) >= 0.01:
                action = "upgraded_estimate_to_actual" if existing.import_basis == "estimated" and basis == "actual" else "updated_amount"
                _update(
                    db, existing, amount=amount, import_basis=basis,
                    description=_electricity_description(month, basis),
                )
                updated += 1
                details.append({"external_ref": external_id, "action": action, "basis": basis, "amount": amount})
            else:
                skipped += 1
                details.append({"external_ref": external_id, "action": "already_imported", "basis": basis})
            continue

        duplicate = _manual_electricity_duplicate(db, month)
        if duplicate:
            skipped += 1
            details.append(
                {"external_ref": external_id, "action": "skipped_manual_duplicate", "manual_expense_id": duplicate.id}
            )
            continue

        created = _insert(
            db,
            expense_date=_first_day(month),
            merchant=f"Electricity bill {month}" + (" (estimate)" if basis == "estimated" else ""),
            amount=amount,
            category_name="Bills",
            description=_electricity_description(month, basis),
            external_id=external_id,
            import_basis=basis,
        )
        if created:
            imported += 1
            details.append({"external_ref": external_id, "action": "imported", "basis": basis, "amount": amount})
        else:
            skipped += 1
            details.append({"external_ref": external_id, "action": "already_imported", "basis": basis})

    if not (imported or updated or skipped):
        return {
            "source": source,
            "status": "empty",
            "imported": 0,
            "skipped": 0,
            "error": "no actual bill and no closed-month estimate available yet",
        }
    return {"source": source, "status": "ok", "imported": imported, "updated": updated, "skipped": skipped, "details": details}


# -------------------------------------------------------------------- public
def sync_all(db: Session) -> tuple[list[dict], str]:
    """Run both pulls; each source is isolated - one failing never blocks the other."""
    today_month = _month_of(date.today())
    results = []
    for runner in (lambda: _sync_subscription_tracker(db, today_month), lambda: _sync_smart_home_energy(db)):
        try:
            results.append(runner())
        except Exception as exc:  # defensive: one source must never break the other
            db.rollback()
            source = "subscription_tracker" if not results else "smart_home_energy"
            results.append(
                {"source": source, "status": "invalid_response", "error": f"sync failed: {exc.__class__.__name__}",
                 "imported": 0, "skipped": 0}
            )
    statuses = [result["status"] for result in results]
    if all(status in FAILURE_STATUSES for status in statuses):
        overall = "failed"
    elif any(status in FAILURE_STATUSES | {"empty"} for status in statuses):
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
        if base_url and not is_valid_base_url(base_url):
            payload, error, kind, latency_ms = None, "base URL must start with http:// or https://", "misconfigured", 0.0
        else:
            payload, error, kind, latency_ms = check_service_health(
                base_url,
                timeout=settings.integration_timeout_seconds,
                connect_timeout=settings.integration_connect_timeout_seconds,
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
    return services, datetime.now(timezone.utc).isoformat()
