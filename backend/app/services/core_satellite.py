"""Core-Satellite-Explosion portfolio allocator."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import norm

from app.time_utils import utcnow


@dataclass
class PortfolioLayer:
    name: str
    target_pct: float
    max_drawdown: float
    min_sharpe: float
    current_value: float = 0.0
    current_positions: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CoreSatelliteAllocator:
    """Three-layer allocator with regime-adjusted targets and risk limits."""

    def __init__(
        self,
        total_capital: float = 180000.0,
        core_pct: float = 0.50,
        satellite_pct: float = 0.30,
        explosion_pct: float = 0.20,
        rebalance_threshold: float = 0.05,
        weekly_target: float = 0.02,
    ):
        total_pct = core_pct + satellite_pct + explosion_pct
        if total_pct <= 0:
            raise ValueError("Layer percentages must sum to a positive value")
        self.total = float(total_capital)
        self.weekly_target = weekly_target
        self.rebalance_threshold = rebalance_threshold
        self.core = PortfolioLayer("CORE", core_pct / total_pct, 0.10, 0.5)
        self.satellite = PortfolioLayer("SATELLITE", satellite_pct / total_pct, 0.20, 1.0)
        self.explosion = PortfolioLayer("EXPLOSION", explosion_pct / total_pct, 0.35, 1.2)
        self.layers = [self.core, self.satellite, self.explosion]
        self.cash = self.total
        self.allocation_history: list[dict[str, Any]] = []

    def allocate(
        self,
        core_signals: pd.DataFrame | None = None,
        satellite_signals: pd.DataFrame | None = None,
        explosion_signals: pd.DataFrame | None = None,
        regime: str = "NORMAL",
    ) -> dict[str, Any]:
        targets = self._regime_targets(regime)
        allocations = {
            "CORE": {
                "target_value": self.total * targets["CORE"],
                "current_value": sum(self.core.current_positions.values()),
                "positions": self._allocate_core(core_signals, self.total * targets["CORE"]),
            },
            "SATELLITE": {
                "target_value": self.total * targets["SATELLITE"],
                "current_value": sum(self.satellite.current_positions.values()),
                "positions": self._allocate_satellite(
                    satellite_signals, self.total * targets["SATELLITE"]
                ),
            },
            "EXPLOSION": {
                "target_value": self.total * targets["EXPLOSION"],
                "current_value": sum(self.explosion.current_positions.values()),
                "positions": self._allocate_explosion(
                    explosion_signals, self.total * targets["EXPLOSION"]
                ),
            },
        }
        used = sum(sum(layer["positions"].values()) for layer in allocations.values())
        cash = max(0.0, self.total - used)
        allocations["CASH"] = cash
        total_risk = self._calculate_total_risk(allocations)

        record = {
            "timestamp": utcnow().isoformat(),
            "regime": regime,
            "targets": targets,
            "allocations": allocations,
            "cash_pct": cash / self.total if self.total else 0.0,
            "total_risk_1std": total_risk,
            "weekly_target_prob": self._estimate_target_probability(allocations),
            "risk_warning": self._risk_warning(total_risk),
        }
        self.allocation_history.append(record)
        return record

    def _regime_targets(self, regime: str) -> dict[str, float]:
        adjustments = {
            "TRENDING_UP": {"CORE": 0.0, "SATELLITE": 0.0, "EXPLOSION": 0.05},
            "TRENDING_DOWN": {"CORE": 0.10, "SATELLITE": -0.05, "EXPLOSION": -0.10},
            "HIGH_VOL": {"CORE": 0.15, "SATELLITE": -0.05, "EXPLOSION": -0.10},
            "LOW_VOL": {"CORE": -0.05, "SATELLITE": 0.05, "EXPLOSION": 0.0},
            "MEAN_REVERTING": {"CORE": 0.0, "SATELLITE": 0.05, "EXPLOSION": -0.05},
            "REGIME_UNCERTAIN": {"CORE": 0.20, "SATELLITE": -0.10, "EXPLOSION": -0.10},
        }
        adj = adjustments.get(regime, {"CORE": 0.0, "SATELLITE": 0.0, "EXPLOSION": 0.0})
        core = float(np.clip(self.core.target_pct + adj["CORE"], 0.30, 0.70))
        satellite = float(np.clip(self.satellite.target_pct + adj["SATELLITE"], 0.15, 0.40))
        explosion = float(np.clip(self.explosion.target_pct + adj["EXPLOSION"], 0.05, 0.25))
        total = core + satellite + explosion
        return {"CORE": core / total, "SATELLITE": satellite / total, "EXPLOSION": explosion / total}

    def _allocate_core(self, signals: pd.DataFrame | None, capital: float) -> dict[str, float]:
        if signals is None or signals.empty:
            return {"SPY": capital * 0.60, "QQQ": capital * 0.40}
        long_signals = signals[signals["signal"] == "LONG"] if "signal" in signals else signals
        if long_signals.empty:
            return {"CASH_CORE": capital}
        weights = self._score_weights(long_signals, "confidence")
        return {
            str(row.get("ticker", row.get("symbol", f"CORE_{idx}"))): capital * weights[pos]
            for pos, (idx, row) in enumerate(long_signals.iterrows())
        }

    def _allocate_satellite(
        self, signals: pd.DataFrame | None, capital: float
    ) -> dict[str, float]:
        if signals is None or signals.empty:
            return {}
        trades = signals[signals["take_trade"]] if "take_trade" in signals else signals
        positions = {}
        for _, row in trades.iterrows():
            ticker = str(row.get("ticker", row.get("symbol")))
            if not ticker or ticker == "None":
                continue
            kelly = float(row.get("kelly_fraction", 0.02))
            confidence = float(row.get("confidence", 0.5))
            positions[ticker] = capital * min(max(kelly, 0.0), 0.10) * 0.5 * confidence
        return self._scale_to_capital(positions, capital)

    def _allocate_explosion(
        self, signals: pd.DataFrame | None, capital: float
    ) -> dict[str, float]:
        if signals is None or signals.empty:
            return {}
        top = signals.sort_values("combined_score", ascending=False).head(15)
        if top.empty:
            return {}
        max_position = self.total * 0.02
        weights = self._score_weights(top, "combined_score")
        positions = {}
        for pos, (_, row) in enumerate(top.iterrows()):
            ticker = str(row.get("ticker", row.get("symbol", f"EXP_{pos}")))
            positions[ticker] = min(capital * weights[pos], max_position)
        return positions

    def _score_weights(self, df: pd.DataFrame, score_col: str) -> np.ndarray:
        if score_col in df:
            scores = np.maximum(df[score_col].astype(float).to_numpy(), 0.0)
            if scores.sum() > 0:
                return scores / scores.sum()
        return np.full(len(df), 1.0 / len(df))

    def _scale_to_capital(self, positions: dict[str, float], capital: float) -> dict[str, float]:
        total = sum(positions.values())
        if total > capital and total > 0:
            scale = capital / total
            return {ticker: value * scale for ticker, value in positions.items()}
        return positions

    def _calculate_total_risk(self, allocations: dict[str, Any]) -> float:
        core_val = sum(allocations["CORE"]["positions"].values())
        sat_val = sum(allocations["SATELLITE"]["positions"].values())
        exp_val = sum(allocations["EXPLOSION"]["positions"].values())
        core_var = (core_val * 0.15) ** 2
        sat_var = (sat_val * 0.25) ** 2
        exp_var = (exp_val * 0.40) ** 2
        total_var = (
            core_var
            + sat_var
            + exp_var
            + 0.3 * np.sqrt(core_var * sat_var)
            + 0.2 * np.sqrt(core_var * exp_var)
            + 0.4 * np.sqrt(sat_var * exp_var)
        )
        return float(np.sqrt(total_var) / self.total) if self.total > 0 else 0.0

    def _estimate_target_probability(self, allocations: dict[str, Any]) -> float:
        core_w = sum(allocations["CORE"]["positions"].values()) / self.total
        sat_w = sum(allocations["SATELLITE"]["positions"].values()) / self.total
        exp_w = sum(allocations["EXPLOSION"]["positions"].values()) / self.total
        weekly_er = (core_w * 0.0008 + sat_w * 0.0025 + exp_w * 0.0040) * 5
        weekly_vol = self._calculate_total_risk(allocations) / np.sqrt(252) * np.sqrt(5)
        if weekly_vol <= 0:
            return 1.0 if weekly_er >= self.weekly_target else 0.0
        return float(1.0 - norm.cdf((self.weekly_target - weekly_er) / weekly_vol))

    def _risk_warning(self, total_risk: float) -> str:
        if total_risk > 0.35:
            return "CRITICAL"
        if total_risk > 0.20:
            return "WARNING"
        return "OK"

    def rebalance_check(self) -> bool:
        current = {
            "CORE": sum(self.core.current_positions.values()) / self.total,
            "SATELLITE": sum(self.satellite.current_positions.values()) / self.total,
            "EXPLOSION": sum(self.explosion.current_positions.values()) / self.total,
        }
        targets = {
            "CORE": self.core.target_pct,
            "SATELLITE": self.satellite.target_pct,
            "EXPLOSION": self.explosion.target_pct,
        }
        return any(
            abs(current[layer] - targets[layer]) > self.rebalance_threshold
            for layer in current
        )

    def get_weekly_report(self) -> dict[str, Any]:
        if not self.allocation_history:
            return {"error": "No allocation history"}
        latest = self.allocation_history[-1]
        return {
            "week_ending": latest["timestamp"],
            "regime": latest["regime"],
            "cash_pct": f"{latest['cash_pct']:.1%}",
            "target_hit_probability": f"{latest['weekly_target_prob']:.1%}",
            "layer_allocations": latest["targets"],
            "active_positions": {
                "CORE": len(latest["allocations"]["CORE"]["positions"]),
                "SATELLITE": len(latest["allocations"]["SATELLITE"]["positions"]),
                "EXPLOSION": len(latest["allocations"]["EXPLOSION"]["positions"]),
            },
        }
