"""SQLAlchemy ORM models for Person A - Smart Expense Categorization & Budget Management."""
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    expenses: Mapped[list["Expense"]] = relationship(back_populates="category_ref")
    budgets: Mapped[list["Budget"]] = relationship(back_populates="category_ref")


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    expense_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    merchant: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True, nullable=False)
    # source: "manual" (user typed it) or "integration" (synced over HTTP from B/C)
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    # Stable external identifier for idempotent integration imports,
    # e.g. "B:B-SUB-3:2026-10" or "C:actual:2026-09". Unique when present.
    external_id: Mapped[str | None] = mapped_column(String(120), unique=True, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    category_ref: Mapped["Category"] = relationship(back_populates="expenses")

    @property
    def category(self) -> str:
        """Category NAME (the JSON contract exposes the string, not the FK)."""
        return self.category_ref.name if self.category_ref is not None else ""


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("category_id", "month", name="uq_budget_category_month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True, nullable=False)
    # Billing month in "YYYY-MM" form (string keeps the API contract simple).
    month: Mapped[str] = mapped_column(String(7), index=True, nullable=False)
    amount_limit: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    category_ref: Mapped["Category"] = relationship(back_populates="budgets")

    @property
    def category(self) -> str:
        return self.category_ref.name if self.category_ref is not None else ""
