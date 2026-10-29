"""Shared pytest fixtures for Person A.

Environment variables are set BEFORE any application module is imported so
that database.py / config.py bind to a throwaway SQLite file.
"""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="csi3007_a_tests_")
# TEST_DATABASE_URL lets the same suite run against PostgreSQL (must be an empty DB).
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL") or f"sqlite:///{_TMP}/test_expense_budget.db"
os.environ["INTEGRATION_B_BASE_URL"] = ""
os.environ["INTEGRATION_C_BASE_URL"] = ""
os.environ["INTEGRATION_TIMEOUT_SECONDS"] = "0.5"
os.environ["INTEGRATION_MAX_RETRIES"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client
