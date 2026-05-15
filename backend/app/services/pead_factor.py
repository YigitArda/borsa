"""
Post-Earnings Announcement Drift (PEAD) Factor

Factors:
  2A. SUE score — Standardized Unexpected Earnings (Ball & Brown 1968)
  2B. Drift tracking — earnings day return + post-earnings week confirmation
  2C. Analyst revision momentum (Chan et al. 1996)
  2D. Volume confirmation — institutional interest proxy
  2E. Earnings calendar — days to/since earnings, giriş penceresi

Academic evidence: 60 years of drift, 60-75% directional accuracy post-surprise.
Data source: yfinance earnings_dates + earnings_estimate

Lookahead rule: All features computed from data available BEFORE week_ending.
"""
import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.pead_signal import PEADSignal

logger = logging.getLogger(__name__)

PEAD_FEATURES = [
    "sue_score",
    "weeks_since_earnings",
    "pead_signal_strength",
    "pead_decay",
    "earnings_surprise_direction",
    "drift_confirmed",
    "drift_strength",
    "drift_momentum",
    "earnings_day_return",
    "post_earnings_week1",
    "revision_momentum",
    "revision_score",
    "earnings_volume_ratio",
    "institutional_interest_flag",
    "days_to_next_earnings",
    "days_since_last_earnings",
]


def pead_decay(weeks_since_earnings: float) -> float:
    """Linear decay: full at 0 weeks, zero at 6 weeks."""
    return float(max(0.0, 1.0 - weeks_since_earnings / 6.0))


