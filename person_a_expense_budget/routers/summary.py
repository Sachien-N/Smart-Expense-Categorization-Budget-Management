"""Summary + categorize + integration endpoints for Person A."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from crud import category_totals_for_month, list_budgets, source_totals_for_month, spent_for_category_month
from database import get_db
from schemas import (
    BudgetComparison,
    CategoryShare,
    CategorizeSuggestion,
    IntegrationsStatus,
    MonthlySummary,
    SourceShare,
    SyncResult,
    SyncSourceResult,
)
from services.categorizer import categorize_merchant

router = APIRouter(tags=["Summary & Integrations"])


@router.get("/summary", response_model=MonthlySummary)
def monthly_summary_endpoint(
    month: Optional[str] = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    db: Session = Depends(get_db),
):
    """Month roll-up: totals, per-category shares and budget comparison.

    An empty month is a VALID zero (totals 0.0) - it is distinguished from
    missing/invalid input by the 422 validation on `month` format.
    """
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    rows = category_totals_for_month(db, month)
    grand_total = round(sum(row["total"] for row in rows), 2)
    by_category = [
        CategoryShare(
            category=row["category"],
            total=row["total"],
            count=row["count"],
            share_percent=round((row["total"] / grand_total) * 100, 1) if grand_total else 0.0,
        )
        for row in rows
    ]
    budget_comparison = []
    for budget in list_budgets(db, month=month):
        spent = spent_for_category_month(db, budget.category_id, budget.month)
        remaining = round(budget.amount_limit - spent, 2)
        budget_comparison.append(
            BudgetComparison(
                category=budget.category,
                budget=budget.amount_limit,
                spent=spent,
                remaining=remaining,
                utilization_percent=round((spent / budget.amount_limit) * 100, 1) if budget.amount_limit else 0.0,
                over_budget=spent > budget.amount_limit,
            )
        )
    return MonthlySummary(
        month=month,
        total_expenses=grand_total,
        transaction_count=sum(row["count"] for row in rows),
        by_category=by_category,
        by_source=[SourceShare(**row) for row in source_totals_for_month(db, month)],
        budget_comparison=budget_comparison,
    )


@router.get("/categorize", response_model=CategorizeSuggestion)
def categorize_endpoint(merchant: str = Query(min_length=1, max_length=120)):
    """Preview the rule-based category for a merchant without saving anything."""
    category, keyword, confidence = categorize_merchant(merchant)
    if confidence == "rule":
        reason = f"Merchant matched keyword '{keyword}' (first rule in priority order wins)"
    else:
        reason = "No rule matched; falling back to the Uncategorized bucket"
    return CategorizeSuggestion(
        merchant=merchant,
        suggested_category=category,
        matched_keyword=keyword,
        confidence=confidence,
        reason=reason,
    )


@router.get("/integrations/status", response_model=IntegrationsStatus)
def integrations_status_endpoint():
    """Live health probe of Person B and Person C over HTTP."""
    from services.integration_service import build_status_report

    services, checked_at = build_status_report()
    return IntegrationsStatus(checked_at=checked_at, services=services)


@router.post("/integrations/sync", response_model=SyncResult)
def integrations_sync_endpoint(db: Session = Depends(get_db)):
    """Pull Person B subscriptions + Person C bills into local expenses.

    Idempotent: imports carry a stable external_id ("B:<ref>:<YYYY-MM>",
    "C:<YYYY-MM>"); re-running updates changed amounts in place and never
    adds a second row. A C estimate is upgraded to the actual bill when one
    is recorded. Partial failures are reported per source and never break
    the whole call.
    """
    from services.integration_service import sync_all

    results, overall = sync_all(db)
    return SyncResult(
        synced_at=datetime.now(timezone.utc).isoformat(),
        overall=overall,
        results=[SyncSourceResult(**result) for result in results],
    )
