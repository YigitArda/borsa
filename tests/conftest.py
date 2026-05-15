"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest
from fastapi.testclient import TestClient

from app.main import app


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
