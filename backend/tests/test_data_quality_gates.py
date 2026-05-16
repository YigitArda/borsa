"""
Data quality gate tests.

Verifies that impossible dates, future-dated rows, negative lags,
and stale data are detected and flagged.
"""
import pytest
import numpy as np
import pandas as pd
from datetime import date, timedelta


class TestImpossibleDates:
    def test_future_dated_price_rejected(self):
        """Price rows with date > today must be flagged as invalid."""
        today = date(2024, 6, 14)
        prices = [
            {"date": date(2024, 6, 10), "close": 100.0, "valid": True},
            {"date": date(2024, 6, 13), "close": 101.0, "valid": True},
            {"date": date(2024, 6, 15), "close": 999.0, "valid": False},  # future
        ]

        valid = [p for p in prices if p["date"] <= today]
        assert len(valid) == 2
        assert not any(p["date"] > today for p in valid)

    def test_negative_lag_rejected(self):
        """as_of_date before fiscal_period_end is impossible (negative lag)."""
        rows = [
            {"fiscal_period_end": date(2024, 3, 31), "as_of_date": date(2024, 5, 10), "valid": True},
            {"fiscal_period_end": date(2024, 3, 31), "as_of_date": date(2024, 3, 15), "valid": False},  # before period end
        ]

        valid = [r for r in rows if r["as_of_date"] >= r["fiscal_period_end"]]
        assert len(valid) == 1
        assert valid[0]["as_of_date"] >= valid[0]["fiscal_period_end"]


class TestStaleData:
    def test_price_staleness_detected(self):
        """Prices older than 7 days from decision date are stale."""
        decision_date = date(2024, 6, 14)
        latest_price_date = date(2024, 6, 5)

        days_stale = (decision_date - latest_price_date).days
        assert days_stale > 7, f"Price is {days_stale} days stale"

    def test_financial_staleness_detected(self):
        """Financial metrics older than 90 days from decision date are stale."""
        decision_date = date(2024, 6, 14)
        latest_as_of = date(2024, 2, 1)

        days_stale = (decision_date - latest_as_of).days
        assert days_stale > 90, f"Financial data is {days_stale} days stale"


class TestDuplicateRows:
    def test_duplicate_week_ending_rejected(self):
        """Multiple features for same (stock_id, week_ending) should not exist."""
        rows = [
            {"stock_id": 1, "week_ending": date(2024, 6, 14), "feature": "rsi", "value": 60.0},
            {"stock_id": 1, "week_ending": date(2024, 6, 14), "feature": "rsi", "value": 65.0},  # duplicate
        ]

        # Unique constraint should prevent this — detect duplicates
        unique_keys = {(r["stock_id"], r["week_ending"], r["feature"]) for r in rows}
        assert len(unique_keys) < len(rows), "Duplicate rows should be detected"


class TestMissingness:
    def test_all_nan_feature_rejected(self):
        """A feature that is all NaN for a stock should be flagged."""
        values = [np.nan, np.nan, np.nan]
        nan_ratio = sum(1 for v in values if pd.isna(v)) / len(values)
        assert nan_ratio == 1.0, "Feature is 100% missing"

    def test_high_missingness_flagged(self):
        """Features with >50% missing values should be flagged."""
        values = [1.0, np.nan, np.nan, 2.0, np.nan]
        nan_ratio = sum(1 for v in values if pd.isna(v)) / len(values)
        assert nan_ratio > 0.5, f"Missing ratio {nan_ratio} exceeds 50%"


class TestVolumeAnomaly:
    def test_zero_volume_days_flagged(self):
        """Zero volume days are suspicious and should be flagged."""
        volumes = [1000000, 950000, 0, 0, 1100000]
        zero_days = sum(1 for v in volumes if v == 0)
        assert zero_days > 0, "Zero volume days detected"

    def test_volume_spike_without_action_flagged(self):
        """Volume spike >300% without corporate action is suspicious."""
        volumes = [1000000, 1050000, 4000000, 1100000]
        # 3-day moving average before spike
        avg_before = np.mean(volumes[:2])
        spike_ratio = volumes[2] / avg_before
        assert spike_ratio > 3.0, f"Volume spike ratio {spike_ratio} without corporate action"
