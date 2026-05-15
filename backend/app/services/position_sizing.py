"""
Kelly Criterion position sizing.

Fractional Kelly (fraction=0.25 cap) prevents ruin from edge overestimation.
Kelly is computed per strategy from walk-forward trade data.
Negative Kelly → 0.0 (no edge, no position).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

# Hard cap on fractional Kelly to prevent overleverage
MAX_KELLY_FRACTION = 0.25


@dataclass
class KellyEstimate:
    win_rate: float
    avg_win: float
    avg_loss: float
    full_kelly: float
    fractional_kelly: float
    n_trades: int
    is_positive: bool


def compute_kelly_fraction(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    fraction: float = MAX_KELLY_FRACTION,
) -> KellyEstimate:
    """
    Full Kelly: f* = (p * b - q) / b  where b = avg_win / avg_loss.
    Returns fractional Kelly = f* * fraction, capped at fraction.
    Returns estimate with fractional_kelly=0.0 if edge is negative.

    Args:
        win_rate: Fraction of trades that are profitable [0, 1].
        avg_win:  Average winning trade return (positive float).
        avg_loss: Average losing trade magnitude (positive float, sign-agnostic).
        fraction: Kelly multiplier cap (default 0.25 = quarter Kelly).
    """
    if avg_loss <= 0 or avg_win <= 0 or not (0.0 < win_rate < 1.0):
        return KellyEstimate(
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            full_kelly=0.0,
            fractional_kelly=0.0,
            n_trades=0,
            is_positive=False,
        )

    b = avg_win / avg_loss  # payoff ratio
    p = win_rate
    q = 1.0 - p

    full_kelly = (p * b - q) / b

    if full_kelly <= 0:
        logger.debug(
            "Negative Kelly %.4f — no edge. win_rate=%.2f payoff=%.2f",
            full_kelly, p, b,
        )
        return KellyEstimate(
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            full_kelly=full_kelly,
            fractional_kelly=0.0,
            n_trades=0,
            is_positive=False,
        )

    frac = min(full_kelly * fraction, fraction)
    logger.debug("Kelly: full=%.4f fractional=%.4f (win_rate=%.2f payoff=%.2f)", full_kelly, frac, p, b)
    return KellyEstimate(
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        full_kelly=full_kelly,
        fractional_kelly=frac,
        n_trades=0,
        is_positive=True,
    )


def kelly_from_trade_returns(
    trade_returns: list[float],
    fraction: float = MAX_KELLY_FRACTION,
) -> KellyEstimate:
    """
    Estimate Kelly from a list of realized trade returns.
    Requires at least 10 trades for statistical validity.
    """
    n = len(trade_returns)
    if n < 10:
        logger.debug("Kelly: insufficient trades (%d < 10), returning 0", n)
        return KellyEstimate(
            win_rate=0.0, avg_win=0.0, avg_loss=0.0,
            full_kelly=0.0, fractional_kelly=0.0,
            n_trades=n, is_positive=False,
        )

    wins = [r for r in trade_returns if r > 0]
    losses = [r for r in trade_returns if r <= 0]

    if not wins or not losses:
        return KellyEstimate(
            win_rate=float(len(wins) / n), avg_win=0.0, avg_loss=0.0,
            full_kelly=0.0, fractional_kelly=0.0,
            n_trades=n, is_positive=False,
        )

    win_rate = len(wins) / n
    avg_win = float(np.mean(wins))
    avg_loss = float(abs(np.mean(losses)))

    est = compute_kelly_fraction(win_rate, avg_win, avg_loss, fraction)
    est.n_trades = n
    return est


def kelly_from_folds(
    folds: list,
    fraction: float = MAX_KELLY_FRACTION,
) -> KellyEstimate:
    """
    Compute Kelly from walk-forward WalkForwardFold objects or metric dicts.
    Aggregates all trade returns across folds for a robust estimate.

    Accepts either WalkForwardFold objects (with .trade_returns attribute)
    or plain dicts (with '_trade_returns' or 'trade_returns' key).
    """
    all_returns: list[float] = []
    for fold in folds:
        if hasattr(fold, "trade_returns"):
            all_returns.extend(fold.trade_returns or [])
        elif isinstance(fold, dict):
            all_returns.extend(fold.get("_trade_returns") or fold.get("trade_returns") or [])

    if all_returns:
        return kelly_from_trade_returns(all_returns, fraction)

    logger.debug("Kelly: no individual trade returns in folds, falling back to aggregate metrics")
    if not folds:
        return KellyEstimate(
            win_rate=0.0, avg_win=0.0, avg_loss=0.0,
            full_kelly=0.0, fractional_kelly=0.0,
            n_trades=0, is_positive=False,
        )

    # Fallback: use aggregate fold metrics (less accurate)
    def _metric(fold, key: str, default=0.0) -> float:
        if hasattr(fold, "metrics"):
            return float((fold.metrics or {}).get(key, default))
        return float((fold if isinstance(fold, dict) else {}).get(key, default))

    avg_win_rate = float(np.mean([_metric(f, "win_rate") for f in folds]))
    avg_return = float(np.mean([_metric(f, "avg_return") for f in folds]))
    if avg_return <= 0:
        return KellyEstimate(
            win_rate=avg_win_rate, avg_win=0.0, avg_loss=0.0,
            full_kelly=0.0, fractional_kelly=0.0,
            n_trades=0, is_positive=False,
        )

    # Conservative rough approximation when individual returns missing
    avg_win = avg_return * 1.8
    avg_loss = avg_return * 0.8
    est = compute_kelly_fraction(avg_win_rate, avg_win, avg_loss, fraction)
    return est
