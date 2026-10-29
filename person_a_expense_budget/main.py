"""Person A - Smart Expense Categorization & Budget Management (FastAPI backend).

Run locally:  uvicorn main:app --host 127.0.0.1 --port 8001 --reload
Interactive docs: http://127.0.0.1:8001/docs
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from config import settings
from crud import seed_default_categories
from database import Base, SessionLocal, engine, get_db
from routers import budgets, categories, expenses, summary


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Create tables and idempotently seed the canonical categories."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_default_categories(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Smart Expense Categorization & Budget API",
    description=(
        "CSI3007 Advanced Python Programming - Person A (Sachien N, 23MID0255). "
        "Tracks expenses, auto-categorizes merchants with transparent keyword rules, "
        "manages monthly budgets, and integrates with Person B (subscription tracker) "
        "and Person C (smart home energy monitor) strictly over HTTP REST."
    ),
    version=settings.version,
    lifespan=lifespan,
)

# Open CORS so the Streamlit frontend (and any browser client) can call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(expenses.router)
app.include_router(categories.router)
app.include_router(budgets.router)
app.include_router(summary.router)


@app.get("/health", tags=["System"])
def health(db: Session = Depends(get_db)):
    """Liveness + database connectivity probe (used by A's peers and Render)."""
    database_status = "connected"
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - defensive
        database_status = "unavailable"
    return {
        "status": "ok" if database_status == "connected" else "degraded",
        "service": settings.service_name,
        "owner": settings.service_owner,
        "version": settings.version,
        "database": database_status,
        "time": datetime.now(timezone.utc).isoformat(),
    }
