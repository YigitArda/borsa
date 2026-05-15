"""Pipeline endpoint integration tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


class TestPipelineEndpoints:
    def test_pipeline_ingest(self, client: TestClient) -> None:
        response = client.post(
            "/pipeline/ingest",
            json={"tickers": ["AAPL"]},
        )
        # Should queue a Celery task
        assert response.status_code in (200, 202)
        data = response.json()
        assert "task_id" in data or "status" in data

    def test_pipeline_features(self, client: TestClient) -> None:
        response = client.post(
            "/pipeline/features",
            json={"tickers": ["AAPL"]},
        )
        assert response.status_code in (200, 202)

    def test_pipeline_macro(self, client: TestClient) -> None:
        response = client.post("/pipeline/macro")
        assert response.status_code in (200, 202)

    def test_pipeline_news(self, client: TestClient) -> None:
        response = client.post("/pipeline/news")
        assert response.status_code in (200, 202)

    def test_pipeline_financials(self, client: TestClient) -> None:
        response = client.post("/pipeline/financials")
        assert response.status_code in (200, 202)

    def test_pipeline_run_all(self, client: TestClient) -> None:
        response = client.post(
            "/pipeline/run-all",
            json={"tickers": ["AAPL"]},
        )
        assert response.status_code in (200, 202)
        data = response.json()
        assert "task_id" in data or "status" in data


class TestPipelineImportEndpoints:
    def test_import_pit_financials(self, client: TestClient) -> None:
        response = client.post(
            "/pipeline/import/pit-financials",
            json={"path": "/tmp/test.csv"},
        )
        # May fail if file doesn't exist, but endpoint should exist
        assert response.status_code in (200, 202, 422, 500)

    def test_import_universe(self, client: TestClient) -> None:
        response = client.post(
            "/pipeline/import/universe",
            json={"path": "/tmp/test.csv", "index_name": "SP500"},
        )
        assert response.status_code in (200, 202, 422, 500)
