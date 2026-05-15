"""
Mutation Memory — directed search for StrategyProposer.

Tracks which mutation types and features historically improved Sharpe.
StrategyProposer uses these weights (epsilon-greedy) instead of pure random.

Storage: mutation_memory table (restart-safe, DB-backed).
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.mutation_memory import MutationMemory

logger = logging.getLogger(__name__)

MUTATION_TYPES = [
    "add_feature", "remove_feature", "change_threshold",
    "change_top_n", "change_model", "holding_period",
    "stop_loss", "take_profit",
]

# Epsilon for exploration: 20% chance to pick randomly regardless of scores
EPSILON = 0.20


def _softmax(scores: list[float], temperature: float = 1.0) -> list[float]:
    """Numerically stable softmax."""
    arr = np.array(scores, dtype=float) / temperature
    arr -= arr.max()
    exp_arr = np.exp(arr)
    return (exp_arr / exp_arr.sum()).tolist()


class MutationScoreTracker:
    """
    Tracks per-feature and per-mutation-type success scores.

    Scores are updated with sharpe_delta after each research iteration:
      passed=True  → +sharpe_delta
      passed=False → sharpe_delta (negative)

    Feature weights are used by StrategyProposer to bias add/remove decisions.
    """

    def __init__(self, session: Session):
        self.session = session
        self._cache: dict[tuple[str, str], float] = {}  # (feature_or_type, scope) → score
        self._loaded = False

    # ------------------------------------------------------------------
    # Load / persist
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load all scores from DB into local cache."""
        rows = self.session.execute(select(MutationMemory)).scalars().all()
        for r in rows:
            self._cache[(r.feature_name, r.mutation_type)] = r.score
        self._loaded = True
        logger.debug("MutationMemory: loaded %d score entries", len(rows))

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def _persist(self, feature_name: str, mutation_type: str, score: float, n_trials: int) -> None:
        row = self.session.execute(
            select(MutationMemory).where(
                MutationMemory.feature_name == feature_name,
                MutationMemory.mutation_type == mutation_type,
            )
        ).scalar_one_or_none()
        if row is None:
            row = MutationMemory(feature_name=feature_name, mutation_type=mutation_type)
            self.session.add(row)
        row.score = score
        row.n_trials = n_trials
        row.last_updated = datetime.now(tz=timezone.utc).replace(tzinfo=None)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(
        self,
        mutation_type: str,
        features_added: list[str] | None,
        features_removed: list[str] | None,
        sharpe_delta: float,
    ) -> None:
        """
        Update scores after a research iteration.

        Args:
            mutation_type:    Which mutation was applied.
            features_added:   Features added this iteration (may be empty).
            features_removed: Features removed this iteration (may be empty).
            sharpe_delta:     avg_sharpe - base_sharpe (positive = improvement).
        """
        self._ensure_loaded()

        # Update mutation type score
        mut_key = ("__type__", mutation_type)
        old_score = self._cache.get(mut_key, 0.0)
        n_key = ("__ntrial__", mutation_type)
        n = int(self._cache.get(n_key, 0)) + 1
        new_score = old_score + sharpe_delta
        self._cache[mut_key] = new_score
        self._cache[n_key] = float(n)
        self._persist("__type__", mutation_type, new_score, n)

        # Update individual feature scores
        for feat in (features_added or []):
            key = (feat, "add_feature")
            old = self._cache.get(key, 0.0)
            nf_key = (feat, "__nadd__")
            nf = int(self._cache.get(nf_key, 0)) + 1
            self._cache[key] = old + sharpe_delta
            self._cache[nf_key] = float(nf)
            self._persist(feat, "add_feature", old + sharpe_delta, nf)

        for feat in (features_removed or []):
            key = (feat, "remove_feature")
            old = self._cache.get(key, 0.0)
            nf_key = (feat, "__nremove__")
            nf = int(self._cache.get(nf_key, 0)) + 1
            self._cache[key] = old - sharpe_delta  # removing a good feature = bad
            self._cache[nf_key] = float(nf)
            self._persist(feat, "remove_feature", old - sharpe_delta, nf)

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()

    # ------------------------------------------------------------------
    # Weights
    # ------------------------------------------------------------------

    def get_feature_weights(self, feature_pool: list[str]) -> list[float]:
        """
        Return probability distribution over features for add_feature mutations.
        Uses softmax on stored add_feature scores.
        Higher score → more likely to be selected.
        Falls back to uniform if no data.
        """
        self._ensure_loaded()
        scores = [self._cache.get((f, "add_feature"), 0.0) for f in feature_pool]
        return _softmax(scores)

    def get_remove_weights(self, current_features: list[str]) -> list[float]:
        """
        Return probability distribution for remove_feature: prefer removing low-contribution features.
        Low add-score → higher removal probability (invert the score).
        """
        self._ensure_loaded()
        scores = [self._cache.get((f, "add_feature"), 0.0) for f in current_features]
        # Invert: features with lowest add-score are most likely to be removed
        inverted = [-s for s in scores]
        return _softmax(inverted)

    def get_mutation_type_weights(self) -> list[float]:
        """Return probability distribution over mutation types."""
        self._ensure_loaded()
        scores = [self._cache.get(("__type__", mt), 0.0) for mt in MUTATION_TYPES]
        return _softmax(scores)

    def should_explore(self) -> bool:
        """Return True (random) with probability EPSILON, else exploit."""
        return np.random.random() < EPSILON

    def summary(self) -> dict:
        """Return top/bottom features and mutation type scores for diagnostics."""
        self._ensure_loaded()
        feat_scores = {
            k[0]: v for k, v in self._cache.items()
            if k[1] == "add_feature" and not k[0].startswith("__")
        }
        mut_scores = {
            k[1]: v for k, v in self._cache.items()
            if k[0] == "__type__"
        }
        sorted_feats = sorted(feat_scores.items(), key=lambda x: x[1], reverse=True)
        return {
            "top_features": sorted_feats[:5],
            "bottom_features": sorted_feats[-5:],
            "mutation_type_scores": mut_scores,
        }
