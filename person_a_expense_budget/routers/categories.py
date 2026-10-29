"""Category endpoints: GET /categories, GET /category/{name}."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from crud import get_category_by_name, list_categories, list_expenses
from database import get_db
from schemas import CategoryDetail, CategoryOut

router = APIRouter(tags=["Categories"])


@router.get("/categories", response_model=list[CategoryOut])
def list_categories_endpoint(db: Session = Depends(get_db)):
    """All categories (six canonical + Uncategorized fallback), alphabetical."""
    return list_categories(db)


@router.get("/category/{name}", response_model=CategoryDetail)
def category_detail_endpoint(name: str, db: Session = Depends(get_db)):
    """All expenses of one category (case-insensitive) plus roll-up totals."""
    category = get_category_by_name(db, name)
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown category: {name}")
    expenses = list_expenses(db, category=name, limit=200)
    total = round(sum(e.amount for e in expenses), 2)
    return CategoryDetail(
        category=category.name,
        expense_count=len(expenses),
        total_amount=total,
        first_expense_date=min((e.expense_date for e in expenses), default=None),
        last_expense_date=max((e.expense_date for e in expenses), default=None),
        expenses=expenses,
    )
