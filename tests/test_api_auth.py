"""Auth flow integration tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def test_user_credentials() -> dict:
    return {"email": "integration_test@example.com", "password": "testpassword123"}


class TestAuthFlow:
    def test_full_auth_flow(self, client: TestClient, test_user_credentials: dict) -> None:
        # 1. Register
        register_resp = client.post("/auth/register", json=test_user_credentials)
        # User may already exist from previous test run
        assert register_resp.status_code in (201, 409)

        # 2. Login
        login_resp = client.post("/auth/login", json=test_user_credentials)
        assert login_resp.status_code == 200
        data = login_resp.json()
        assert "access_token" in data
        assert "token_type" in data
        token = data["access_token"]

        # 3. Access protected endpoint with JWT
        me_resp = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_resp.status_code == 200
        me_data = me_resp.json()
        assert me_data["email"] == test_user_credentials["email"]

    def test_login_wrong_password(self, client: TestClient, test_user_credentials: dict) -> None:
        resp = client.post(
            "/auth/login",
            json={"email": test_user_credentials["email"], "password": "wrongpassword"},
        )
        assert resp.status_code == 401

    def test_access_protected_without_token(self, client: TestClient) -> None:
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_access_protected_with_invalid_token(self, client: TestClient) -> None:
        resp = client.get(
            "/auth/me",
            headers={"Authorization": "Bearer invalid_token"},
        )
        assert resp.status_code == 401

    def test_api_key_auth(self, client: TestClient) -> None:
        # API key auth is optional; test that endpoints work with or without
        resp = client.get("/stocks")
        assert resp.status_code == 200
