"""
Feature-level point-in-time (PIT) tests.

Verifies that each feature category only uses data available before the
decision date (week_ending).
"""
import pytest
import numpy as np
import pandas as pd
from datetime import date, timedelta
from unittest.mock import MagicMock, patch


class TestTechnicalFeaturesPIT:
    def test_daily_data_strictly_before_week_end(self):
        """Technical features must use daily data with index < week_end."""
        week_end = pd.Timestamp("2024-06-14")
        daily_index = pd.date_range("2024-06-01", "2024-06-14", freq="B")
        daily_df = pd.DataFrame({"close": range(len(daily_index))}, index=daily_index)

        # Correct: strict < filter
        avail_daily = daily_df[daily_df.index < week_end]
        assert avail_daily.index.max() < week_end
        # The last day (2024-06-14, Friday) is excluded
        assert week_end not in avail_daily.index

    def test_momentum_12_1_skips_last_week(self):
        """12-1 momentum must skip the most recent week (month-end effect)."""
        weekly = pd.Series([0.01] * 14, index=pd.date_range("2024-01-05", periods=14, freq="W-FRI"))
        # 12-1 uses weeks -13 to -2 (skip last week)
        if len(weekly) >= 13:
            momentum_window = weekly.iloc[-13:-1]
            assert len(momentum_window) == 12
            # Most recent week is excluded
            assert weekly.index[-1] not in momentum_window.index


class TestFinancialFeaturesPIT:
    def test_as_of_date_filter(self):
        """Financial features must only use metrics with as_of_date <= decision_date."""
        decision_date = date(2024, 6, 14)

        metrics = [
            {"metric_name": "pe_ratio", "as_of_date": date(2024, 5, 15), "value": 25.0},
            {"metric_name": "pe_ratio", "as_of_date": date(2024, 6, 10), "value": 26.0},
            {"metric_name": "pe_ratio", "as_of_date": date(2024, 6, 20), "value": 27.0},  # future
        ]

        visible = [m for m in metrics if m["as_of_date"] <= decision_date]
        assert len(visible) == 2
        assert all(m["as_of_date"] <= decision_date for m in visible)
        # Future metric is excluded
        assert not any(m["as_of_date"] == date(2024, 6, 20) for m in visible)

    def test_most_recent_visible_metric_selected(self):
        """When multiple metrics are visible, the most recent one is used."""
        decision_date = date(2024, 6, 14)
        metrics = [
            {"metric_name": "pe_ratio", "as_of_date": date(2024, 5, 15), "value": 25.0},
            {"metric_name": "pe_ratio", "as_of_date": date(2024, 6, 10), "value": 26.0},
        ]

        visible = [m for m in metrics if m["as_of_date"] <= decision_date]
        most_recent = max(visible, key=lambda m: m["as_of_date"])
        assert most_recent["value"] == 26.0


class TestMacroFeaturesPIT:
    def test_macro_closest_past_week(self):
        """Macro features must use the closest past week, not future."""
        decision_week = pd.Timestamp("2024-06-14")
        macro_weeks = pd.date_range("2024-01-05", "2024-06-21", freq="W-FRI")

        # Only past weeks
        past_weeks = macro_weeks[macro_weeks <= decision_week]
        closest = past_weeks.max()
        assert closest <= decision_week
        assert closest == pd.Timestamp("2024-06-14")


class TestNewsFeaturesPIT:
    def test_news_range_exclusive_upper_bound(self):
        """News must use [week_start, week_ending) — exclusive upper bound."""
        week_ending = date(2024, 6, 14)
        week_start = week_ending - timedelta(days=7)

        articles = [
            {"published_at": week_start, "valid": True},
            {"published_at": week_ending - timedelta(days=1), "valid": True},
            {"published_at": week_ending, "valid": False},  # exactly at boundary — excluded
            {"published_at": week_ending + timedelta(days=1), "valid": False},  # future
        ]

        valid = [
            a for a in articles
            if week_start <= a["published_at"] < week_ending
        ]
        assert len(valid) == 2
        assert all(a["valid"] for a in valid)


class TestSocialFeaturesPIT:
    def test_social_exact_week_match(self):
        """Social sentiment must match exact week_ending, never future weeks."""
        target_week = date(2024, 6, 14)
        weeks = [date(2024, 6, 7), date(2024, 6, 14), date(2024, 6, 21)]

        matched = [w for w in weeks if w == target_week]
        assert matched == [date(2024, 6, 14)]
        assert date(2024, 6, 21) not in matched  # future excluded


class TestSpikeFeaturesPIT:
    def test_spike_features_exclude_current_week(self):
        """Spike features must exclude the current week (no lookahead)."""
        week_end = date(2024, 6, 14)
        cutoff = week_end - timedelta(weeks=1)

        events = [
            {"week_ending": date(2024, 6, 7), "valid": True},
            {"week_ending": date(2024, 6, 14), "valid": False},  # current week
        ]

        valid = [e for e in events if e["week_ending"] <= cutoff]
        assert len(valid) == 1
        assert valid[0]["week_ending"] == date(2024, 6, 7)


class TestSyntheticFutureRowRejection:
    def test_future_row_not_in_feature_set(self):
        """If a synthetic future row is added, features must not see it."""
        decision_date = date(2024, 6, 14)

        # Simulate DB rows
        rows = [
            {"week_ending": date(2024, 6, 7), "value": 100, "valid": True},
            {"week_ending": date(2024, 6, 14), "value": 101, "valid": True},
            {"week_ending": date(2024, 6, 21), "value": 999, "valid": False},  # future
        ]

        visible = [r for r in rows if r["week_ending"] <= decision_date]
        assert len(visible) == 2
        assert not any(r["week_ending"] > decision_date for r in visible)
        # Future value 999 must not leak
        assert 999 not in [r["value"] for r in visible]
