"""CRUD + query layer for Person A. Routers never touch the ORM directly."""
from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import Budget, Category, Expense

CANONICAL_CATEGORIES = [
    "Food",
    "Travel",
    "Bills",
    "Entertainment",
    "Shopping",
    "Subscriptions",
]
FALLBACK_CATEGORY = "Uncategorized"


# --------------------------------------------------------------- categories
def seed_default_categories(db: Session) -> None:
    """Idempotently ensure canonical categories + fallback exist."""
    descriptions = {
        "Food": "Restaurants, delivery apps, groceries, cafes",
        "Travel": "Cabs, fuel, tickets, tolls, parking",
        "Bills": "Electricity, water, gas, broadband, mobile recharge",
        "Entertainment": "Movies, events, games, leisure purchases",
        "Shopping": "E-commerce and retail purchases",
        "Subscriptions": "Recurring OTT / software memberships",
        FALLBACK_CATEGORY: "Fallback bucket for merchants matching no categorizer rule",
    }
    for name in CANONICAL_CATEGORIES + [FALLBACK_CATEGORY]:
        if not db.scalar(select(Category).where(Category.name == name)):
            db.add(Category(name=name, description=descriptions.get(name, "")))
    db.commit()


def list_categories(db: Session) -> list[Category]:
    return list(db.scalars(select(Category).order_by(Category.name)).all())


def get_category_by_name(db: Session, name: str) -> Optional[Category]:
    return db.scalar(select(Category).where(func.lower(Category.name) == name.lower()))


def get_or_create_category(db: Session, name: str) -> Category:
    category = get_category_by_name(db, name)
    if category is None:
        category = Category(name=name.strip(), description="Created on demand via API")
        db.add(category)
        db.flush()
    return category


# ----------------------------------------------------------------- expenses
def get_expense(db: Session, expense_id: int) -> Optional[Expense]:
    return db.get(Expense, expense_id)


def get_expense_by_external_id(db: Session, external_id: str) -> Optional[Expense]:
    return db.scalar(select(Expense).where(Expense.external_id == external_id))


def create_expense(
    db: Session,
    *,
    expense_date: date,
    merchant: str,
    amount: float,
    category_name: str,
    description: str = "",
    source: str = "manual",
    external_id: Optional[str] = None,
) -> Expense:
    category = get_or_create_category(db, category_name)
    expense = Expense(
        expense_date=expense_date,
        merchant=merchant.strip(),
        description=description or "",
        amount=round(float(amount), 2),
        category_id=category.id,
        source=source,
        external_id=external_id,
    )
    db.add(expense)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise
    db.refresh(expense)
    return expense


def update_expense(db: Session, expense: Expense, changes: dict) -> Expense:
    if "category" in changes and changes["category"]:
        category = get_or_create_category(db, changes.pop("category"))
        expense.category_id = category.id
    for field, value in changes.items():
        if value is not None:
            setattr(expense, field, value)
    if "amount" in changes and changes["amount"] is not None:
        expense.amount = round(float(expense.amount), 2)
    db.commit()
    db.refresh(expense)
    return expense


def delete_expense(db: Session, expense: Expense) -> None:
    db.delete(expense)
    db.commit()


def list_expenses(
    db: Session,
    *,
    month: Optional[str] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Expense]:
    stmt = select(Expense).join(Category)
    if month:
        stmt = stmt.where(func.strftime("%Y-%m", Expense.expense_date) == month)
    if category:
        stmt = stmt.where(func.lower(Category.name) == category.lower())
    if source:
        stmt = stmt.where(Expense.source == source)
    stmt = stmt.order_by(Expense.expense_date.desc(), Expense.id.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


# ----------------------------------------------------------------- budgets
def get_budget(db: Session, budget_id: int) -> Optional[Budget]:
    return db.get(Budget, budget_id)


def get_budget_for(db: Session, category_id: int, month: str) -> Optional[Budget]:
    return db.scalar(select(Budget).where(Budget.category_id == category_id, Budget.month == month))


def create_budget(db: Session, *, category_id: int, month: str, amount_limit: float) -> Budget:
    budget = Budget(category_id=category_id, month=month, amount_limit=round(float(amount_limit), 2))
    db.add(budget)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise
    db.refresh(budget)
    return budget


def list_budgets(db: Session, month: Optional[str] = None) -> list[Budget]:
    stmt = select(Budget)
    if month:
        stmt = stmt.where(Budget.month == month)
    return list(db.scalars(stmt.order_by(Budget.month.desc(), Budget.id)).all())


def spent_for_category_month(db: Session, category_id: int, month: str) -> float:
    total = db.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0.0)).where(
            Expense.category_id == category_id,
            func.strftime("%Y-%m", Expense.expense_date) == month,
        )
    )
    return round(float(total or 0.0), 2)


# ----------------------------------------------------------------- summary
def category_totals_for_month(db: Session, month: str) -> list[dict]:
    rows = db.execute(
        select(Category.name, func.coalesce(func.sum(Expense.amount), 0.0), func.count(Expense.id))
        .join(Expense, Expense.category_id == Category.id)
        .where(func.strftime("%Y-%m", Expense.expense_date) == month)
        .group_by(Category.name)
        .order_by(func.sum(Expense.amount).desc())
    ).all()
    return [{"category": name, "total": round(float(total), 2), "count": count} for name, total, count in rows]
