"""
Momentum + Low Volatility + BAB + QMJ + Cross-sectional Momentum Ranking

Factors:
  1A. Momentum × Low-Vol combined score  (Asness et al. 2013)
  1B. Betting Against Beta               (Frazzini & Pedersen 2014)
  1C. Quality Minus Junk                 (Asness, Frazzini & Pedersen 2019)
  1D. Cross-sectional momentum ranking   (sector + universe percentile)

Per-stock features are computed inline in feature_engineering.py.
This module provides:
  - Stateless helper functions for per-stock computation
  - MomentumLowVolBatchService for cross-sectional normalization (run after all stocks)
"""
import logging
import math

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.feature import FeatureWeekly
from app.models.macro import MacroIndicator

logger = logging.getLogger(__name__)

MOMENTUM_LOWVOL_FEATURES = [
    "momentum_12_1", "momentum_6_1", "combined_momentum",
    "realized_vol_12w", "vol_score",
    "beta_52w",
    "qmj_score",
]

MOMENTUM_LOWVOL_BATCH_FEATURES = [
    "mom_lowvol_score",
    "vol_score_rank",
    "bab_score",
    "beta_percentile_in_sector",
    "momentum_rank_in_sector",
    "momentum_rank_in_universe",
]

FEATURE_SET_VERSION = "v4"


# ---------------------------------------------------------------------------
# Per-stock helpers (no DB access)
# ---------------------------------------------------------------------------

def compute_momentum_features(weekly_returns: pd.Series) -> dict:
    """
    Compute per-week momentum and volatility features from weekly return history.

    weekly_returns: series of weekly returns available up to (not including) the
                    prediction week. Index should be sorted ascending.
    """
    out: dict[str, float] = {}
    wr = weekly_returns.dropna()

    # Need at least 13 weeks for full momentum_12_1
    if len(wr) < 4:
        return {k: np.nan for k in MOMENTUM_LOWVOL_FEATURES}

    r1w = float(wr.iloc[-1]) if len(wr) >= 1 else np.nan
    r4w = float((1 + wr.iloc[-4:]).prod() - 1) if len(wr) >= 4 else np.nan
    r12w = float((1 + wr.iloc[-12:]).prod() - 1) if len(wr) >= 12 else np.nan

    # momentum_12_1: 12-week return skipping last week (no reversal contamination)
    if len(wr) >= 13:
        momentum_12_1 = float((1 + wr.iloc[-13:-1]).prod() - 1)
    elif len(wr) >= 2:
        momentum_12_1 = r12w - r1w if pd.notna(r12w) else np.nan
    else:
        momentum_12_1 = np.nan

    # momentum_6_1: 4-week skip-1 proxy
    momentum_6_1 = (r4w - r1w) if pd.notna(r4w) and pd.notna(r1w) else np.nan

    combined_momentum = (
        0.7 * momentum_12_1 + 0.3 * momentum_6_1
        if pd.notna(momentum_12_1) and pd.notna(momentum_6_1)
        else np.nan
    )

    # Realized vol over last 12 weeks
    realized_vol_12w = float(wr.iloc[-12:].std()) if len(wr) >= 12 else float(wr.std())
    vol_score = 1.0 / (realized_vol_12w + 0.001)

    out["momentum_12_1"] = momentum_12_1
    out["momentum_6_1"] = momentum_6_1
    out["combined_momentum"] = combined_momentum
    out["realized_vol_12w"] = realized_vol_12w
    out["vol_score"] = vol_score

    return out


def compute_beta_52w(stock_weekly_returns: pd.Series, sp500_weekly_returns: pd.Series) -> float:
    """
    Rolling 52-week beta: cov(stock, SP500) / var(SP500).
    Aligns by date index before computing.
    """
    if len(stock_weekly_returns) < 10 or len(sp500_weekly_returns) < 10:
        return np.nan
    aligned = pd.concat([stock_weekly_returns, sp500_weekly_returns], axis=1).dropna()
    aligned.columns = ["stock", "sp500"]
    tail = aligned.tail(52)
    if len(tail) < 10:
        return np.nan
    var_sp = float(tail["sp500"].var())
    if var_sp < 1e-12:
        return np.nan
    cov = float(tail["stock"].cov(tail["sp500"]))
    return cov / var_sp


def compute_qmj_score(financial: dict) -> float:
    """
    Quality Minus Junk composite score from available financial metrics.
    Returns NaN if insufficient data.
    Each component uses Z-scores across available metrics (single-stock
    approximation — cross-sectional normalization is done in batch).
    """
    def safe(key, multiplier=1.0):
        v = financial.get(key)
        return float(v) * multiplier if v is not None and pd.notna(v) else None

    # Profitability
    prof = [safe("roe"), safe("roa"), safe("gross_margin"), safe("operating_margin")]
    prof_vals = [v for v in prof if v is not None]

    # Growth
    grow = [safe("revenue_growth"), safe("earnings_growth")]
    grow_vals = [v for v in grow if v is not None]

    # Safety (debt_to_equity lower = better, current_ratio higher = better)
    saf = [safe("debt_to_equity", -1.0), safe("current_ratio")]
    saf_vals = [v for v in saf if v is not None]

    n_components = (1 if prof_vals else 0) + (1 if grow_vals else 0) + (1 if saf_vals else 0)
    if n_components == 0:
        return np.nan

    score = 0.0
    if prof_vals:
        score += float(np.mean(prof_vals))
    if grow_vals:
        score += float(np.mean(grow_vals))
    if saf_vals:
        score += float(np.mean(saf_vals))
    return score / n_components


