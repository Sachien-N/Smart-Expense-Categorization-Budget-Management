"""Expense endpoints: POST/GET /expenses, GET/PUT/DELETE /expenses/{id}."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from crud import create_expense, delete_expense, get_expense, list_expenses, update_expense
from database import get_db
from schemas import ExpenseCreate, ExpenseOut, ExpenseUpdate
from services.categorizer import categorize_merchant

router = APIRouter(prefix="/expenses", tags=["Expenses"])


@router.post("", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def create_expense_endpoint(payload: ExpenseCreate, db: Session = Depends(get_db)):
    """Create an expense. When `category` is omitted the rule-based
    categorizer assigns one (fallback bucket: Uncategorized)."""
    if payload.external_id:
        from crud import get_expense_by_external_id

        existing = get_expense_by_external_id(db, payload.external_id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"external_id already imported: {payload.external_id}",
            )

    category_name = payload.category or categorize_merchant(payload.merchant)[0]
    try:
        expense = create_expense(
            db,
            expense_date=payload.expense_date or date.today(),
            merchant=payload.merchant,
            amount=payload.amount,
            category_name=category_name,
            description=payload.description or "",
            external_id=payload.external_id,
        )
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Expense violates a uniqueness constraint (external_id already used)",
        )
    return expense


@router.get("", response_model=list[ExpenseOut])
def list_expenses_endpoint(
    month: Optional[str] = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    category: Optional[str] = Query(default=None, max_length=60),
    source: Optional[str] = Query(default=None, pattern="^(manual|integration)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List expenses with optional month / category / source filters."""
    return list_expenses(db, month=month, category=category, source=source, limit=limit, offset=offset)


@router.get("/{expense_id}", response_model=ExpenseOut)
def get_expense_endpoint(expense_id: int, db: Session = Depends(get_db)):
    expense = get_expense(db, expense_id)
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Expense {expense_id} not found")
    return expense


@router.put("/{expense_id}", response_model=ExpenseOut)
def update_expense_endpoint(expense_id: int, payload: ExpenseUpdate, db: Session = Depends(get_db)):
    expense = get_expense(db, expense_id)
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Expense {expense_id} not found")
    changes = payload.model_dump(exclude_unset=True)
    return update_expense(db, expense, changes)


@router.delete("/{expense_id}")
def delete_expense_endpoint(expense_id: int, db: Session = Depends(get_db)):
    expense = get_expense(db, expense_id)
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Expense {expense_id} not found")
    delete_expense(db, expense)
    return {"deleted": True, "id": expense_id}
