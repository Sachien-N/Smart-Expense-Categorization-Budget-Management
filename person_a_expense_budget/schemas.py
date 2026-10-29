"""Pydantic v2 schemas defining the public JSON contract of Person A's API."""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

MonthPattern = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="Month as YYYY-MM")


# ---------------------------------------------------------------- expenses
class ExpenseCreate(BaseModel):
    merchant: str = Field(min_length=1, max_length=120)
    amount: float = Field(gt=0, description="Positive amount in INR")
    expense_date: Optional[date] = Field(default=None, description="Defaults to today when omitted")
    category: Optional[str] = Field(
        default=None,
        description="Category name. When omitted, the rule-based categorizer assigns one.",
    )
    description: Optional[str] = Field(default=None, max_length=500)
    external_id: Optional[str] = Field(
        default=None,
        description="Integration idempotency key (set by /integrations/sync); unique.",
    )


class ExpenseUpdate(BaseModel):
    merchant: Optional[str] = Field(default=None, min_length=1, max_length=120)
    amount: Optional[float] = Field(default=None, gt=0)
    expense_date: Optional[date] = None
    category: Optional[str] = None
    description: Optional[str] = Field(default=None, max_length=500)


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    expense_date: date
    merchant: str
    description: str
    amount: float
    category: str
    source: Literal["manual", "integration"]
    external_id: Optional[str] = None
    created_at: datetime


# -------------------------------------------------------------- categories
class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    is_active: bool


class CategoryDetail(BaseModel):
    category: str
    expense_count: int
    total_amount: float
    first_expense_date: Optional[date] = None
    last_expense_date: Optional[date] = None
    expenses: list[ExpenseOut]


# ----------------------------------------------------------------- budgets
class BudgetCreate(BaseModel):
    category: str = Field(min_length=1, max_length=60)
    month: str = MonthPattern
    amount_limit: float = Field(gt=0)


class BudgetOut(BaseModel):
    id: int
    category: str
    month: str
    amount_limit: float
    spent: float
    remaining: float
    utilization_percent: float
    over_budget: bool


# ----------------------------------------------------------------- summary
class CategoryShare(BaseModel):
    category: str
    total: float
    count: int
    share_percent: float


class BudgetComparison(BaseModel):
    category: str
    budget: float
    spent: float
    remaining: float
    utilization_percent: float
    over_budget: bool


class MonthlySummary(BaseModel):
    month: str
    total_expenses: float
    transaction_count: int
    by_category: list[CategoryShare]
    budget_comparison: list[BudgetComparison]


# ------------------------------------------------------------- categorizer
class CategorizeSuggestion(BaseModel):
    merchant: str
    suggested_category: str
    matched_keyword: Optional[str] = None
    confidence: Literal["rule", "fallback"]
    reason: str


# ------------------------------------------------------------- integration
class ServiceStatus(BaseModel):
    service_key: str
    base_url: Optional[str] = None
    status: Literal["available", "unavailable", "invalid_response", "not_configured"]
    peer_service_name: Optional[str] = None
    peer_version: Optional[str] = None
    latency_ms: Optional[float] = None
    error: Optional[str] = None


class IntegrationsStatus(BaseModel):
    checked_at: str
    services: list[ServiceStatus]


class SyncSourceResult(BaseModel):
    source: str
    status: Literal["ok", "unavailable", "invalid_response", "not_configured", "empty"]
    imported: int = 0
    skipped: int = 0
    basis: Optional[str] = None
    error: Optional[str] = None
    details: list[dict] = Field(default_factory=list)


class SyncResult(BaseModel):
    synced_at: str
    overall: Literal["ok", "partial", "failed"]
    results: list[SyncSourceResult]
