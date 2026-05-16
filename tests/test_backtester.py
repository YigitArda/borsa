from datetime import date

from app.services.backtester import Trade


def test_trade_handles_zero_entry_price():
    trade = Trade(
        ticker="AAPL",
        stock_id=1,
        entry_date=date(2026, 5, 11),
        exit_date=date(2026, 5, 18),
        entry_price=0.0,
        exit_price=10.0,
        signal_strength=0.9,
    )

    assert trade.return_pct == 0.0
    assert trade.pnl == 0.0
