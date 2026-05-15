"""
Curriculum Learning for model training.

Trains on "easy" market periods first (low VIX, strong trends),
gradually expands to include "hard" periods (crises, high volatility).

Difficulty score per week: VIX × (1 + |weekly_return_std|)
Normalized to [0, 1] across all weeks.

Schedule: starts at threshold 0.3, increments by STEP each curriculum step.
"""
from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.macro import MacroIndicator
from app.models.price import PriceWeekly
from app.models.stock import Stock

logger = logging.getLogger(__name__)

VIX_CODE = "VIX"
SPY_TICKER = "SPY"

# Curriculum schedule constants
INITIAL_THRESHOLD = 0.30   # Start: only weeks with difficulty < 30th percentile
STEP = 0.10                # Increment per curriculum level
FINAL_THRESHOLD = 1.01     # At this level, all weeks are included


class DifficultyScorer:
    """
    Computes per-week difficulty scores from VIX and market return volatility.
    """

    def __init__(self, session: Session):
        self.session = session

    def compute_weekly_difficulty(self) -> pd.Series:
        """
        Returns a pd.Series indexed by week_ending date with difficulty score [0, 1].

        difficulty_raw = VIX × (1 + |rolling_return_std|)
        difficulty = normalized to [0, 1]
        """
        vix_rows = self.session.execute(
            select(MacroIndicator)
            .where(MacroIndicator.indicator_code == VIX_CODE)
            .order_by(MacroIndicator.date)
        ).scalars().all()

        if not vix_rows:
            logger.warning("CurriculumTrainer: no VIX data found")
            return pd.Series(dtype=float)

        vix_df = pd.DataFrame([{"date": r.date, "vix": r.value} for r in vix_rows])
        vix_df["date"] = pd.to_datetime(vix_df["date"])
        vix_df = vix_df.set_index("date").sort_index()

        # Get SPY weekly returns for return std computation
        spy = self.session.execute(
            select(Stock).where(Stock.ticker == SPY_TICKER)
        ).scalar_one_or_none()

        ret_df = pd.Series(dtype=float, name="weekly_return")
        if spy:
            spy_rows = self.session.execute(
                select(PriceWeekly).where(PriceWeekly.stock_id == spy.id).order_by(PriceWeekly.week_ending)
            ).scalars().all()
            if spy_rows:
                ret_df = pd.Series(
                    {r.week_ending: r.weekly_return for r in spy_rows if r.weekly_return is not None}
                )
                ret_df.index = pd.to_datetime(ret_df.index)

        # Resample VIX to weekly (Friday) by taking Friday value or last available
        vix_weekly = vix_df["vix"].resample("W-FRI").last().ffill()

        # Rolling 4-week std of SPY returns as market volatility proxy
        if not ret_df.empty:
            ret_weekly = ret_df.resample("W-FRI").last()
            roll_std = ret_weekly.rolling(4).std().reindex(vix_weekly.index).ffill().fillna(0)
        else:
            roll_std = pd.Series(0.0, index=vix_weekly.index)

        # Difficulty raw
        difficulty_raw = vix_weekly * (1.0 + roll_std.abs())

        # Normalize to [0, 1]
        dmin = difficulty_raw.min()
        dmax = difficulty_raw.max()
        if dmax > dmin:
            difficulty = (difficulty_raw - dmin) / (dmax - dmin)
        else:
            difficulty = pd.Series(0.5, index=difficulty_raw.index)

        return difficulty.dropna()


class CurriculumScheduler:
    """
    Manages the curriculum threshold that grows over training iterations.

    threshold=0.3 → only easy weeks (difficulty < 0.3)
    threshold=1.0 → all weeks included
    """

    def __init__(self, initial: float = INITIAL_THRESHOLD, step: float = STEP):
        self.threshold = initial
        self.step = step
        self._iteration = 0

    def advance(self) -> None:
        """Advance to next curriculum level."""
        self.threshold = min(self.threshold + self.step, FINAL_THRESHOLD)
        self._iteration += 1
        logger.info("Curriculum advanced to level %d (threshold=%.2f)", self._iteration, self.threshold)

    def is_complete(self) -> bool:
        return self.threshold >= FINAL_THRESHOLD

    @property
    def level(self) -> int:
        return self._iteration


