"""Alpha decay monitoring for live strategy health."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class DecayAlert:
    strategy_id: str
    strategy_name: str
    status: str
    baseline_sharpe: float
    current_sharpe: float
    decay_ratio: float
    rolling_return: float
    rolling_volatility: float
    max_drawdown_current: float
    recommendation: str
    timestamp: datetime

    def to_dict(self) -> dict:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


class AlphaDecayMonitor:
    """Track strategy Sharpe degradation and trigger retirement warnings."""

    def __init__(
        self,
        warning_threshold: float = 0.70,
        critical_threshold: float = 0.50,
        rolling_window: int = 60,
        min_observations: int = 30,
    ):
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.rolling_window = rolling_window
        self.min_observations = min_observations
        self.baselines: dict[str, dict] = {}
        self.history: dict[str, pd.DataFrame] = {}
        self.last_status: dict[str, str] = {}

    def initialize_strategy(
        self,
        strategy_id: str,
        strategy_name: str,
        historical_returns: pd.Series,
        in_sample_sharpe: float | None = None,
    ) -> None:
        returns = pd.Series(historical_returns, dtype=float).dropna()
        baseline_sharpe = (
            float(in_sample_sharpe) if in_sample_sharpe is not None else self._sharpe(returns)
        )
        self.baselines[strategy_id] = {
            "name": strategy_name,
            "baseline_sharpe": baseline_sharpe,
            "baseline_vol": float(returns.std()) if len(returns) else 0.0,
            "baseline_mean": float(returns.mean()) if len(returns) else 0.0,
            "baseline_win_rate": float((returns > 0).mean()) if len(returns) else 0.0,
            "live_since": datetime.utcnow(),
        }
        self.history[strategy_id] = pd.DataFrame(
            columns=["return", "prediction", "actual", "timestamp"]
        )
        self.last_status[strategy_id] = "HEALTHY"

    def update(
        self,
        strategy_id: str,
        daily_return: float,
        prediction: float | None = None,
        actual: float | None = None,
    ) -> DecayAlert | None:
        if strategy_id not in self.history:
            logger.warning("Strategy %s not initialized in decay monitor", strategy_id)
            return None

        row = pd.DataFrame(
            [
                {
                    "return": float(daily_return),
                    "prediction": prediction,
                    "actual": actual,
                    "timestamp": datetime.utcnow(),
                }
            ]
        )
        self.history[strategy_id] = pd.concat(
            [self.history[strategy_id], row], ignore_index=True
        )
        if len(self.history[strategy_id]) < self.min_observations:
            return None

        alert = self._evaluate(strategy_id)
        if alert and alert.status != self.last_status.get(strategy_id):
            self.last_status[strategy_id] = alert.status
            return alert
        if alert and alert.status == "CRITICAL":
            return alert
        return None

    def status_for(self, strategy_id: str) -> dict | None:
        if strategy_id not in self.baselines:
            return None
        alert = self._evaluate(strategy_id, include_healthy=True)
        return alert.to_dict() if alert else None

    def _evaluate(
        self, strategy_id: str, include_healthy: bool = False
    ) -> DecayAlert | None:
        baseline = self.baselines[strategy_id]
        hist = self.history[strategy_id]
        if len(hist) < self.min_observations:
            return None

        recent = pd.Series(hist["return"].astype(float)).iloc[-self.rolling_window :]
        current_sharpe = self._sharpe(recent)
        current_vol = float(recent.std()) if len(recent) else 0.0
        current_mean = float(recent.mean()) if len(recent) else 0.0
        current_win_rate = float((recent > 0).mean()) if len(recent) else 0.0

        baseline_sharpe = baseline["baseline_sharpe"]
        baseline_vol = baseline["baseline_vol"]
        baseline_win_rate = baseline["baseline_win_rate"]
        sharpe_decay = current_sharpe / (baseline_sharpe + 1e-6)
        vol_inflation = current_vol / (baseline_vol + 1e-6)
        win_rate_decay = current_win_rate / (baseline_win_rate + 1e-6)

        curve = (1.0 + recent).cumprod()
        drawdown = (curve - curve.cummax()) / curve.cummax()
        max_dd = float(drawdown.min()) if len(drawdown) else 0.0

        if sharpe_decay < self.critical_threshold or vol_inflation > 2.0:
            status = "CRITICAL"
            recommendation = "IMMEDIATE_SHUTDOWN"
        elif sharpe_decay < self.warning_threshold or win_rate_decay < 0.60:
            status = "WARNING"
            recommendation = "REDUCE_SIZE_50_PERCENT"
        else:
            status = "HEALTHY"
            recommendation = "MAINTAIN"

        if status == "HEALTHY" and not include_healthy:
            return None

        return DecayAlert(
            strategy_id=strategy_id,
            strategy_name=baseline["name"],
            status=status,
            baseline_sharpe=float(baseline_sharpe),
            current_sharpe=float(current_sharpe),
            decay_ratio=float(sharpe_decay),
            rolling_return=current_mean,
            rolling_volatility=current_vol,
            max_drawdown_current=max_dd,
            recommendation=recommendation,
            timestamp=datetime.utcnow(),
        )

    def _sharpe(self, returns: pd.Series, risk_free: float = 0.0) -> float:
        returns = pd.Series(returns, dtype=float).dropna()
        if len(returns) < 2 or returns.std() == 0:
            return 0.0
        return float((returns.mean() - risk_free) / returns.std() * np.sqrt(252))

    def get_health_report(self) -> pd.DataFrame:
        reports = []
        for strategy_id in self.baselines:
            alert = self._evaluate(strategy_id, include_healthy=True)
            if alert:
                reports.append(
                    {
                        "strategy_id": alert.strategy_id,
                        "name": alert.strategy_name,
                        "status": alert.status,
                        "sharpe_decay": alert.decay_ratio,
                        "current_sharpe": alert.current_sharpe,
                        "recommendation": alert.recommendation,
                    }
                )
        return pd.DataFrame(reports)
