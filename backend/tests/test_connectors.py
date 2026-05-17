from __future__ import annotations

import sys
import types
from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.data_source_health import DataConnector
from app.models.news import NewsAnalysis, NewsArticle
from app.models.stock import Stock
from app.services.connectors.news import YFinanceNewsConnector
from app.services.connectors.optional import PolygonNewsConnector
from app.services.connectors.registry import ConnectorRegistry
from app.services.data_source_health import DataConnectorHealthService
from app.services.news_service import NewsService


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


def test_registry_exposes_enabled_and_optional_connectors():
    provider_ids = {definition.provider_id for definition in ConnectorRegistry.definitions()}
    assert "yfinance_news" in provider_ids
    assert "gdelt_news" in provider_ids
    assert "sec_edgar_news" in provider_ids
    assert "polygon_news" in provider_ids
    assert "worldbank_macro" in provider_ids
    assert "adanos_sentiment" in provider_ids


def test_sync_registry_creates_connector_rows():
    session = make_session()
    rows = DataConnectorHealthService(session).sync_registry()

    polygon = session.query(DataConnector).filter_by(provider_id="polygon_news").one()
    sec = session.query(DataConnector).filter_by(provider_id="sec_edgar_news").one()

    assert rows
    assert polygon.enabled is False
    assert polygon.configured is False
    assert sec.enabled is True
    assert sec.configured is True


def test_yfinance_news_connector_upserts_provider_metadata(monkeypatch):
    session = make_session()
    session.add(Stock(ticker="AAPL", name="Apple Inc."))
    session.commit()
    DataConnectorHealthService(session).sync_registry()

    fake_yfinance = types.SimpleNamespace(
        Ticker=lambda ticker: types.SimpleNamespace(
            news=[
                {
                    "title": "AAPL launches a new product",
                    "link": "https://example.com/aapl-product",
                    "publisher": "Example",
                    "providerPublishTime": int(datetime(2024, 1, 15, tzinfo=timezone.utc).timestamp()),
                }
            ]
        )
    )
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)

    result = YFinanceNewsConnector(session).run(tickers=["AAPL"], as_of_date=date(2024, 1, 16), lookback_days=7)
    article = session.query(NewsArticle).one()
    analysis = session.query(NewsAnalysis).one()

    assert result.status == "ok"
    assert result.rows == 1
    assert article.provider_id == "yfinance_news"
    assert article.available_at is not None
    assert article.source_quality == 0.55
    assert article.fallback_used is True
    assert analysis.is_product_launch is True


def test_optional_connector_skips_without_api_key(monkeypatch):
    monkeypatch.setattr("app.services.connectors.optional.settings.polygon_api_key", None)
    session = make_session()

    connector = PolygonNewsConnector(session)
    result = connector.run(tickers=["AAPL"])

    assert connector.is_configured() is False
    assert result.status == "skipped"


def test_weekly_news_features_use_available_at_not_only_published_at():
    session = make_session()
    stock = Stock(ticker="AAPL", name="Apple Inc.")
    session.add(stock)
    session.commit()

    article = NewsArticle(
        url_hash="delayed",
        published_at=datetime(2024, 1, 2),
        available_at=datetime(2024, 1, 10),
        source="example",
        provider_id="test",
        headline="AAPL earnings beat",
        ticker_mentions=["AAPL"],
    )
    session.add(article)
    session.flush()
    session.add(
        NewsAnalysis(
            news_id=article.id,
            stock_id=stock.id,
            sentiment_score=0.5,
            sentiment_label="positive",
            relevance_score=1.0,
            is_earnings=True,
        )
    )
    session.commit()

    svc = NewsService(session)
    before_available = svc.get_weekly_news_features(stock.id, date(2024, 1, 7))
    after_available = svc.get_weekly_news_features(stock.id, date(2024, 1, 12))

    assert before_available["news_volume"] == 0.0
    assert after_available["news_volume"] == 1.0
    assert after_available["news_earnings_flag"] == 1.0
