from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.prediction import PaperTrade, WeeklyPrediction
from app.models.price import PriceDaily
from app.models.stock import Stock
from app.services.paper_trading import PaperTradingService


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_paper_trading_opens_and_evaluates_prediction():
    session = _session()
    stock = Stock(ticker="AAPL", name="Apple")
    session.add(stock)
    session.flush()

    pred = WeeklyPrediction(
        week_starting=date(2026, 5, 11),
        stock_id=stock.id,
        strategy_id=1,
        prob_2pct=0.65,
        expected_return=0.03,
        confidence="high",
        rank=1,
    )
    session.add(pred)
    session.flush()

    prices = [
        PriceDaily(stock_id=stock.id, date=date(2026, 5, 11), open=100, high=101, low=99, close=100, volume=1_000_000),
        PriceDaily(stock_id=stock.id, date=date(2026, 5, 12), open=100, high=103, low=100, close=102, volume=1_000_000),
        PriceDaily(stock_id=stock.id, date=date(2026, 5, 15), open=102, high=104, low=101, close=103, volume=1_000_000),
    ]
    session.add_all(prices)
    session.commit()

    svc = PaperTradingService(session)
    assert svc.open_from_predictions(week_starting=date(2026, 5, 11)) == 1
    assert svc.open_from_predictions(week_starting=date(2026, 5, 11)) == 0

    summary = svc.evaluate_open_positions(as_of=date(2026, 5, 18))
    trade = session.query(PaperTrade).one()

    assert summary["evaluated_now"] == 1
    assert trade.status == "closed"
    assert round(trade.realized_return, 4) == 0.03
    assert trade.hit_2pct is True
    assert trade.hit_3pct is True