# ---------------------------------------------------------------------------
# Batch cross-sectional service
# ---------------------------------------------------------------------------

class MomentumLowVolBatchService:
    """
    Cross-sectional normalization after per-stock features are computed.
    Computes Z-scores and percentile ranks within sector/universe.
    Must be called after feature_engineering run_all().
    """

    def __init__(self, session: Session):
        self.session = session

    def compute_cross_sectional_all(self, tickers: list[str]) -> int:
        stocks = self.session.execute(
            select(Stock).where(Stock.ticker.in_(tickers))
        ).scalars().all()
        if not stocks:
            return 0
        stock_by_id = {s.id: s for s in stocks}
        stock_ids = [s.id for s in stocks]

        # Load raw per-stock features we need
        raw_features = ["combined_momentum", "vol_score", "beta_52w", "momentum_12_1"]
        rows = self.session.execute(
            select(FeatureWeekly).where(
                FeatureWeekly.stock_id.in_(stock_ids),
                FeatureWeekly.feature_name.in_(raw_features),
            )
        ).scalars().all()

        if not rows:
            return 0

        df = pd.DataFrame([{
            "stock_id": r.stock_id,
            "week_ending": r.week_ending,
            "feature_name": r.feature_name,
            "value": r.value,
        } for r in rows])

        df["sector"] = df["stock_id"].map(
            lambda sid: getattr(stock_by_id.get(sid), "sector", None) or "Unknown"
        )
        wide = df.pivot_table(
            index=["stock_id", "week_ending", "sector"],
            columns="feature_name",
            values="value",
        ).reset_index()

        out_rows = []
        for week, wdf in wide.groupby("week_ending"):
            # mom_lowvol_score = Z-score of (combined_momentum * vol_score)
            if "combined_momentum" in wdf.columns and "vol_score" in wdf.columns:
                raw_ml = wdf["combined_momentum"] * wdf["vol_score"]
                out_rows += self._zscore_feature(wdf, raw_ml, week, "mom_lowvol_score")
                out_rows += self._percentile_feature(wdf, wdf.get("vol_score"), week, "vol_score_rank")

            # BAB: bab_score = Z-score of -beta_52w
            if "beta_52w" in wdf.columns:
                raw_bab = -wdf["beta_52w"]
                out_rows += self._zscore_feature(wdf, raw_bab, week, "bab_score")
                out_rows += self._sector_percentile_feature(wdf, wdf["beta_52w"], week, "beta_percentile_in_sector", ascending=True)

            # Momentum rank: percentile of momentum_12_1 within sector and universe
            if "momentum_12_1" in wdf.columns:
                out_rows += self._sector_percentile_feature(wdf, wdf["momentum_12_1"], week, "momentum_rank_in_sector")
                out_rows += self._percentile_feature(wdf, wdf.get("momentum_12_1"), week, "momentum_rank_in_universe")

        if out_rows:
            stmt = pg_insert(FeatureWeekly).values(out_rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["stock_id", "week_ending", "feature_name", "feature_set_version"],
                set_={"value": stmt.excluded.value},
            )
            self.session.execute(stmt)
            self.session.commit()
            logger.info("MomentumLowVol cross-sectional: %d rows", len(out_rows))
        return len(out_rows)

    def _zscore_feature(self, wdf, series, week, feature_name):
        valid = wdf[series.notna()].copy()
        if valid.empty:
            return []
        mu = series.dropna().mean()
        std = series.dropna().std()
        if std < 1e-12:
            zscores = pd.Series(0.0, index=valid.index)
        else:
            zscores = (series.loc[valid.index] - mu) / std
        return [{
            "stock_id": int(row["stock_id"]),
            "week_ending": week,
            "feature_name": feature_name,
            "value": float(zscores.loc[i]) if pd.notna(zscores.loc[i]) else None,
            "feature_set_version": FEATURE_SET_VERSION,
        } for i, row in valid.iterrows()]

    def _percentile_feature(self, wdf, series, week, feature_name):
        if series is None:
            return []
        valid = wdf[series.notna()].copy()
        if valid.empty:
            return []
        pcts = series.loc[valid.index].rank(pct=True)
        return [{
            "stock_id": int(wdf.loc[i, "stock_id"]),
            "week_ending": week,
            "feature_name": feature_name,
            "value": float(pcts.loc[i]),
            "feature_set_version": FEATURE_SET_VERSION,
        } for i in valid.index]

    def _sector_percentile_feature(self, wdf, series, week, feature_name, ascending=False):
        out = []
        wdf = wdf.copy()
        wdf["_val"] = series.values
        for sector, sdf in wdf.groupby("sector"):
            valid = sdf[sdf["_val"].notna()]
            if valid.empty:
                continue
            pcts = valid["_val"].rank(pct=True, ascending=ascending)
            for i, row in valid.iterrows():
                out.append({
                    "stock_id": int(row["stock_id"]),
                    "week_ending": week,
                    "feature_name": feature_name,
                    "value": float(pcts.loc[i]),
                    "feature_set_version": FEATURE_SET_VERSION,
                })
        return out

    def get_sp500_weekly_returns(self) -> pd.Series:
        """Load SP500 weekly returns from macro_indicators for use in beta computation."""
        rows = self.session.execute(
            select(MacroIndicator)
            .where(MacroIndicator.indicator_code == "SP500")
            .order_by(MacroIndicator.date)
        ).scalars().all()
        if not rows:
            return pd.Series(dtype=float)
        df = pd.DataFrame([{"date": r.date, "value": r.value} for r in rows])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        weekly = df["value"].resample("W-FRI").last().pct_change().dropna()
        return weekly
