"""
Thompson Sampling Bandit for strategy selection.

Each strategy is modeled as a Beta(alpha, beta) distribution.
  alpha = paper trade hits + 1
  beta  = paper trade misses + 1

Each selection: sample from each strategy's Beta, pick argmax.
Update: when a paper trade closes, increment alpha (hit) or beta (miss).

Storage: strategy_bandit_arms table (strategy_id, alpha, beta, last_updated).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.strategy_bandit_arm import StrategyBanditArm

logger = logging.getLogger(__name__)


class StrategyBandit:
    """
    Thompson Sampling multi-armed bandit for strategy selection.

    Usage:
        bandit = StrategyBandit(session)
        strategy_id = bandit.select_strategy(candidate_ids)
        bandit.record_outcome(strategy_id, hit=True)
    """

    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------
    # Arm management
    # ------------------------------------------------------------------

    def _get_or_create_arm(self, strategy_id: int) -> StrategyBanditArm:
        arm = self.session.execute(
            select(StrategyBanditArm).where(StrategyBanditArm.strategy_id == strategy_id)
        ).scalar_one_or_none()
        if arm is None:
            arm = StrategyBanditArm(
                strategy_id=strategy_id,
                alpha=1,
                beta=1,
                last_updated=datetime.now(tz=timezone.utc),
            )
            self.session.add(arm)
            self.session.flush()
        return arm

    def _persist_arm(self, strategy_id: int, alpha: int, beta: int) -> None:
        arm = self.session.execute(
            select(StrategyBanditArm).where(StrategyBanditArm.strategy_id == strategy_id)
        ).scalar_one_or_none()
        if arm is None:
            arm = StrategyBanditArm(strategy_id=strategy_id)
            self.session.add(arm)
        arm.alpha = alpha
        arm.beta = beta
        arm.last_updated = datetime.now(tz=timezone.utc).replace(tzinfo=None)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def select_strategy(self, candidate_ids: list[int]) -> int | None:
        """
        Thompson Sampling: sample from each strategy's Beta distribution,
        return the strategy_id with the highest sample.

        Args:
            candidate_ids: List of strategy IDs to choose from.

        Returns:
            Selected strategy_id, or None if list is empty.
        """
        if not candidate_ids:
            return None

        arms = {sid: self._get_or_create_arm(sid) for sid in candidate_ids}
        samples = {
            sid: np.random.beta(arm.alpha, arm.beta)
            for sid, arm in arms.items()
        }
        selected = max(samples, key=lambda sid: samples[sid])
        logger.debug(
            "Bandit selected strategy %d (sample=%.4f) from %d candidates",
            selected, samples[selected], len(candidate_ids),
        )
        return selected

    # ------------------------------------------------------------------
    # Outcome recording
    # ------------------------------------------------------------------

    def record_outcome(self, strategy_id: int, hit: bool) -> None:
        """
        Update Beta parameters after a paper trade closes.

        Args:
            strategy_id: Strategy that generated the trade.
            hit:         True if trade hit the return target, False otherwise.
        """
        arm = self._get_or_create_arm(strategy_id)
        if hit:
            arm.alpha += 1
        else:
            arm.beta += 1
        arm.last_updated = datetime.now(tz=timezone.utc)
        self._persist_arm(strategy_id, arm.alpha, arm.beta)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
        logger.info(
            "Bandit arm %d updated: alpha=%d beta=%d (hit=%s)",
            strategy_id, arm.alpha, arm.beta, hit,
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def arm_summary(self, strategy_ids: list[int] | None = None) -> list[dict]:
        """Return Beta parameters and expected win rate for each arm."""
        if strategy_ids:
            rows = self.session.execute(
                select(StrategyBanditArm).where(StrategyBanditArm.strategy_id.in_(strategy_ids))
            ).scalars().all()
        else:
            rows = self.session.execute(select(StrategyBanditArm)).scalars().all()

        return [
            {
                "strategy_id": r.strategy_id,
                "alpha": r.alpha,
                "beta": r.beta,
                "expected_hit_rate": round(r.alpha / (r.alpha + r.beta), 4),
                "n_trials": r.alpha + r.beta - 2,  # subtract the Bayesian priors
                "last_updated": r.last_updated.isoformat() if r.last_updated else None,
            }
            for r in rows
        ]
