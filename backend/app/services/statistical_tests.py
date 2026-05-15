"""
Statistical validation for trading strategies.

  Probabilistic Sharpe Ratio (López de Prado 2018)
  Deflated Sharpe Ratio (adjusted for multiple trials)
  Shuffle / permutation test
  Concentration check (single-stock, single-year)
  SPY benchmark comparison
"""
import logging
import math
from datetime import date

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


def probabilistic_sharpe_ratio(returns: list[float], sr_benchmark: float = 0.0) -> float:
    """
    PSR: probability that true Sharpe > sr_benchmark given observed returns.
    Returns a probability in [0, 1].
    """
    r = np.array(returns, dtype=float)
    T = len(r)
    if T < 4:
        return 0.0
    sr = r.mean() / (r.std(ddof=1) + 1e-10) * math.sqrt(52)
    skew = float(pd.Series(r).skew())
    kurt = float(pd.Series(r).kurtosis())  # excess kurtosis

    denom = math.sqrt(1 - skew * sr / math.sqrt(52) + (kurt + 1) / 4 * (sr / math.sqrt(52)) ** 2)
    if denom <= 0:
        return 0.0
    z = (sr - sr_benchmark) * math.sqrt(T - 1) / denom
    return float(stats.norm.cdf(z))


def deflated_sharpe_ratio(
    returns: list[float],
    n_trials: int = 1,
) -> float:
    """
    DSR: SR adjusted for multiple trials using Bonferroni-style SR* estimate.
    Returns the DSR value (annualised).
    """
    r = np.array(returns, dtype=float)
    T = len(r)
    if T < 4:
        return 0.0
    sr = r.mean() / (r.std(ddof=1) + 1e-10) * math.sqrt(52)

    # Expected max SR under null for n_trials independent tests
    # Approximation: SR* = sqrt(2 * log(n_trials)) / sqrt(T)  (Bonferroni-style)
    if n_trials > 1:
        sr_star = math.sqrt(2 * math.log(n_trials)) * math.sqrt(52) / math.sqrt(T)
    else:
        sr_star = 0.0

    skew = float(pd.Series(r).skew())
    kurt = float(pd.Series(r).kurtosis())

    adj = 1 - skew * (sr / math.sqrt(52)) / 6 + (kurt + 1) / 4 * (sr / math.sqrt(52)) ** 2
    if adj <= 0:
        return sr
    dsr = (sr - sr_star) / math.sqrt(adj)
    return float(dsr)


def permutation_test(returns: list[float], n_permutations: int = 500) -> float:
    """
    Shuffle test: fraction of permuted Sharpe ratios >= observed Sharpe.
    Low p-value = strategy is likely not random.
    Returns p-value in [0, 1].
    """
    r = np.array(returns, dtype=float)
    if len(r) < 5:
        return 1.0

    def sharpe(x: np.ndarray) -> float:
        std = x.std(ddof=1)
        return x.mean() / std * math.sqrt(52) if std > 0 else 0.0

    observed = sharpe(r)
    rng = np.random.default_rng(42)
    null_distribution = [sharpe(rng.permutation(r)) for _ in range(n_permutations)]
    p_value = float(np.mean(np.array(null_distribution) >= observed))
    return p_value


def concentration_check(trades: list[dict]) -> dict:
    """
    Check for unhealthy concentration:
      - single_stock_pct: max fraction of trades from one ticker
      - single_year_pct: max fraction of trades from one calendar year
      Returns flags and details.
    """
    if not trades:
        return {"ok": True, "single_stock_pct": 0.0, "single_year_pct": 0.0}

    tickers = [t.get("ticker", "") for t in trades]
    years = [t.get("entry_date").year if hasattr(t.get("entry_date"), "year") else 0 for t in trades]

    n = len(trades)
    ticker_counts = pd.Series(tickers).value_counts()
    year_counts = pd.Series(years).value_counts()

    max_ticker_pct = float(ticker_counts.iloc[0] / n) if n > 0 else 0.0
    max_year_pct = float(year_counts.iloc[0] / n) if n > 0 else 0.0

    ok = max_ticker_pct <= 0.5 and max_year_pct <= 0.6

    return {
        "ok": ok,
        "single_stock_pct": round(max_ticker_pct, 4),
        "single_year_pct": round(max_year_pct, 4),
        "top_ticker": ticker_counts.index[0] if len(ticker_counts) > 0 else "",
        "top_year": int(year_counts.index[0]) if len(year_counts) > 0 else 0,
    }


def get_spy_weekly_sharpe(session, lookback_weeks: int = 260) -> float:
    """
    Compute SPY's annualised Sharpe from stored macro data (SP500 weekly returns).
    Falls back to a reasonable estimate if data is unavailable.
    """
    try:
        from sqlalchemy import select
        from app.models.macro import MacroIndicator
        rows = session.execute(
            select(MacroIndicator)
            .where(MacroIndicator.indicator_code == "SP500")
            .order_by(MacroIndicator.date)
        ).scalars().all()
        if len(rows) < 10:
            return 0.4  # historical S&P500 Sharpe approximation

        df = pd.DataFrame([{"date": r.date, "value": r.value} for r in rows])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        weekly = df["value"].resample("W-FRI").last().pct_change().dropna()
        recent = weekly.iloc[-lookback_weeks:]
        if len(recent) < 10:
            return 0.4
        return float(recent.mean() / recent.std() * math.sqrt(52))
    except Exception as e:
        logger.warning(f"SPY Sharpe computation failed: {e}")
        return 0.4
