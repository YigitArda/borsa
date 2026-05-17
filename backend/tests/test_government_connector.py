from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.data_source_health import DataConnector
from app.models.smallcap_signals import GovernmentContract
from app.models.stock import Stock
from app.services.connectors.optional import USASpendingConnector


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Stock.__table__,
            DataConnector.__table__,
            GovernmentContract.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def test_usaspending_is_configured():
    session = make_session()
    assert USASpendingConnector(session).is_configured() is True


def test_usaspending_persist_award(monkeypatch):
    monkeypatch.setattr("app.services.connectors.optional.settings.connector_request_timeout", 20)

    session = make_session()
    stock = Stock(ticker="AAPL", name="Apple Inc.")
    session.add(stock)
    session.commit()

    fake_response = {
        "results": [
            {
                "Award ID": "CONT_AWD_TEST123",
                "Recipient Name": "Apple Inc.",
                "Awarding Agency": "Department of Defense",
                "Award Amount": 5000000.0,
                "Description": "Software license contract",
                "Contract Award Type": "D",
                "Period of Performance Current End Date": "2024-12-31",
                "Action Date": "2024-03-01",
            }
        ]
    }

    with patch("app.services.connectors.optional.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_response
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = USASpendingConnector(session).run(tickers=["AAPL"])

    assert result.status == "ok"
    assert result.rows == 1

    contract = session.query(GovernmentContract).first()
    assert contract is not None
    assert contract.award_id == "CONT_AWD_TEST123"
    assert contract.award_amount == 5000000.0
    assert contract.award_date == date(2024, 3, 1)
    assert contract.stock_id == stock.id


def test_usaspending_skips_small_awards(monkeypatch):
    monkeypatch.setattr("app.services.connectors.optional.settings.connector_request_timeout", 20)

    session = make_session()
    stock = Stock(ticker="AAPL", name="Apple Inc.")
    session.add(stock)
    session.commit()

    fake_response = {
        "results": [
            {
                "Award ID": "SMALL_AWARD",
                "Recipient Name": "Apple Inc.",
                "Award Amount": 500000.0,
                "Action Date": "2024-03-01",
                "Awarding Agency": "GSA",
                "Description": "Small contract",
                "Contract Award Type": "A",
                "Period of Performance Current End Date": None,
            }
        ]
    }

    with patch("app.services.connectors.optional.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_response
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = USASpendingConnector(session).run(tickers=["AAPL"])

    assert result.rows == 0
    assert session.query(GovernmentContract).count() == 0
