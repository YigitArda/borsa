"""Scientific backtest engine.

Implements purged cross-validation, triple-barrier labels, meta-label filtering,
and Benjamini-Hochberg multiple-testing control for strategy research.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, clone
from sklearn.model_selection import BaseCrossValidator

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Container for a single scientific backtest split result."""

    primary_return: float
    meta_accuracy: float
    sharpe: float
    max_drawdown: float
    trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    in_sample: bool = False
    fold: int | str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Hypothesis:
    """Falsifiable trading hypothesis evaluated before promotion."""

    name: str
    mechanism: str
    expected_edge: float
    asset_universe: str
    timeframe: str
    max_drawdown_tolerance: float = 0.20
    min_sharpe: float = 1.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "UNTESTED"
    results: list[BacktestResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mechanism": self.mechanism,
            "expected_edge": self.expected_edge,
            "asset_universe": self.asset_universe,
            "timeframe": self.timeframe,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "results_count": len(self.results),
        }


class PurgedKFold(BaseCrossValidator):
    """Purged K-fold split with an embargo around each test fold."""

    def __init__(self, n_splits: int = 5, pct_embargo: float = 0.02):
        if n_splits < 2:
            raise ValueError("n_splits must be at least 2")
        if pct_embargo < 0:
            raise ValueError("pct_embargo must be non-negative")
        self.n_splits = n_splits
        self.pct_embargo = pct_embargo

    def split(self, X, y=None, groups=None):  # noqa: N803 - sklearn signature
        n_samples = len(X)
        if n_samples < self.n_splits:
            raise ValueError("n_samples must be >= n_splits")

        indices = np.arange(n_samples)
        fold_sizes = np.full(self.n_splits, n_samples // self.n_splits, dtype=int)
        fold_sizes[: n_samples % self.n_splits] += 1
        embargo = int(np.ceil(n_samples * self.pct_embargo))

        start = 0
        for fold_size in fold_sizes:
            stop = start + fold_size
            test_indices = indices[start:stop]

            train_left_end = max(0, start - embargo)
            train_right_start = min(n_samples, stop + embargo)
            train_indices = np.concatenate(
                [indices[:train_left_end], indices[train_right_start:]]
            )
            yield train_indices, test_indices
            start = stop

    def get_n_splits(self, X=None, y=None, groups=None):  # noqa: N803
        return self.n_splits


class CombinatorialPurgedKFold(BaseCrossValidator):
    """Combinatorial purged CV with multiple test groups per split."""

    def __init__(
        self,
        n_groups: int = 6,
        n_test_groups: int = 2,
        pct_embargo: float = 0.02,
        max_splits: int | None = None,
    ):
        if n_groups < 2:
            raise ValueError("n_groups must be at least 2")
        if not 1 <= n_test_groups < n_groups:
            raise ValueError("n_test_groups must be between 1 and n_groups - 1")
        self.n_groups = n_groups
        self.n_test_groups = n_test_groups
        self.pct_embargo = pct_embargo
        self.max_splits = max_splits

    def split(self, X, y=None, groups=None):  # noqa: N803
        n_samples = len(X)
        if n_samples < self.n_groups:
            raise ValueError("n_samples must be >= n_groups")

        indices = np.arange(n_samples)
        group_sizes = np.full(self.n_groups, n_samples // self.n_groups, dtype=int)
        group_sizes[: n_samples % self.n_groups] += 1
        starts = np.r_[0, np.cumsum(group_sizes)[:-1]]
        stops = np.cumsum(group_sizes)
        embargo = int(np.ceil(n_samples * self.pct_embargo))

        split_iter = combinations(range(self.n_groups), self.n_test_groups)
        for split_num, test_groups in enumerate(split_iter):
            if self.max_splits is not None and split_num >= self.max_splits:
                break

            test_mask = np.zeros(n_samples, dtype=bool)
            purge_mask = np.zeros(n_samples, dtype=bool)
            for group_idx in test_groups:
                start, stop = int(starts[group_idx]), int(stops[group_idx])
                test_mask[start:stop] = True
                purge_mask[max(0, start - embargo) : min(n_samples, stop + embargo)] = True

            yield indices[~purge_mask], indices[test_mask]

    def get_n_splits(self, X=None, y=None, groups=None):  # noqa: N803
        total = len(list(combinations(range(self.n_groups), self.n_test_groups)))
        return min(total, self.max_splits) if self.max_splits is not None else total


class TripleBarrierMethod:
    """Label events by profit-taking, stop-loss, or vertical barrier touch."""

    def __init__(
        self,
        pt_sl: tuple[float, float] = (1.0, 1.0),
        min_ret: float = 0.005,
        num_days: int = 5,
    ):
        self.pt_sl = pt_sl
        self.min_ret = min_ret
        self.num_days = num_days

    def get_events(
        self,
        close: pd.Series,
        t_events: pd.DatetimeIndex,
        target: pd.Series,
        vertical_barrier_times: pd.Series | None = None,
        side: pd.Series | None = None,
    ) -> pd.DataFrame:
        close = close.sort_index().dropna()
        t_events = pd.DatetimeIndex([t for t in t_events if t in close.index])
        target = target.reindex(t_events).dropna()
        target = target[target >= self.min_ret]
        t_events = pd.DatetimeIndex(target.index)

        if vertical_barrier_times is None:
            vertical_barrier_times = self._vertical_barriers(close.index, t_events)
        else:
            vertical_barrier_times = vertical_barrier_times.reindex(t_events)

        events = pd.DataFrame(index=t_events)
        events["t1"] = vertical_barrier_times
        events["trgt"] = target
        events["side"] = side.reindex(t_events) if side is not None else 1.0
        events = events.dropna(subset=["t1", "trgt"])

        touches = self._get_touches(close, events)
        events["t1"] = touches["t1"]
        events["ret"] = touches["ret"] * events["side"]
        events["label"] = np.sign(events["ret"]).astype(int)
        events["meta_label"] = (events["ret"] > 0).astype(int)
        events["barrier"] = touches["barrier"]
        return events

    def _vertical_barriers(
        self, close_index: pd.DatetimeIndex, t_events: pd.DatetimeIndex
    ) -> pd.Series:
        out: dict[pd.Timestamp, pd.Timestamp] = {}
        for event_time in t_events:
            pos = close_index.searchsorted(event_time + pd.Timedelta(days=self.num_days))
            if pos < len(close_index):
                out[event_time] = close_index[pos]
        return pd.Series(out)

    def _get_touches(self, close: pd.Series, events: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=events.index, columns=["t1", "ret", "barrier"])
        for start_time, row in events.iterrows():
            end_time = row["t1"]
            path = close.loc[start_time:end_time]
            if len(path) < 2 or row["trgt"] <= 0:
                out.loc[start_time] = [end_time, 0.0, "vertical"]
                continue

            returns = (path / close.loc[start_time] - 1.0) * row["side"]
            pt_level = self.pt_sl[0] * row["trgt"]
            sl_level = -self.pt_sl[1] * row["trgt"]
            pt_hits = returns[returns >= pt_level]
            sl_hits = returns[returns <= sl_level]

            first_pt = pt_hits.index.min() if not pt_hits.empty else pd.NaT
            first_sl = sl_hits.index.min() if not sl_hits.empty else pd.NaT

            if pd.isna(first_pt) and pd.isna(first_sl):
                touch_time = end_time
                barrier = "vertical"
            elif pd.isna(first_sl) or (not pd.isna(first_pt) and first_pt <= first_sl):
                touch_time = first_pt
                barrier = "pt"
            else:
                touch_time = first_sl
                barrier = "sl"

            raw_ret = close.loc[touch_time] / close.loc[start_time] - 1.0
            out.loc[start_time] = [touch_time, float(raw_ret), barrier]
        return out


class ScientificBacktestEngine:
    """Production-grade research backtester with leakage controls."""

    def __init__(
        self,
        n_splits: int = 6,
        pct_embargo: float = 0.04,
        fdr_threshold: float = 0.05,
        transaction_cost: float = 0.001,
    ):
        self.n_splits = n_splits
        self.pct_embargo = pct_embargo
        self.fdr_threshold = fdr_threshold
        self.transaction_cost = transaction_cost
        self.hypotheses: list[Hypothesis] = []

    def register_hypothesis(self, hypothesis: Hypothesis) -> None:
        self.hypotheses.append(hypothesis)
        logger.info("Registered hypothesis: %s", hypothesis.name)

    def cpcv_backtest(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        primary_model: BaseEstimator,
        events: pd.DatetimeIndex | None = None,
        target_volatility: pd.Series | None = None,
        meta_model: BaseEstimator | None = None,
        combinatorial: bool = True,
    ) -> list[BacktestResult]:
        """Run purged CV or CPCV and return split-level strategy metrics."""
        X, y = self._align_xy(X, y)
        cv: BaseCrossValidator
        if combinatorial:
            cv = CombinatorialPurgedKFold(
                n_groups=self.n_splits,
                n_test_groups=max(1, min(2, self.n_splits - 1)),
                pct_embargo=self.pct_embargo,
            )
        else:
            cv = PurgedKFold(n_splits=self.n_splits, pct_embargo=self.pct_embargo)

        results: list[BacktestResult] = []
        for fold_idx, (train_idx, test_idx) in enumerate(cv.split(X), start=1):
            if len(train_idx) == 0 or len(test_idx) == 0:
                continue

            X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
            y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
            train_target = self._model_target(y_train)

            primary = clone(primary_model)
            primary.fit(X_train, train_target)
            primary_pred = primary.predict(X_test)
            side = self._prediction_to_side(primary_pred)
            strategy_returns = self._calculate_returns(side, y_test, events=X_test.index)
            meta_accuracy = 0.5

            if meta_model is not None and len(strategy_returns) > 1:
                strategy_returns, meta_accuracy = self._apply_meta_label(
                    meta_model=clone(meta_model),
                    primary_model=primary,
                    X_train=X_train,
                    X_test=X_test,
                    y_train=y_train,
                    strategy_returns=strategy_returns,
                )

            results.append(self._result_from_returns(strategy_returns, fold=fold_idx))
            results[-1].meta_accuracy = float(meta_accuracy)

        return results

    def _apply_meta_label(
        self,
        meta_model: BaseEstimator,
        primary_model: BaseEstimator,
        X_train: pd.DataFrame,
        X_test: pd.DataFrame,
        y_train: pd.Series,
        strategy_returns: pd.Series,
    ) -> tuple[pd.Series, float]:
        train_side = self._prediction_to_side(primary_model.predict(X_train))
        train_returns = self._calculate_returns(train_side, y_train, events=X_train.index)
        train_labels = (train_returns > 0).astype(int)
        if train_labels.nunique() < 2:
            return strategy_returns, 0.5

        meta_train_features = self._extract_meta_features(primary_model, X_train, y_train)
        meta_test_features = self._extract_meta_features(
            primary_model, X_test, strategy_returns
        )
        try:
            meta_model.fit(meta_train_features, train_labels)
            meta_pred = pd.Series(meta_model.predict(meta_test_features), index=X_test.index)
        except Exception as exc:
            logger.warning("Meta-label model failed: %s", exc)
            return strategy_returns, 0.5

        meta_labels = (strategy_returns > 0).astype(int)
        meta_accuracy = float((meta_pred == meta_labels).mean())
        filtered = strategy_returns[meta_pred.astype(bool)]
        return filtered, meta_accuracy

    def _align_xy(self, X: pd.DataFrame, y: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
        joined = X.join(y.rename("__target__"), how="inner").dropna()
        return joined.drop(columns=["__target__"]), joined["__target__"]

    def _model_target(self, y: pd.Series) -> pd.Series:
        unique = set(pd.Series(y).dropna().unique().tolist())
        if unique and unique.issubset({-1, 0, 1}):
            return y
        return (y > 0).astype(int)

    def _prediction_to_side(self, predictions: np.ndarray | pd.Series) -> np.ndarray:
        pred = np.asarray(predictions, dtype=float)
        unique = set(np.unique(pred).tolist())
        if unique and unique.issubset({0.0, 1.0}):
            return np.where(pred > 0, 1.0, -1.0)
        return np.where(pred >= 0, 1.0, -1.0)

    def _calculate_returns(
        self, predictions: np.ndarray, actual: pd.Series, events: pd.Index
    ) -> pd.Series:
        side = pd.Series(predictions, index=events, dtype=float).reindex(actual.index)
        gross = side * actual.astype(float)
        turnover = side.diff().fillna(side).abs()
        return gross - self.transaction_cost * turnover

    def _extract_meta_features(
        self, model: BaseEstimator, X: pd.DataFrame, y: pd.Series
    ) -> pd.DataFrame:
        if hasattr(model, "predict_proba"):
            prob = model.predict_proba(X)
            confidence = np.max(prob, axis=1)
        else:
            confidence = np.full(len(X), 0.5)

        series = pd.Series(y, index=X.index, dtype=float)
        vol = series.rolling(20, min_periods=2).std().fillna(series.std() or 0.0)
        trend = series.rolling(10, min_periods=2).mean().abs() / (vol + 1e-6)
        return pd.DataFrame(
            {
                "confidence": confidence,
                "volatility": vol.to_numpy(),
                "trend_strength": trend.fillna(0.0).to_numpy(),
            },
            index=X.index,
        )

    def _result_from_returns(self, returns: pd.Series, fold: int | str) -> BacktestResult:
        clean = pd.Series(returns).dropna()
        sharpe = self._sharpe_ratio(clean)
        max_dd = self._max_drawdown(clean)
        wins = clean[clean > 0]
        losses = clean[clean < 0]
        return BacktestResult(
            primary_return=float(clean.sum()) if len(clean) else 0.0,
            meta_accuracy=0.5,
            sharpe=float(sharpe),
            max_drawdown=float(max_dd),
            trades=int(len(clean)),
            win_rate=float((clean > 0).mean()) if len(clean) else 0.0,
            avg_win=float(wins.mean()) if len(wins) else 0.0,
            avg_loss=float(losses.mean()) if len(losses) else 0.0,
            in_sample=False,
            fold=fold,
        )

    def _sharpe_ratio(self, returns: pd.Series, risk_free: float = 0.0) -> float:
        returns = pd.Series(returns).dropna()
        if len(returns) < 2 or returns.std() == 0:
            return 0.0
        return float((returns.mean() - risk_free) / returns.std() * np.sqrt(252))

    def _max_drawdown(self, returns: pd.Series) -> float:
        returns = pd.Series(returns).dropna()
        if returns.empty:
            return 0.0
        curve = (1.0 + returns).cumprod()
        running_max = curve.cummax()
        drawdown = (curve - running_max) / running_max
        return float(drawdown.min())

    def evaluate_hypothesis(
        self, hypothesis: Hypothesis, results: list[BacktestResult]
    ) -> bool:
        if not results:
            hypothesis.status = "REJECTED"
            return False

        sharpe_mean = float(np.mean([r.sharpe for r in results]))
        max_dd = float(min(r.max_drawdown for r in results))
        passes = (
            sharpe_mean >= hypothesis.min_sharpe
            and abs(max_dd) <= hypothesis.max_drawdown_tolerance
            and all(r.sharpe > 0 for r in results)
        )
        hypothesis.status = "VALIDATED" if passes else "REJECTED"
        hypothesis.results = results
        return passes

    def multiple_testing_adjustment(
        self, p_values: list[float] | np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Benjamini-Hochberg FDR control without an extra statsmodels dependency."""
        p = np.asarray(p_values, dtype=float)
        if p.size == 0:
            return np.array([], dtype=bool), np.array([], dtype=float)

        order = np.argsort(p)
        ranked = p[order]
        n = len(ranked)
        adjusted_sorted = np.empty(n, dtype=float)
        cumulative_min = 1.0
        for i in range(n - 1, -1, -1):
            rank = i + 1
            cumulative_min = min(cumulative_min, ranked[i] * n / rank)
            adjusted_sorted[i] = cumulative_min

        adjusted = np.empty(n, dtype=float)
        adjusted[order] = np.clip(adjusted_sorted, 0.0, 1.0)
        rejected = adjusted <= self.fdr_threshold
        return rejected, adjusted