class CurriculumTrainer:
    """
    Wraps ModelTrainer.walk_forward() with curriculum filtering.

    Usage:
        ct = CurriculumTrainer(session, tickers)
        ct.compute_difficulty()   # once per session, loads VIX data
        folds = ct.walk_forward_curriculum(config, threshold=0.5)
    """

    def __init__(self, session: Session, tickers: list[str]):
        self.session = session
        self.tickers = tickers
        self._difficulty: pd.Series | None = None

    def compute_difficulty(self) -> None:
        """Load difficulty scores. Call once before training."""
        scorer = DifficultyScorer(self.session)
        self._difficulty = scorer.compute_weekly_difficulty()
        logger.info("CurriculumTrainer: computed difficulty for %d weeks", len(self._difficulty))

    def get_allowed_weeks(self, threshold: float) -> set[date]:
        """Return set of week_ending dates with difficulty < threshold."""
        if self._difficulty is None:
            self.compute_difficulty()
        if self._difficulty is None or self._difficulty.empty:
            return set()  # no filter
        allowed = self._difficulty[self._difficulty <= threshold]
        return {idx.date() for idx in allowed.index}

    def walk_forward_curriculum(
        self,
        config: dict,
        threshold: float = FINAL_THRESHOLD,
        min_train_years: int = 5,
    ) -> list:
        """
        Run walk-forward with curriculum filtering applied to training data.

        Weeks harder than threshold are excluded from training.
        Test set is always the full held-out period (no filtering on test).

        Args:
            config:          Strategy config dict.
            threshold:       Difficulty threshold [0, 1]. 1.0 = all weeks.
            min_train_years: Minimum training years (passed to ModelTrainer).

        Returns:
            List of WalkForwardFold objects.
        """
        from app.services.model_training import ModelTrainer

        allowed_weeks = self.get_allowed_weeks(threshold)
        trainer = ModelTrainer(self.session, config)

        # Monkey-patch: inject curriculum filter into the dataset loading
        if allowed_weeks and threshold < FINAL_THRESHOLD:
            original_load = trainer.load_dataset

            def curriculum_load(tickers_inner):
                df = original_load(tickers_inner)
                if df.empty:
                    return df
                if hasattr(df["week_ending"], "dt"):
                    week_dates = df["week_ending"].dt.date
                else:
                    week_dates = df["week_ending"]
                mask = week_dates.isin(allowed_weeks)
                filtered = df[mask | (week_dates > max(allowed_weeks, default=date.today()))]
                logger.debug(
                    "Curriculum filter: kept %d/%d rows (threshold=%.2f)",
                    len(filtered), len(df), threshold,
                )
                return filtered

            trainer.load_dataset = curriculum_load

        return trainer.walk_forward(self.tickers, min_train_years=min_train_years)

    def run_full_curriculum(
        self,
        config: dict,
        scheduler: CurriculumScheduler | None = None,
        n_levels: int = 7,
    ) -> list:
        """
        Run complete curriculum: easy → hard, collect all folds.
        Useful for final training before promotion.
        """
        if scheduler is None:
            scheduler = CurriculumScheduler()

        all_folds = []
        for level in range(n_levels):
            logger.info("Curriculum level %d/%d threshold=%.2f", level + 1, n_levels, scheduler.threshold)
            folds = self.walk_forward_curriculum(config, threshold=scheduler.threshold)
            all_folds.extend(folds)
            scheduler.advance()
            if scheduler.is_complete():
                break

        return all_folds

    def difficulty_summary(self) -> dict:
        """Return statistics about the difficulty distribution."""
        if self._difficulty is None:
            self.compute_difficulty()
        if self._difficulty is None or self._difficulty.empty:
            return {}
        return {
            "n_weeks": int(len(self._difficulty)),
            "mean": round(float(self._difficulty.mean()), 3),
            "std": round(float(self._difficulty.std()), 3),
            "p25": round(float(self._difficulty.quantile(0.25)), 3),
            "p50": round(float(self._difficulty.quantile(0.50)), 3),
            "p75": round(float(self._difficulty.quantile(0.75)), 3),
            "easy_weeks": int((self._difficulty < 0.3).sum()),
            "hard_weeks": int((self._difficulty > 0.7).sum()),
        }
