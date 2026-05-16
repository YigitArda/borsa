from datetime import date

import pandas as pd
import pytest


def test_intraday_spike_detects_four_percent_boundary():
    from app.services.intraday_event_detector import IntradayEventDetector

    detector = IntradayEventDetector(session=object())
    prices = pd.DataFrame(
        [
            {"date": date(2026, 1, 5), "open": 100.0, "high": 104.0, "low": 99.0, "close": 102.0, "volume": 1_000},
            {"date": date(2026, 1, 6), "open": 102.0, "high": 102.5, "low": 100.5, "close": 101.0, "volume": 1_100},
        ]
    )

    metrics = detector._compute_spike_metrics(prices)

    assert metrics is not None
    assert metrics["spike_type"] == "up"
    assert metrics["max_up"] == pytest.approx(0.04)
    assert metrics["spike_day"] == date(2026, 1, 5)


def test_intraday_spike_stays_normal_below_threshold():
    from app.services.intraday_event_detector import IntradayEventDetector

    detector = IntradayEventDetector(session=object())
    prices = pd.DataFrame(
        [
            {"date": date(2026, 1, 5), "open": 100.0, "high": 103.9, "low": 99.2, "close": 102.0, "volume": 1_000},
            {"date": date(2026, 1, 6), "open": 102.0, "high": 102.4, "low": 100.8, "close": 101.0, "volume": 1_100},
        ]
    )

    metrics = detector._compute_spike_metrics(prices)

    assert metrics is not None
    assert metrics["spike_type"] == "normal"
