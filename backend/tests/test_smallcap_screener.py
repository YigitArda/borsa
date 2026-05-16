from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models.financial import FinancialMetric
from app.models.macro import MacroIndicator
from app.models.news import NewsArticle
from app.models.price import PriceDaily
from app.models.regime import MarketRegime
from app.models.short_interest import ShortInterestData
from app.models.smallcap_signals import (
    GovernmentContract,
    InsiderTransaction,
    InstitutionalPosition,
    SmallCapRadarResult,
)
from app.models.stock import Stock
from app.services.insider_buying import InsiderBuyingService
from app.services.smallcap_screener import SmallCapScreener


class _Response:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Stock.__table__,
            PriceDaily.__table__,
            FinancialMetric.__table__,
            MacroIndicator.__table__,
            MarketRegime.__table__,
            NewsArticle.__table__,
            ShortInterestData.__table__,
            InsiderTransaction.__table__,
            GovernmentContract.__table__,
            InstitutionalPosition.__table__,
            SmallCapRadarResult.__table__,
        ],
    )
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


def test_mock_form4_ingest_and_ceo_open_market_score(db_session):
    stock = Stock(ticker="RKLB", name="Rocket Lab USA Inc", exchange="NASDAQ", is_active=True)
    db_session.add(stock)
    db_session.commit()

    submissions = {
        "filings": {
            "recent": {
                "form": ["4"],
                "filingDate": ["2024-03-05"],
                "accessionNumber": ["0001234567-24-000001"],
            }
        }
    }
    form4 = """<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Jane CEO</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><officerTitle>Chief Executive Officer</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>100</value></transactionPricePerShare>
      </transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>5000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""

    with patch("app.services.insider_buying.get_cik", return_value="0000123456"):
        with patch(
            "app.services.insider_buying.requests.get",
            side_effect=[_Response(submissions), _Response(text=form4)],
        ):
            service = InsiderBuyingService(db_session)
            rows = service.ingest_ticker("RKLB", lookback_days=90, as_of_date=date(2024, 3, 8))

    score = InsiderBuyingService(db_session).get_insider_score(stock.id, date(2024, 3, 8))
    assert rows == 1
    assert score["buys"] == 1
    assert score["score"] == 52.0


def test_insider_selling_over_half_of_buying_zeroes_score(db_session):
    stock = Stock(ticker="SELL", name="Seller Inc", exchange="NASDAQ", is_active=True)
    db_session.add(stock)
    db_session.flush()
    db_session.add_all(
        [
            InsiderTransaction(
                stock_id=stock.id,
                filed_date=date(2024, 3, 1),
                insider_name="Buyer",
                transaction_type="buy",
                total_value=100_000,
                is_open_market=True,
            ),
            InsiderTransaction(
                stock_id=stock.id,
                filed_date=date(2024, 3, 2),
                insider_name="Seller",
                transaction_type="sell",
                total_value=60_000,
                is_open_market=False,
            ),
        ]
    )
    db_session.commit()

    score = InsiderBuyingService(db_session).get_insider_score(stock.id, date(2024, 3, 8))
    assert score["score"] == 0.0
    assert score["sells"] == 1


def test_vix_over_30_returns_empty_scan(db_session):
    screener = SmallCapScreener(db_session)
    with patch.object(screener, "get_regime_context", return_value=("BEAR", 0.5, 35.0)):
        assert screener.run_scan(date(2024, 3, 8), top_n=5) == []


def test_low_dollar_volume_eliminates_ticker(db_session):
    stock = Stock(ticker="LOWV", name="Low Volume Inc", exchange="NASDAQ", is_active=True)
    db_session.add(stock)
    db_session.flush()
    db_session.add(
        PriceDaily(
            stock_id=stock.id,
            date=date(2024, 3, 7),
            open=10,
            high=10,
            low=10,
            close=10,
            adj_close=10,
            volume=10_000,
        )
    )
    db_session.commit()

    screener = SmallCapScreener(db_session)
    with patch.object(screener, "get_regime_context", return_value=("NEUTRAL", 0.85, 18.0)):
        result = screener.score_ticker("LOWV", date(2024, 3, 8))

    assert result.eliminated is True
    assert result.elimination_reason == "insufficient_liquidity"
