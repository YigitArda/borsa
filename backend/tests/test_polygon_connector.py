from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.data_source_health import DataConnector
from app.models.news import NewsArticle, NewsAnalysis
from app.models.stock import Stock
from app.services.connectors.optional import PolygonNewsConnector, PolygonPricesConnector


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Stock.__table__,
            DataConnector.__table__,
            NewsArticle.__table__,
            NewsAnalysis.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def test_polygon_news_skipped_without_api_key(monkeypatch):
    monkeypatch.setattr("app.services.connectors.optional.settings.polygon_api_key", None)
    session = make_session()
    connector = PolygonNewsConnector(session)
    assert connector.is_configured() is False
    result = connector.run(tickers=["AAPL"])
    assert result.status == "skipped"
    assert result.message == "polygon_api_key_missing"


def test_polygon_prices_skipped_without_api_key(monkeypatch):
    monkeypatch.setattr("app.services.connectors.optional.settings.polygon_api_key", None)
    session = make_session()
    connector = PolygonPricesConnector(session)
    assert connector.is_configured() is False
    result = connector.run(tickers=["AAPL"])
    assert result.status == "skipped"


def test_polygon_news_normalizes_available_at(monkeypatch):
    monkeypatch.setattr("app.services.connectors.optional.settings.polygon_api_key", "test_key")
    monkeypatch.setattr("app.services.connectors.optional.settings.connector_request_timeout", 20)

    session = make_session()
    stock = Stock(ticker="AAPL", name="Apple Inc.")
    session.add(stock)
    session.commit()

    pub_utc = "2024-03-15T10:00:00Z"
    fake_response = {
        "results": [
            {
                "article_url": "https://example.com/aapl-news-1",
                "title": "AAPL earnings beat expectations",
                "published_utc": pub_utc,
                "publisher": {"name": "Example News"},
                "description": "Apple earnings beat",
            }
        ]
    }

    with patch("app.services.connectors.optional.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_response
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = PolygonNewsConnector(session).run(tickers=["AAPL"], as_of_date=date(2024, 3, 16))

    assert result.status == "ok"
    article = session.query(NewsArticle).first()
    assert article is not None
    assert article.provider_id == "polygon_news"
    assert article.available_at is not None
    expected_dt = datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc)
    assert abs((article.available_at.replace(tzinfo=timezone.utc) - expected_dt).total_seconds()) < 5
    assert article.source_quality == 0.85


def test_polygon_prices_available_at_is_close_plus_one_day(monkeypatch):
    monkeypatch.setattr("app.services.connectors.optional.settings.polygon_api_key", "test_key")
    monkeypatch.setattr("app.services.connectors.optional.settings.connector_request_timeout", 20)

    session = make_session()
    stock = Stock(ticker="AAPL", name="Apple Inc.")
    session.add(stock)
    session.commit()

    ts_ms = int(datetime(2024, 3, 15, tzinfo=timezone.utc).timestamp() * 1000)
    fake_response = {
        "results": [
            {"t": ts_ms, "o": 170.0, "h": 175.0, "l": 169.0, "c": 172.0, "v": 1000000}
        ]
    }

    persisted_rows = []

    def capture_pg_insert(model):
        stmt = MagicMock()

        def values(rows):
            persisted_rows.extend(rows)
            inner = MagicMock()
            inner.on_conflict_do_nothing.return_value = inner
            return inner

        stmt.values = values
        return stmt

    with patch("app.services.connectors.optional.pg_insert", side_effect=capture_pg_insert):
        with patch("app.services.connectors.optional.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = fake_response
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            result = PolygonPricesConnector(session).run(tickers=["AAPL"])

    assert result.status == "ok"
    assert len(persisted_rows) == 1
    row = persisted_rows[0]
    assert row["provider_id"] == "polygon_prices"
    assert row["available_at"].date() == date(2024, 3, 16)
    assert row["source_quality"] == 0.95
