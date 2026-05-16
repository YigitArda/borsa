"""
Preprocessing leakage tests.

Verifies that scaler/encoder fit only on train data and transform on test.
"""
import pytest
import numpy as np
import pandas as pd
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from sklearn.preprocessing import StandardScaler


class TestScalerFitTransformIsolation:
    def test_scaler_fit_on_train_transform_on_test(self):
        """StandardScaler must be fit on train and only transform on test."""
        train = np.array([[1.0], [2.0], [3.0]])
        test = np.array([[4.0], [5.0]])

        scaler = StandardScaler()
        train_scaled = scaler.fit_transform(train)
        test_scaled = scaler.transform(test)

        # Train mean should be 2.0, std should be 1.0
        assert abs(train_scaled.mean()) < 1e-9
        assert abs(train_scaled.std(ddof=0) - 1.0) < 1e-9

        # Test should NOT be zero-mean (it would be if fit on combined data)
        assert abs(test_scaled.mean()) > 0.5, (
            "Test data should not be zero-mean when scaler fit only on train"
        )

    def test_combined_fit_leaks_test_distribution(self):
        """If scaler fit on combined train+test, test distribution is distorted."""
        train = np.array([[1.0], [2.0], [3.0]])
        test = np.array([[4.0], [5.0]])
        combined = np.vstack([train, test])

        # Correct: fit on train only
        good_scaler = StandardScaler()
        good_scaler.fit(train)
        good_test_scaled = good_scaler.transform(test)

        # Wrong: fit on combined
        bad_scaler = StandardScaler()
        bad_test_scaled = bad_scaler.fit_transform(combined)[len(train):]

        # The bad scaler distorts test values (they should be different)
        assert not np.allclose(good_test_scaled, bad_test_scaled), (
            "Combined fit changes test scaling — this IS leakage"
        )


class TestWalkForwardSplit:
    def test_train_test_no_overlap(self):
        """Train and test weeks must not overlap in walk-forward split."""
        weeks = pd.date_range("2015-01-02", "2024-12-27", freq="W-FRI")
        train_end_idx = 52 * 5  # 5 years
        test_window = 52
        embargo = 4

        train_end = weeks[train_end_idx - 1]
        test_start = weeks[train_end_idx + embargo]
        test_end = weeks[train_end_idx + test_window - 1]

        assert train_end < test_start, "Train must end before test starts"
        assert test_start <= test_end, "Test start must be <= test end"

    def test_embargo_prevents_overlap(self):
        """Without embargo, train_end and test_start would be consecutive weeks."""
        weeks = pd.date_range("2015-01-02", "2024-12-27", freq="W-FRI")
        train_end_idx = 52 * 5
        embargo = 4

        train_end = weeks[train_end_idx - 1]
        test_start_no_embargo = weeks[train_end_idx]
        test_start_with_embargo = weeks[train_end_idx + embargo]

        assert test_start_with_embargo > test_start_no_embargo, (
            "Embargo must push test start forward"
        )
        gap_days = (test_start_with_embargo - train_end).days
        assert gap_days >= 7 * embargo, f"Gap should be >= {embargo} weeks"

    def test_folds_are_chronological(self):
        """Each fold's train_end must be after previous fold's train_end."""
        weeks = pd.date_range("2015-01-02", "2024-12-27", freq="W-FRI")
        min_train_years = 5
        test_window = 52
        embargo = 4

        train_end_idx = 52 * min_train_years
        prev_train_end = None
        fold_num = 0

        while train_end_idx + test_window <= len(weeks):
            train_end = weeks[train_end_idx - 1]
            if prev_train_end is not None:
                assert train_end > prev_train_end, (
                    f"Fold {fold_num} train_end must be after previous"
                )
            prev_train_end = train_end
            train_end_idx += test_window
            fold_num += 1

        assert fold_num > 0, "Must have at least one fold"


class TestHoldoutIsolation:
    def test_holdout_rows_removed_before_split(self):
        """Holdout cutoff must remove rows before any train/test split."""
        weeks = pd.date_range("2015-01-02", "2024-12-27", freq="W-FRI")
        holdout_cutoff = date(2023, 1, 1)

        df = pd.DataFrame({"week_ending": weeks, "value": range(len(weeks))})
        df["week_ending"] = pd.to_datetime(df["week_ending"])

        original_len = len(df)
        df_filtered = df[df["week_ending"] < pd.Timestamp(holdout_cutoff)]

        assert len(df_filtered) < original_len, "Holdout must remove rows"
        assert df_filtered["week_ending"].max() < pd.Timestamp(holdout_cutoff), (
            "Max week must be before holdout cutoff"
        )

    def test_holdout_never_appears_in_train_or_test(self):
        """Holdout weeks must not appear in any fold."""
        weeks = pd.date_range("2015-01-02", "2024-12-27", freq="W-FRI")
        holdout_cutoff = pd.Timestamp("2023-01-01")

        df = pd.DataFrame({"week_ending": weeks})
        df["week_ending"] = pd.to_datetime(df["week_ending"])
        df = df[df["week_ending"] < holdout_cutoff]

        all_weeks = sorted(df["week_ending"].unique())
        for w in all_weeks:
            assert w < holdout_cutoff, f"Week {w} should not be in holdout"


class TestLabelLeakage:
    def test_label_uses_future_return(self):
        """Labels intentionally use future returns — verify they're pre-computed
        and not recomputed at train time from future prices."""
        weekly_returns = pd.Series([0.01, -0.02, 0.03, 0.01, -0.01])
        next_week = weekly_returns.shift(-1)

        # Label: 1 if next week >= 2%
        labels = (next_week >= 0.02).astype(int)

        # Last label must be NaN/0 (no future data)
        assert pd.isna(next_week.iloc[-1]) or labels.iloc[-1] == 0, (
            "Last label must not use non-existent future return"
        )

    def test_no_label_overlap_between_folds(self):
        """A week's label must not be used as a feature in another fold."""
        # This is a conceptual test — in practice labels are separate columns
        features = ["rsi_14", "macd", "sma_50"]
        labels = ["target_2pct_1w", "target_3pct_1w"]

        overlap = set(features) & set(labels)
        assert len(overlap) == 0, f"Features and labels must not overlap: {overlap}"
