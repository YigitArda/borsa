"""API Integration Tests — end-to-end tests using FastAPI TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


class TestHealthEndpoints:
    def test_health(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_root(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "Borsa Research Engine" in response.json()["message"]


class TestStocksEndpoints:
    def test_list_stocks(self, client: TestClient) -> None:
        response = client.get("/stocks")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_stock_detail(self, client: TestClient) -> None:
        # Test with a well-known ticker
        response = client.get("/stocks/AAPL")
        # May be 200 or 404 depending on data
        assert response.status_code in (200, 404)

    def test_stock_prices(self, client: TestClient) -> None:
        response = client.get("/stocks/AAPL/prices")
        assert response.status_code in (200, 404)

    def test_stock_features(self, client: TestClient) -> None:
        response = client.get("/stocks/AAPL/features")
        assert response.status_code in (200, 404)


class TestDataQualityEndpoints:
    def test_data_quality_report(self, client: TestClient) -> None:
        response = client.get("/data-quality")
        assert response.status_code == 200
        data = response.json()
        assert "stocks" in data
        assert "macro_freshness" in data

    def test_data_quality_scores(self, client: TestClient) -> None:
        response = client.get("/data-quality/scores")
        assert response.status_code == 200

    def test_data_quality_summary(self, client: TestClient) -> None:
        response = client.get("/data-quality/summary")
        assert response.status_code == 200
        data = response.json()
        assert "stock_count" in data
        assert "data_sources" in data
        assert "system_status" in data
        assert "feature_coverage" in data


class TestResearchEndpoints:
    def test_risk_warnings(self, client: TestClient) -> None:
        response = client.get("/research/risk-warnings")
        assert response.status_code == 200
        data = response.json()
        assert "warnings" in data

    def test_promotions(self, client: TestClient) -> None:
        response = client.get("/research/promotions")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_regime_history(self, client: TestClient) -> None:
        response = client.get("/research/regime/history")
        assert response.status_code == 200

    def test_kill_switch_status(self, client: TestClient) -> None:
        response = client.get("/research/kill-switch/status")
        assert response.status_code == 200
        data = response.json()
        assert "active" in data

    def test_arxiv_papers(self, client: TestClient) -> None:
        response = client.get("/research/papers")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_arxiv_insights(self, client: TestClient) -> None:
        response = client.get("/research/insights")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestWeeklyPicksEndpoints:
    def test_get_weekly_picks(self, client: TestClient) -> None:
        response = client.get("/weekly-picks")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_paper_trades(self, client: TestClient) -> None:
        response = client.get("/weekly-picks/paper")
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert "trades" in data


class TestStrategiesEndpoints:
    def test_list_strategies(self, client: TestClient) -> None:
        response = client.get("/strategies")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_missing_strategy_returns_404(self, client: TestClient) -> None:
        response = client.get("/strategies/999999")
        assert response.status_code == 404


class TestJobsEndpoints:
    def test_list_jobs(self, client: TestClient) -> None:
        response = client.get("/jobs")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_running_jobs(self, client: TestClient) -> None:
        response = client.get("/jobs/running")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestSelectedStocksEndpoints:
    def test_list_selected_stocks(self, client: TestClient) -> None:
        response = client.get("/selected-stocks")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_selected_stocks_history(self, client: TestClient) -> None:
        response = client.get("/selected-stocks/history")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestAuthEndpoints:
    def test_register(self, client: TestClient) -> None:
        response = client.post(
            "/auth/register",
            json={"email": "test@example.com", "password": "testpass123"},
        )
        # May be 201 (created) or 409 (already exists)
        assert response.status_code in (201, 409, 422)

    def test_login_invalid(self, client: TestClient) -> None:
        response = client.post(
            "/auth/login",
            json={"email": "nonexistent@example.com", "password": "wrong"},
        )
        assert response.status_code == 401

    def test_me_without_auth(self, client: TestClient) -> None:
        response = client.get("/auth/me")
        assert response.status_code == 401


class TestVerificationEndpoints:
    def test_verification_status(self, client: TestClient) -> None:
        response = client.get("/verification/status")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_verification_full(self, client: TestClient) -> None:
        response = client.get("/verification")
        assert response.status_code == 200
        data = response.json()
        assert "checks" in data
        assert "overall_status" in data


class TestRateLimiting:
    def test_rate_limit_headers(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers

    def test_rate_limit_not_exceeded(self, client: TestClient) -> None:
        # Make a few requests, should not be rate limited
        for _ in range(3):
            response = client.get("/health")
            assert response.status_code == 200


class TestErrorHandling:
    def test_404(self, client: TestClient) -> None:
        response = client.get("/nonexistent-endpoint")
        assert response.status_code == 404

    def test_invalid_json(self, client: TestClient) -> None:
        response = client.post(
            "/auth/login",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422


class TestNotificationsEndpoints:
    def test_get_notification_settings(self, client: TestClient) -> None:
        response = client.get("/notifications/settings")
        assert response.status_code == 200
        data = response.json()
        assert data["emailAlerts"] is True
        assert "slackWebhook" in data

    def test_update_notification_settings(self, client: TestClient) -> None:
        payload = {
            "emailAlerts": False,
            "slackWebhook": "https://hooks.slack.com/services/test",
            "jobFailures": False,
            "killSwitchTriggers": False,
            "strategyPromotions": True,
            "dailyDigest": True,
        }
        response = client.put("/notifications/settings", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["emailAlerts"] is False
        assert data["strategyPromotions"] is True

        get_response = client.get("/notifications/settings")
        assert get_response.status_code == 200
        assert get_response.json()["slackWebhook"] == payload["slackWebhook"]


class Test404Coverage:
    def test_missing_backtest_returns_404(self, client: TestClient) -> None:
        response = client.get("/backtest/999999")
        assert response.status_code == 404

    def test_missing_stock_quality_score_returns_404(self, client: TestClient) -> None:
        response = client.get("/data-quality/scores/NOPE")
        assert response.status_code == 404
