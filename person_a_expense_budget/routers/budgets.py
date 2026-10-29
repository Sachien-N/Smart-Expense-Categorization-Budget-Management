"""Budget endpoints: GET /budgets, POST /budgets."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from crud import create_budget, get_budget_for, get_or_create_category, list_budgets, spent_for_category_month
from database import get_db
from schemas import BudgetCreate, BudgetOut

router = APIRouter(prefix="/budgets", tags=["Budgets"])


def _to_out(db: Session, budget) -> BudgetOut:
    spent = spent_for_category_month(db, budget.category_id, budget.month)
    remaining = round(budget.amount_limit - spent, 2)
    utilization = round((spent / budget.amount_limit) * 100, 1) if budget.amount_limit else 0.0
    return BudgetOut(
        id=budget.id,
        category=budget.category,
        month=budget.month,
        amount_limit=budget.amount_limit,
        spent=spent,
        remaining=remaining,
        utilization_percent=utilization,
        over_budget=spent > budget.amount_limit,
    )


@router.get("", response_model=list[BudgetOut])
def list_budgets_endpoint(
    month: Optional[str] = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    db: Session = Depends(get_db),
):
    """Budgets with live spent / remaining / utilization comparison."""
    return [_to_out(db, budget) for budget in list_budgets(db, month=month)]


@router.post("", response_model=BudgetOut, status_code=status.HTTP_201_CREATED)
def create_budget_endpoint(payload: BudgetCreate, db: Session = Depends(get_db)):
    """Set (or attempt to set) a monthly limit for one category."""
    category = get_or_create_category(db, payload.category)
    if get_budget_for(db, category.id, payload.month):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Budget for {category.name} in {payload.month} already exists",
        )
    try:
        budget = create_budget(db, category_id=category.id, month=payload.month, amount_limit=payload.amount_limit)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Budget for {category.name} in {payload.month} already exists",
        )
    return _to_out(db, budget)