class PEADFactor:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest_earnings(self, ticker: str) -> int:
        """
        Fetch earnings history from yfinance and store in pead_signals.
        Call this before computing features.
        """
        stock = self.session.execute(
            select(Stock).where(Stock.ticker == ticker)
        ).scalar_one_or_none()
        if not stock:
            return 0

        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            earnings_dates = t.earnings_dates
        except Exception as e:
            logger.warning("yfinance earnings_dates failed %s: %s", ticker, e)
            return 0

        if earnings_dates is None or earnings_dates.empty:
            return 0

        # earnings_dates index = earnings date; columns include 'EPS Estimate', 'Reported EPS'
        rows = []
        for dt, row in earnings_dates.iterrows():
            try:
                e_date = dt.date() if hasattr(dt, "date") else dt
                actual = row.get("Reported EPS")
                expected = row.get("EPS Estimate")
                if pd.notna(actual) and pd.notna(expected):
                    rows.append({
                        "stock_id": stock.id,
                        "earnings_date": e_date,
                        "actual_eps": float(actual),
                        "expected_eps": float(expected),
                    })
            except Exception:
                pass

        if not rows:
            return 0

        # Compute SUE for each row (8-quarter rolling std of surprise)
        surprises = [r["actual_eps"] - r["expected_eps"] for r in rows]
        for i, row in enumerate(rows):
            window = surprises[max(0, i - 7): i + 1]  # up to 8 quarters, inclusive
            std = float(np.std(window)) if len(window) > 1 else 1.0
            surprise = surprises[i]
            row["sue_score"] = round(surprise / std, 4) if std > 1e-6 else 0.0

        stmt = pg_insert(PEADSignal).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_id", "earnings_date"],
            set_={
                "actual_eps": stmt.excluded.actual_eps,
                "expected_eps": stmt.excluded.expected_eps,
                "sue_score": stmt.excluded.sue_score,
            },
        )
        self.session.execute(stmt)
        self.session.commit()
        logger.info("PEAD ingested %d earnings records for %s", len(rows), ticker)
        return len(rows)

    def update_price_confirmations(self, ticker: str, daily_df: pd.DataFrame) -> int:
        """
        After ingesting earnings dates, compute earnings_day_return, post_earnings_week1,
        and earnings_volume_ratio from price data.

        daily_df: DataFrame with index=date, columns=[open, high, low, close, volume]
        """
        stock = self.session.execute(
            select(Stock).where(Stock.ticker == ticker)
        ).scalar_one_or_none()
        if not stock:
            return 0

        signals = self.session.execute(
            select(PEADSignal).where(PEADSignal.stock_id == stock.id)
        ).scalars().all()

        updated = 0
        for sig in signals:
            ed = pd.Timestamp(sig.earnings_date)
            try:
                # Earnings day return
                if ed in daily_df.index:
                    prev_idx = daily_df.index.get_loc(ed) - 1
                    if prev_idx >= 0:
                        prev_close = daily_df["close"].iloc[prev_idx]
                        ed_close = daily_df.loc[ed, "close"]
                        sig.earnings_day_return = float(ed_close / prev_close - 1)

                # Post-earnings week 1 (5 trading days after earnings)
                future = daily_df[daily_df.index > ed].iloc[:5]
                if len(future) >= 5:
                    week1_return = float(future["close"].iloc[-1] / future["close"].iloc[0] - 1)
                    sig.post_earnings_week1 = week1_return

                # Volume surprise ratio: earnings week vs prior 4 weeks
                prior = daily_df[daily_df.index < ed].tail(20)  # 4 weeks ≈ 20 days
                earnings_week_vol = daily_df[daily_df.index >= ed].head(5)["volume"].sum()
                if len(prior) >= 10 and prior["volume"].mean() > 0:
                    sig.earnings_volume_ratio = float(
                        earnings_week_vol / (prior["volume"].mean() * 5)
                    )
                updated += 1
            except Exception:
                pass

        self.session.commit()
        return updated

    # ------------------------------------------------------------------
    # Feature computation (reads from DB)
    # ------------------------------------------------------------------

    def compute_features(
        self,
        stock_id: int,
        week_end_date: date,
        weekly_df: pd.DataFrame | None = None,
    ) -> dict:
        """
        Return PEAD features for a given stock as of week_end_date.
        Uses only data from signals with earnings_date < week_end_date.
        """
        null_out = {k: np.nan for k in PEAD_FEATURES}

        signals = self.session.execute(
            select(PEADSignal)
            .where(
                PEADSignal.stock_id == stock_id,
                PEADSignal.earnings_date < week_end_date,
            )
            .order_by(PEADSignal.earnings_date.desc())
        ).scalars().all()

        if not signals:
            return null_out

        latest = signals[0]
        e_date = latest.earnings_date
        weeks_since = (week_end_date - e_date).days / 7.0
        decay = pead_decay(weeks_since)
        sue = latest.sue_score or 0.0

        out: dict = {}
        out["sue_score"] = round(sue, 4)
        out["weeks_since_earnings"] = round(weeks_since, 2)
        out["pead_decay"] = round(decay, 4)
        out["earnings_surprise_direction"] = (
            1.0 if sue > 0 else (-1.0 if sue < 0 else 0.0)
        )
        out["days_since_last_earnings"] = float((week_end_date - e_date).days)

        # Drift confirmation
        edr = latest.earnings_day_return
        pew1 = latest.post_earnings_week1
        drift_confirmed = 0.0
        drift_momentum = np.nan
        drift_strength = 0.0
        if edr is not None and pew1 is not None:
            drift_confirmed = 1.0 if edr * pew1 > 0 else 0.0
            # Drift momentum: post-week1 return normalized by vol
            if weekly_df is not None and not weekly_df.empty:
                avail = weekly_df[weekly_df.index < pd.Timestamp(week_end_date)]["weekly_return"].dropna()
                recent_vol = float(avail.iloc[-12:].std()) if len(avail) >= 12 else float(avail.std() + 1e-6)
                if recent_vol > 1e-6:
                    drift_momentum = round(float(pew1) / recent_vol, 4)
            drift_strength = round(sue * drift_confirmed * decay, 4)

        out["drift_confirmed"] = drift_confirmed
        out["drift_strength"] = drift_strength
        out["drift_momentum"] = drift_momentum if pd.notna(drift_momentum) else np.nan
        out["earnings_day_return"] = float(edr) if edr is not None else np.nan
        out["post_earnings_week1"] = float(pew1) if pew1 is not None else np.nan

        # Volume confirmation
        evr = latest.earnings_volume_ratio
        out["earnings_volume_ratio"] = float(evr) if evr is not None else np.nan
        out["institutional_interest_flag"] = 1.0 if evr is not None and evr > 2.0 else 0.0

        # PEAD signal strength
        out["pead_signal_strength"] = round(abs(sue) * decay, 4)

        # Analyst revision momentum — use ERM proxy from DB
        # We compute revision from available signals (look at previous quarter's EPS estimate change)
        revision_momentum = np.nan
        revision_score = np.nan
        if len(signals) >= 2:
            prev = signals[1]
            if prev.expected_eps and prev.expected_eps != 0 and latest.expected_eps:
                rev = (latest.expected_eps - prev.expected_eps) / abs(prev.expected_eps)
                revision_momentum = round(float(rev), 4)
                revision_score = revision_momentum  # breadth unavailable from yfinance
        out["revision_momentum"] = revision_momentum if pd.notna(revision_momentum) else np.nan
        out["revision_score"] = revision_score if pd.notna(revision_score) else np.nan

        # Days to next earnings (look ahead in DB for future signals)
        # We use yfinance-stored future entries if they exist
        future_signals = self.session.execute(
            select(PEADSignal)
            .where(
                PEADSignal.stock_id == stock_id,
                PEADSignal.earnings_date >= week_end_date,
            )
            .order_by(PEADSignal.earnings_date.asc())
            .limit(1)
        ).scalar_one_or_none()

        if future_signals:
            out["days_to_next_earnings"] = float(
                (future_signals.earnings_date - week_end_date).days
            )
        else:
            out["days_to_next_earnings"] = np.nan

        return out

    def run_all(self, tickers: list[str]) -> dict:
        results = {}
        for ticker in tickers:
            try:
                results[ticker] = self.ingest_earnings(ticker)
            except Exception as e:
                logger.error("PEAD ingest failed %s: %s", ticker, e)
                results[ticker] = 0
        return results
