"""
Behavioral Finance Signal Layer.

Implements four bias-based signals derived from academic literature:

  2B Anchoring:    52w high/low anchoring + breakout signal (George & Hwang 2004)
  2C Herding:      Cross-sectional return correlation → herd detection
  2A Disposition:  Unrealized gain/loss proxy → tax-loss selling pressure
  2D Overreaction: Short-term reversal after extreme moves (De Bondt & Thaler 1985)

All signals are computed from data available BEFORE week_ending (no lookahead).
Returns NaN rather than raising if data is insufficient.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Feature names exported to feature_engineering.py
BEHAVIORAL_FEATURES = [
    # Anchoring
    "anchor_proximity_high",    # (price - 52w_high) / 52w_high  (≤0)
    "anchor_proximity_low",     # (price - 52w_low) / 52w_low    (≥0)
    "anchor_breakout_signal",   # 1 if price > 52w_high * 1.02, else 0
    # Disposition
    "disposition_gain_proxy",   # (price - 52w_low) / (52w_high - 52w_low)  ∈[0,1]
    "disposition_selling_risk", # 1 if near 52w_high (potential profit-taking), 0 otherwise
    # Herding
    "herding_score",            # cross-sectional correlation proxy (passed externally)
    # Overreaction
    "overreaction_reversal",    # negative of 4w return when |4w_return| > 2σ
    "extreme_move_flag",        # 1 if |4w_return| > 2σ, else 0
]


# ---------------------------------------------------------------------------
# Per-stock signals (computed inside FeatureEngineeringService per week)
# ---------------------------------------------------------------------------

def compute_anchoring(close: pd.Series) -> dict[str, float]:
    """
    Compute 52-week anchoring signals.

    Args:
        close: Daily close price series (sorted ascending, no lookahead).

    Returns:
        Dict with anchor_proximity_high, anchor_proximity_low, anchor_breakout_signal.
    """
    if len(close) < 20:
        return {k: np.nan for k in ["anchor_proximity_high", "anchor_proximity_low", "anchor_breakout_signal"]}

    window = close.iloc[-252:] if len(close) >= 252 else close
    high_52 = float(window.max())
    low_52 = float(window.min())
    cur = float(close.iloc[-1])

    if high_52 <= 0:
        return {k: np.nan for k in ["anchor_proximity_high", "anchor_proximity_low", "anchor_breakout_signal"]}

    prox_high = (cur - high_52) / high_52  # typically ≤ 0
    prox_low = (cur - low_52) / low_52 if low_52 > 0 else np.nan  # typically ≥ 0

    # Breakout: price exceeded 52w high by ≥2% → psy. resistance broken → FOMO
    breakout = 1.0 if cur > high_52 * 1.02 else 0.0

    return {
        "anchor_proximity_high": round(prox_high, 6),
        "anchor_proximity_low": round(prox_low, 6) if pd.notna(prox_low) else np.nan,
        "anchor_breakout_signal": breakout,
    }


def compute_disposition(close: pd.Series) -> dict[str, float]:
    """
    Disposition effect proxy.

    Investors hold losers (avoid realizing losses) and sell winners too early.
    A stock near its 52w high has large unrealized gains → selling pressure.
    A stock near its 52w low has large unrealized losses → holders won't sell.

    Args:
        close: Daily close price series.

    Returns:
        disposition_gain_proxy: position in [0,1] within 52w range.
        disposition_selling_risk: 1 if in top 10% of 52w range.
    """
    if len(close) < 20:
        return {"disposition_gain_proxy": np.nan, "disposition_selling_risk": np.nan}

    window = close.iloc[-252:] if len(close) >= 252 else close
    high_52 = float(window.max())
    low_52 = float(window.min())
    cur = float(close.iloc[-1])
    rng = high_52 - low_52

    if rng <= 0:
        return {"disposition_gain_proxy": 0.5, "disposition_selling_risk": 0.0}

    gain_proxy = (cur - low_52) / rng  # 0=at 52w low, 1=at 52w high
    selling_risk = 1.0 if gain_proxy >= 0.90 else 0.0

    return {
        "disposition_gain_proxy": round(gain_proxy, 6),
        "disposition_selling_risk": selling_risk,
    }


def compute_overreaction(weekly_returns: pd.Series) -> dict[str, float]:
    """
    Short-term overreaction reversal signal (De Bondt & Thaler 1985).

    Stocks with extreme 4-week moves tend to partially reverse.
    Signal: if |4w_return| > 2σ, flag extreme move and expect reversal.

    Args:
        weekly_returns: Past weekly returns (no lookahead, sorted ascending).

    Returns:
        overreaction_reversal: -4w_return if extreme move, else 0.
        extreme_move_flag: 1 if extreme, else 0.
    """
    if len(weekly_returns) < 20:
        return {"overreaction_reversal": np.nan, "extreme_move_flag": np.nan}

    # Rolling σ of 4-week returns over the last 52 weeks
    roll4 = weekly_returns.rolling(4).sum()
    long_std = float(roll4.iloc[-52:].std()) if len(roll4) >= 52 else float(roll4.std())

    current_4w = float((1 + weekly_returns.iloc[-4:]).prod() - 1) if len(weekly_returns) >= 4 else np.nan

    if pd.isna(current_4w) or long_std <= 0:
        return {"overreaction_reversal": 0.0, "extreme_move_flag": 0.0}

    is_extreme = abs(current_4w) > 2.0 * long_std
    return {
        "overreaction_reversal": round(-current_4w, 6) if is_extreme else 0.0,
        "extreme_move_flag": 1.0 if is_extreme else 0.0,
    }


# ---------------------------------------------------------------------------
# Cross-sectional herding (computed across stocks for one week)
# ---------------------------------------------------------------------------

def compute_herding_score(all_weekly_returns: dict[str, float]) -> float:
    """
    Cross-sectional herding score for one week.

    Christie & Huang (1995): In herding periods, stocks cluster around market return.
    Low cross-sectional dispersion (CSSD) → high herding.

    Args:
        all_weekly_returns: {ticker: weekly_return} for all stocks this week.

    Returns:
        herding_score ∈ [0, 1]: 0=no herding, 1=extreme herding.
    """
    vals = [v for v in all_weekly_returns.values() if pd.notna(v)]
    if len(vals) < 5:
        return np.nan

    arr = np.array(vals)
    mkt_return = float(np.mean(arr))
    cssd = float(np.sqrt(np.mean((arr - mkt_return) ** 2)))  # cross-sectional std

    # Normalize by historical percentile — here we use a simple sigmoid on CSSD
    # Lower CSSD → higher herding
    # Typical CSSD range: 0.01 - 0.06 for weekly returns
    # Invert and clip to [0,1]
    herding = float(np.clip(1.0 - cssd / 0.05, 0.0, 1.0))
    return round(herding, 4)


def compute_all_behavioral(
    close: pd.Series,
    weekly_returns: pd.Series,
    herding_score: float | None = None,
) -> dict[str, float]:
    """
    Convenience function: compute all per-stock behavioral signals.

    Args:
        close:          Daily close prices (sorted ascending, no lookahead).
        weekly_returns: Weekly returns (sorted ascending, no lookahead).
        herding_score:  Pre-computed cross-sectional herding score for this week.

    Returns:
        Dict with all BEHAVIORAL_FEATURES values.
    """
    result: dict[str, float] = {}
    result.update(compute_anchoring(close))
    result.update(compute_disposition(close))
    result.update(compute_overreaction(weekly_returns))
    result["herding_score"] = herding_score if herding_score is not None else np.nan
    return result
