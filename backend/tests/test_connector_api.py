from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest_plugins = []


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def client(mock_db):
    from fastapi.testclient import TestClient

    async def override_get_db():
        yield mock_db

    from app.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_get_data_sources_200(client, mock_db):
    with patch("app.api.data_sources.ConnectorRegistry") as mock_reg:
        from app.services.connectors.base import ConnectorDefinition
        mock_def = ConnectorDefinition(
            provider_id="yfinance_news",
            name="Yahoo Finance News",
            category="news",
            enabled_by_default=True,
            priority=90,
        )
        mock_reg.definitions.return_value = [mock_def]

        mock_connector_cls = MagicMock()
        mock_connector_cls.return_value.is_configured.return_value = True
        mock_reg.get_class.return_value = mock_connector_cls

        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        response = client.get("/data-sources")
    assert response.status_code == 200
    data = response.json()
    assert "connectors" in data


def test_sync_data_sources_queues_task(client):
    with patch("app.api.data_sources.enqueue_task") as mock_enqueue:
        mock_task = MagicMock()
        mock_task.id = "task-123"
        mock_enqueue.return_value = mock_task

        response = client.post("/data-sources/sync")

    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "task-123"


def test_patch_toggle_enabled_404_if_not_found(client, mock_db):
    mock_db.scalar.return_value = None
    response = client.patch("/data-sources/nonexistent_provider", json={"enabled": False})
    assert response.status_code == 404


def test_run_data_sources_queues_task(client):
    with patch("app.api.data_sources.enqueue_task") as mock_enqueue:
        mock_task = MagicMock()
        mock_task.id = "run-task-456"
        mock_enqueue.return_value = mock_task

        response = client.post("/data-sources/run", json={"tickers": ["AAPL"], "categories": ["news"]})

    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "run-task-456"
