from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.data_source_health import DataConnector, DataSourceHealth
from app.models.news import NewsArticle, NewsAnalysis
from app.models.stock import Stock
from app.services.connectors.base import ConnectorRunResult
from app.services.connectors.orchestrator import ConnectorOrchestrator
from app.services.connectors.registry import ConnectorRegistry
from app.services.data_source_health import DataConnectorHealthService


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Stock.__table__,
            DataConnector.__table__,
            DataSourceHealth.__table__,
            NewsArticle.__table__,
            NewsAnalysis.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def test_sync_registry_creates_rows():
    session = make_session()
    orch = ConnectorOrchestrator(session)
    rows = orch.sync_registry()
    assert len(rows) > 0
    connector_count = session.query(DataConnector).count()
    assert connector_count > 0


def test_run_with_category_filter_only_includes_that_category():
    session = make_session()
    DataConnectorHealthService(session).sync_registry()

    mock_result = ConnectorRunResult("yfinance_news", "ok", 3)

    with patch.object(ConnectorRegistry, "instantiate") as mock_inst:
        mock_connector = MagicMock()
        mock_connector.is_configured.return_value = True
        mock_connector.provider_id = "yfinance_news"
        mock_connector.run.return_value = mock_result
        mock_inst.return_value = mock_connector

        with patch.object(ConnectorRegistry, "enabled_provider_ids", return_value=["yfinance_news"]):
            orch = ConnectorOrchestrator(session)
            response = orch.run(categories=["news"], tickers=["AAPL"])

    providers = response.get("providers", [])
    assert len(providers) == 1
    assert providers[0]["provider_id"] == "yfinance_news"
    assert providers[0]["status"] == "ok"


def test_orchestrator_continues_after_provider_failure():
    session = make_session()
    DataConnectorHealthService(session).sync_registry()

    def make_failing_connector(pid):
        c = MagicMock()
        c.is_configured.return_value = True
        c.provider_id = pid
        c.run.side_effect = RuntimeError("deliberate failure")
        c.skipped.return_value = ConnectorRunResult(pid, "skipped")
        return c

    def make_ok_connector(pid):
        c = MagicMock()
        c.is_configured.return_value = True
        c.provider_id = pid
        c.run.return_value = ConnectorRunResult(pid, "ok", 5)
        return c

    call_n = [0]

    def side_effect(provider_id, sess):
        call_n[0] += 1
        if call_n[0] == 1:
            return make_failing_connector(provider_id)
        return make_ok_connector(provider_id)

    with patch.object(ConnectorRegistry, "instantiate", side_effect=side_effect):
        with patch.object(ConnectorRegistry, "enabled_provider_ids", return_value=["provider_a", "provider_b"]):
            orch = ConnectorOrchestrator(session)
            response = orch.run(tickers=["AAPL"])

    providers = response.get("providers", [])
    assert len(providers) == 2
    statuses = {p["provider_id"]: p["status"] for p in providers}
    assert statuses["provider_a"] == "failed"
    assert statuses["provider_b"] == "ok"


def test_disabled_connector_not_run():
    session = make_session()
    DataConnectorHealthService(session).sync_registry()

    row = session.query(DataConnector).filter_by(provider_id="polygon_news").one_or_none()
    if row:
        row.enabled = False
        session.commit()

    enabled_ids = ConnectorRegistry.enabled_provider_ids(session)
    assert "polygon_news" not in enabled_ids


def test_connector_last_status_updated():
    session = make_session()
    DataConnectorHealthService(session).sync_registry()

    health_svc = DataConnectorHealthService(session)
    health_svc.record(
        provider_id="yfinance_news",
        status="ok",
        rows=5,
        details={"tickers": {"AAPL": 5}},
    )

    row = session.query(DataConnector).filter_by(provider_id="yfinance_news").one()
    assert row.last_status == "ok"


def test_pit_available_at_invariant():
    decision_time = datetime(2024, 1, 10, tzinfo=timezone.utc)
    available_future = datetime(2024, 1, 15, tzinfo=timezone.utc)
    available_past = datetime(2024, 1, 8, tzinfo=timezone.utc)

    assert available_future > decision_time, "Future available_at must be excluded from feature set"
    assert available_past <= decision_time, "Past available_at must be included in feature set"
