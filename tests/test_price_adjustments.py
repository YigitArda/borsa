from datetime import date

import pandas as pd

from app.services.data_ingestion import DataIngestionService
from app.services.price_adjustments import adjusted_ohlc


def test_daily_ingestion_preserves_raw_close_and_adj_close():
    df = pd.DataFrame({
        "Date": [pd.Timestamp(date(2026, 5, 15))],
        "Open": [99.0],
        "High": [105.0],
        "Low": [98.0],
        "Close": [100.0],
        "Adj Close": [90.0],
        "Volume": [1_000_000],
    })

    rows = DataIngestionService(None)._build_daily_price_rows(stock_id=7, df=df)

    assert rows[0]["close"] == 100.0
    assert rows[0]["adj_close"] == 90.0


def test_adjusted_ohlc_scales_raw_ohlc_to_adj_close_basis():
    adjusted = adjusted_ohlc(99.0, 105.0, 98.0, 100.0, 90.0)

    assert adjusted["close"] == 90.0
    assert round(adjusted["open"], 2) == 89.1
    assert round(adjusted["high"], 2) == 94.5
    assert round(adjusted["low"], 2) == 88.2
