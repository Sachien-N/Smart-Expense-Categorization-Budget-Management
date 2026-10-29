"""Person A - Smart Expense Categorization & Budget Management (FastAPI backend).

Run locally:  uvicorn main:app --host 127.0.0.1 --port 8001 --reload
Production:   uvicorn main:app --host 0.0.0.0 --port $PORT
Interactive docs: http://127.0.0.1:8001/docs
"""
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from config import settings
from crud import seed_default_categories
from database import Base, SessionLocal, add_missing_columns, database_backend, engine, get_db
from routers import budgets, categories, expenses, summary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("expense_budget")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Create tables, apply additive column migrations, seed categories."""
    Base.metadata.create_all(bind=engine)
    added = add_missing_columns("expenses", {"import_basis": "VARCHAR(20)"})
    if added:
        logger.info("Migrated expenses table: added columns %s", added)
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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Log the full traceback server-side; return a generic JSON 500 (no stack
    traces, SQL or connection strings leak to API consumers)."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/", include_in_schema=False)
def root():
    return {"service": settings.service_name, "docs": "/docs", "health": "/health"}


@app.get("/health", tags=["System"])
def health(db: Session = Depends(get_db)):
    """Liveness + database connectivity probe (used by A's peers and Render).

    Always HTTP 200 while the process is up; `database` reports readiness
    separately ("connected" / "unavailable") and `status` becomes "degraded".
    """
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
        "database_backend": database_backend(),
        "time": datetime.now(timezone.utc).isoformat(),
    }
