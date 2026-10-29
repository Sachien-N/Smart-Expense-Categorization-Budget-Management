"""The v1.1 additive migration must upgrade a v1.0 database without data loss."""
import tempfile

from sqlalchemy import create_engine, text

from database import add_missing_columns, normalize_database_url

V1_EXPENSES_DDL = """
CREATE TABLE expenses (
    id INTEGER PRIMARY KEY, expense_date DATE NOT NULL, merchant VARCHAR(120) NOT NULL,
    description VARCHAR(500) NOT NULL, amount FLOAT NOT NULL, category_id INTEGER NOT NULL,
    source VARCHAR(20) NOT NULL, external_id VARCHAR(120), created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)"""


def test_import_basis_column_added_and_rows_preserved():
    engine = create_engine(f"sqlite:///{tempfile.mkdtemp()}/v1.db")
    with engine.begin() as conn:
        conn.execute(text(V1_EXPENSES_DDL))
        conn.execute(text(
            "INSERT INTO expenses VALUES (1, '2026-09-01', 'Swiggy', '', 250.0, 1, 'manual', NULL, "
            "'2026-09-01 10:00:00', '2026-09-01 10:00:00')"
        ))
    assert add_missing_columns("expenses", {"import_basis": "VARCHAR(20)"}, bind=engine) == ["import_basis"]
    assert add_missing_columns("expenses", {"import_basis": "VARCHAR(20)"}, bind=engine) == []  # idempotent
    with engine.connect() as conn:
        row = conn.execute(text("SELECT merchant, amount, import_basis FROM expenses")).one()
    assert tuple(row) == ("Swiggy", 250.0, None)


def test_database_url_normalization(tmp_path):
    assert normalize_database_url("postgres://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"
    assert normalize_database_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    url = normalize_database_url("sqlite:///data/x.db")
    assert url.startswith("sqlite:///") and url.endswith("/data/x.db") and "/./" not in url
    absolute = normalize_database_url(f"sqlite:///{tmp_path.as_posix()}/y.db")
    assert absolute == f"sqlite:///{tmp_path.as_posix()}/y.db"
    assert normalize_database_url(None).endswith("/data/expense_budget.db")
