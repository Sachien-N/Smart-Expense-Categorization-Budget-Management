"""SQLite database engine and session management for Person A.

Each CSI3007 project owns a SEPARATE database file. No other project
ever opens this file - cross-app data flows exclusively over HTTP REST.
"""
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "expense_budget.db"
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"

# Make sure the parent directory of a file-based SQLite DB exists.
if DATABASE_URL.startswith("sqlite:///"):
    _db_path = DATABASE_URL.replace("sqlite:///", "", 1)
    if _db_path:  # skip in-memory sqlite:///:memory:
        Path(_db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    """FastAPI dependency yielding a scoped SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
