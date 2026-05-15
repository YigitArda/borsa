"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import os
import sys
import shutil
from uuid import uuid4
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
TEST_TMP = ROOT / ".pytest_tmp"
TEST_TMP.mkdir(exist_ok=True)

os.environ.setdefault("TMP", str(TEST_TMP))
os.environ.setdefault("TEMP", str(TEST_TMP))
os.environ.setdefault("TMPDIR", str(TEST_TMP))
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{(TEST_TMP / 'test.db').as_posix()}")
os.environ.setdefault("SYNC_DATABASE_URL", f"sqlite:///{(TEST_TMP / 'test.db').as_posix()}")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET", "pytest-jwt-secret")

# Add backend to path before importing the app
sys.path.insert(0, str(BACKEND))

import pytest
from fastapi.testclient import TestClient

from app.database import Base
import app.models  # noqa: F401 - ensure all model tables are registered
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def _setup_test_database():
    from sqlalchemy import create_engine

    engine = create_engine(os.environ["SYNC_DATABASE_URL"])
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(scope="session")
def client() -> TestClient:
    """FastAPI TestClient for API integration tests."""
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict:
    """Default authenticated headers (no API key in dev mode)."""
    return {"Content-Type": "application/json"}


@pytest.fixture
def test_user() -> dict:
    """Test user credentials."""
    return {
        "email": "pytest_user@example.com",
        "password": "pytest_password_123",
    }


@pytest.fixture
def tmp_path():
    """Local replacement for pytest's tmp_path fixture.

    The built-in temp factory has Windows cleanup issues in this workspace, so
    this fixture provides the minimal Path contract the tests need.
    """
    path = TEST_TMP / f"borsa-{os.getpid()}-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
