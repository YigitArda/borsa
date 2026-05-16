from datetime import date, timedelta

import pandas as pd
import pytest


def test_backtester_mt_m_equity_and_kelly_cap(monkeypatch):
    from app.config import settings
    from app.services.backtester import Backtester

    monkeypatch.setattr(settings, "transaction_cost_bps", 0.0, raising=False)
    monkeypatch.setattr(settings, "slippage_bps", 0.0, raising=False)

    week0 = date(2026, 1, 2)
    week1 = week0 + timedelta(weeks=1)

    predictions = pd.DataFrame(
        [
            {"week_ending": week0, "ticker": "AAPL", "stock_id": 1, "prob": 0.9},
            {"week_ending": week1, "ticker": "AAPL", "stock_id": 1, "prob": 0.0},
        ]
    )

    price_rows = [
        {"date": week0 + timedelta(days=3), "ticker": "AAPL", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {"date": week0 + timedelta(days=4), "ticker": "AAPL", "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.0},
        {"date": week0 + timedelta(days=5), "ticker": "AAPL", "open": 102.0, "high": 103.0, "low": 101.0, "close": 102.0},
        {"date": week0 + timedelta(days=6), "ticker": "AAPL", "open": 103.0, "high": 104.0, "low": 102.0, "close": 103.0},
        {"date": week0 + timedelta(days=7), "ticker": "AAPL", "open": 109.0, "high": 111.0, "low": 108.0, "close": 110.0},
        {"date": week1 + timedelta(days=3), "ticker": "AAPL", "open": 105.0, "high": 106.0, "low": 104.0, "close": 106.0},
        {"date": week1 + timedelta(days=4), "ticker": "AAPL", "open": 106.0, "high": 107.0, "low": 105.0, "close": 107.0},
        {"date": week1 + timedelta(days=5), "ticker": "AAPL", "open": 107.0, "high": 108.0, "low": 106.0, "close": 108.0},
        {"date": week1 + timedelta(days=6), "ticker": "AAPL", "open": 108.0, "high": 109.0, "low": 107.0, "close": 109.0},
        {"date": week1 + timedelta(days=7), "ticker": "AAPL", "open": 109.0, "high": 111.0, "low": 108.0, "close": 110.0},
    ]
    prices = pd.DataFrame(price_rows)

    backtester = Backtester(
        predictions_df=predictions,
        price_df=prices,
        threshold=0.5,
        top_n=5,
        holding_weeks=1,
        kelly_fraction=0.6,
    )

    result = backtester.run()

    assert backtester._position_size(n_positions=1, regime_mult=1.0) == pytest.approx(0.2)
    assert result.n_trades == 1
    assert result.trades[0].return_pct == pytest.approx(0.10)
    assert result.equity_curve.iloc[-1] == pytest.approx(1.02)
