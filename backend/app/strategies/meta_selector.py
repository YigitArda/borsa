"""Regime-aware strategy selection with alpha-decay filtering."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class StrategyFitness:
    strategy_id: str
    name: str
    recent_sharpe: float
    regime_match: float
    decay_status: str
    capacity_remaining: float
    correlation_penalty: float
    weight: float = 0.0


class RegimeDetector:
    """Detect volatility/trend regimes from market return data."""

    def __init__(self, vol_window: int = 20, trend_window: int = 50):
        self.vol_window = vol_window
        self.trend_window = trend_window
        self.regime_history: list[str] = []

    def detect(self, market_data: pd.DataFrame) -> str:
        if market_data is None or market_data.empty or "returns" not in market_data:
            return "REGIME_UNCERTAIN"

        returns = pd.Series(market_data["returns"], dtype=float).dropna()
        if len(returns) < max(10, self.vol_window):
            return "REGIME_UNCERTAIN"

        vol_series = returns.rolling(self.vol_window, min_periods=5).std()
        vol = vol_series.iloc[-1]
        history = returns.rolling(min(252, max(self.vol_window, len(returns))), min_periods=5).std()
        vol_percentile = float((history <= vol).mean()) if not history.dropna().empty else 0.5

        sma_short = returns.rolling(20, min_periods=5).mean().iloc[-1]
        sma_long = returns.rolling(self.trend_window, min_periods=5).mean().iloc[-1]
        autocorr = returns.iloc[-20:].autocorr(lag=1)
        autocorr = 0.0 if pd.isna(autocorr) else float(autocorr)

        if vol_percentile > 0.80:
            regime = "HIGH_VOL"
        elif vol_percentile < 0.20:
            regime = "LOW_VOL"
        elif sma_short > sma_long * 1.02 and autocorr > 0.1:
            regime = "TRENDING_UP"
        elif sma_short < sma_long * 0.98 and autocorr > 0.1:
            regime = "TRENDING_DOWN"
        elif autocorr < -0.1:
            regime = "MEAN_REVERTING"
        else:
            regime = "REGIME_UNCERTAIN"

        self.regime_history.append(regime)
        return regime


class MetaStrategySelector:
    """Allocate capital across strategies using fitness, regime and decay state."""

    def __init__(
        self,
        max_strategies: int = 5,
        min_sharpe_threshold: float = 0.8,
        learning_rate: float = 0.15,
        correlation_limit: float = 0.70,
    ):
        self.max_strategies = max_strategies
        self.min_sharpe = min_sharpe_threshold
        self.lr = learning_rate
        self.corr_limit = correlation_limit
        self.regime_detector = RegimeDetector()
        self.current_regime: str | None = None
        self.current_weights: dict[str, float] = {}
        self.returns_matrix: pd.DataFrame = pd.DataFrame()

    def select(
        self,
        strategies: list[dict],
        market_data: pd.DataFrame,
        decay_monitor_results: pd.DataFrame | None = None,
    ) -> dict[str, float]:
        self.current_regime = self.regime_detector.detect(market_data)
        candidates = self._filter_candidates(strategies, decay_monitor_results)
        if not candidates:
            self.current_weights = {"CASH": 1.0}
            return self.current_weights

        fitness_scores: list[StrategyFitness] = []
        for strategy in candidates:
            recent_returns = pd.Series(strategy.get("recent_returns", []), dtype=float)
            sharpe = self._sharpe(recent_returns)
            regime_perf = strategy.get("regime_performance", {}) or {}
            regime_match = float(regime_perf.get(self.current_regime, 0.5))
            decay_status = self._decay_status(strategy["id"], decay_monitor_results)
            decay_penalty = {"HEALTHY": 1.0, "WARNING": 0.5, "CRITICAL": 0.0}.get(
                decay_status, 1.0
            )
            capacity = float(strategy.get("capacity_remaining", 1.0))
            if sharpe * regime_match * decay_penalty * capacity <= 0:
                continue

            fitness_scores.append(
                StrategyFitness(
                    strategy_id=strategy["id"],
                    name=strategy.get("name", strategy["id"]),
                    recent_sharpe=sharpe,
                    regime_match=regime_match,
                    decay_status=decay_status,
                    capacity_remaining=capacity,
                    correlation_penalty=0.0,
                )
            )

        fitness_scores = self._apply_correlation_penalty(fitness_scores)
        fitness_scores.sort(key=self._raw_fitness, reverse=True)
        selected = fitness_scores[: self.max_strategies]
        if not selected:
            self.current_weights = {"CASH": 1.0}
            return self.current_weights

        raw = np.array([max(self._raw_fitness(s), 1e-9) for s in selected])
        temperature = 0.5
        weights = np.exp((raw - np.max(raw)) / temperature)
        weights = weights / weights.sum()
        weights = np.maximum(weights, 0.05)
        weights = weights / weights.sum()

        result = {selected[i].strategy_id: float(weights[i]) for i in range(len(selected))}
        if self.current_regime == "REGIME_UNCERTAIN":
            result = {key: value * 0.70 for key, value in result.items()}
            result["CASH"] = 0.30

        self.current_weights = result
        return result

    def _filter_candidates(
        self, strategies: list[dict], decay_results: pd.DataFrame | None
    ) -> list[dict]:
        filtered = []
        for strategy in strategies:
            recent_returns = pd.Series(strategy.get("recent_returns", []), dtype=float)
            if len(recent_returns) < 20:
                continue
            if self._sharpe(recent_returns) < self.min_sharpe:
                continue
            if self._decay_status(strategy["id"], decay_results) == "CRITICAL":
                continue
            filtered.append(strategy)
        return filtered

    def _decay_status(self, strategy_id: str, decay_results: pd.DataFrame | None) -> str:
        if decay_results is None or decay_results.empty:
            return "HEALTHY"
        match = decay_results[decay_results["strategy_id"] == strategy_id]
        return str(match.iloc[0]["status"]) if not match.empty else "HEALTHY"

    def _apply_correlation_penalty(
        self, fitness_scores: list[StrategyFitness]
    ) -> list[StrategyFitness]:
        if len(fitness_scores) <= 1 or self.returns_matrix.empty:
            return fitness_scores

        for item in fitness_scores:
            max_corr = 0.0
            if item.strategy_id not in self.returns_matrix.columns:
                item.correlation_penalty = 0.0
                continue
            for other in fitness_scores:
                if other.strategy_id == item.strategy_id:
                    continue
                if other.strategy_id not in self.returns_matrix.columns:
                    continue
                corr = self.returns_matrix[item.strategy_id].corr(
                    self.returns_matrix[other.strategy_id]
                )
                if not pd.isna(corr):
                    max_corr = max(max_corr, abs(float(corr)))
            item.correlation_penalty = (
                (max_corr - self.corr_limit) / (1.0 - self.corr_limit)
                if max_corr > self.corr_limit
                else 0.0
            )
        return fitness_scores

    def _raw_fitness(self, item: StrategyFitness) -> float:
        return (
            item.recent_sharpe
            * item.regime_match
            * item.capacity_remaining
            * (1.0 - item.correlation_penalty)
        )

    def _sharpe(self, returns: pd.Series, risk_free: float = 0.0) -> float:
        returns = pd.Series(returns, dtype=float).dropna()
        if len(returns) < 2 or returns.std() == 0:
            return 0.0
        return float((returns.mean() - risk_free) / returns.std() * np.sqrt(252))

    def rebalance_needed(
        self, current_weights: dict[str, float], threshold: float = 0.05
    ) -> bool:
        for strategy_id, target_weight in self.current_weights.items():
            if abs(current_weights.get(strategy_id, 0.0) - target_weight) > threshold:
                return True
        return False
