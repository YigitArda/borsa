"""
Meta-Learner Promotion Gate.

Learns which walk-forward features predict successful paper trading (hit_rate >= 0.45).
Trained on historical (strategy → paper_trading_outcome) pairs.
Uses LogisticRegression — interpretable and fast.

Cold start: fewer than MIN_SAMPLES examples → fall back to fixed thresholds.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MIN_SAMPLES = 20          # Min training examples before meta-learner takes effect
PREDICT_THRESHOLD = 0.60  # predict_proba >= 0.60 → promote


def _extract_features(fold_metrics: list[dict], notes: dict, n_features: int) -> list[float]:
    """
    Build a flat feature vector for the meta-learner from strategy metadata.

    Features:
        avg_sharpe, std_sharpe, avg_win_rate, avg_profit_factor,
        max_drawdown, avg_return, n_trades, n_folds,
        sharpe_trend, permutation_pvalue, deflated_sharpe,
        n_features (complexity)
    """
    if not fold_metrics:
        return [0.0] * 12

    sharpes = [m.get("sharpe", 0.0) for m in fold_metrics]
    win_rates = [m.get("win_rate", 0.0) for m in fold_metrics]
    profit_factors = [m.get("profit_factor", 0.0) for m in fold_metrics]
    drawdowns = [m.get("max_drawdown", 0.0) for m in fold_metrics]
    avg_returns = [m.get("avg_return", 0.0) for m in fold_metrics]
    n_trades = [m.get("n_trades", 0) for m in fold_metrics]

    avg_sharpe = float(np.mean(sharpes))
    std_sharpe = float(np.std(sharpes))
    avg_win_rate = float(np.mean(win_rates))
    avg_pf = float(np.mean(profit_factors))
    min_dd = float(min(drawdowns))
    avg_ret = float(np.mean(avg_returns))
    total_trades = float(sum(n_trades))
    n_folds = float(len(fold_metrics))

    # Sharpe trend: last half vs first half
    if len(sharpes) >= 4:
        mid = len(sharpes) // 2
        sharpe_trend = float(np.mean(sharpes[mid:]) - np.mean(sharpes[:mid]))
    else:
        sharpe_trend = 0.0

    perm_pvalue = float(notes.get("permutation_pvalue", 1.0))
    dsr = float(notes.get("deflated_sharpe", 0.0))

    return [
        avg_sharpe, std_sharpe, avg_win_rate, avg_pf,
        min_dd, avg_ret, total_trades, n_folds,
        sharpe_trend, perm_pvalue, dsr, float(n_features),
    ]


class MetaPromotionModel:
    """
    Logistic regression trained on (strategy_features → paper_hit_rate_success).

    Persistent: training data stored in meta_learner_training_data table.
    Model is re-fit from scratch on each predict() call (small dataset).
    """

    def __init__(self, session: Session):
        self.session = session
        self._model = None
        self._scaler = None
        self._n_samples = 0

    # ------------------------------------------------------------------
    # Training data management
    # ------------------------------------------------------------------

    def record_outcome(
        self,
        strategy_id: int,
        fold_metrics: list[dict],
        notes: dict,
        n_features: int,
        paper_hit_rate: float,
    ) -> None:
        """
        Save a training example when a strategy's paper trading completes.

        Args:
            strategy_id:    DB strategy id.
            fold_metrics:   List of fold metric dicts.
            notes:          Strategy notes dict (permutation_pvalue, deflated_sharpe, etc.).
            n_features:     Number of features in the strategy config.
            paper_hit_rate: Actual paper trading hit rate achieved.
        """
        from app.models.meta_learner_data import MetaLearnerTrainingData

        features_vec = _extract_features(fold_metrics, notes, n_features)
        label = 1 if paper_hit_rate >= 0.45 else 0

        row = self.session.execute(
            select(MetaLearnerTrainingData).where(MetaLearnerTrainingData.strategy_id == strategy_id)
        ).scalar_one_or_none()
        if row is None:
            row = MetaLearnerTrainingData(strategy_id=strategy_id)
            self.session.add(row)
        row.features_json = features_vec
        row.label = label
        row.paper_hit_rate = paper_hit_rate
        row.created_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        self.session.commit()
        logger.info("MetaLearner: recorded outcome for strategy %d (label=%d, hit_rate=%.2f)",
                    strategy_id, label, paper_hit_rate)

    def _load_training_data(self) -> tuple[np.ndarray, np.ndarray]:
        """Load all training examples from DB."""
        from app.models.meta_learner_data import MetaLearnerTrainingData
        rows = self.session.execute(select(MetaLearnerTrainingData)).scalars().all()
        if not rows:
            return np.array([]), np.array([])
        X = np.array([r.features_json for r in rows], dtype=float)
        y = np.array([r.label for r in rows], dtype=int)
        return X, y

    # ------------------------------------------------------------------
    # Fit / predict
    # ------------------------------------------------------------------

    def _fit(self) -> bool:
        """Fit model from DB data. Returns False if insufficient data."""
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        X, y = self._load_training_data()
        self._n_samples = len(y)

        if self._n_samples < MIN_SAMPLES:
            logger.info("MetaLearner: only %d samples (need %d) — cold start mode", self._n_samples, MIN_SAMPLES)
            return False

        if len(np.unique(y)) < 2:
            logger.info("MetaLearner: only one class in training data — cold start mode")
            return False

        n_positive = int(y.sum())
        n_negative = int((y == 0).sum())
        logger.info(
            "MetaLearner eğitim verisi: %d pozitif, %d negatif (toplam %d)",
            n_positive, n_negative, len(y),
        )
        if n_negative == 0:
            logger.error(
                "UYARI: Meta-learner sadece pozitif örnekler görüyor! "
                "promotion.py'de save_training_example() çağrısı eksik."
            )
            return False
        if n_positive / len(y) > 0.8:
            logger.warning(
                "Meta-learner dengesiz: %.1f%% pozitif — class_weight='balanced' uygulanıyor.",
                n_positive / len(y) * 100,
            )

        self._scaler = StandardScaler()
        X_scaled = self._scaler.fit_transform(X)
        self._model = LogisticRegression(
            C=1.0, max_iter=500, random_state=42,
            class_weight="balanced",
        )
        self._model.fit(X_scaled, y)
        logger.info("MetaLearner: fitted on %d samples (pos=%d, neg=%d)",
                    len(y), n_positive, n_negative)
        return True

    def predict(
        self,
        fold_metrics: list[dict],
        notes: dict,
        n_features: int,
    ) -> tuple[bool, float, str]:
        """
        Predict whether this strategy will achieve paper_hit_rate >= 0.45.

        Returns:
            (should_promote, confidence_score, reason_string)
        """
        ready = self._fit()
        if not ready:
            return True, 0.0, f"cold_start ({self._n_samples}/{MIN_SAMPLES} samples)"

        features = _extract_features(fold_metrics, notes, n_features)
        X = np.array([features], dtype=float)
        X_scaled = self._scaler.transform(X)
        proba = float(self._model.predict_proba(X_scaled)[0][1])

        promote = proba >= PREDICT_THRESHOLD
        reason = f"meta_learner proba={proba:.3f} ({'≥' if promote else '<'}{PREDICT_THRESHOLD})"
        return promote, proba, reason

    def feature_importance(self) -> dict[str, float]:
        """Return logistic regression coefficient magnitudes per feature."""
        if self._model is None:
            self._fit()
        if self._model is None:
            return {}
        feature_names = [
            "avg_sharpe", "std_sharpe", "avg_win_rate", "avg_profit_factor",
            "max_drawdown", "avg_return", "total_trades", "n_folds",
            "sharpe_trend", "permutation_pvalue", "deflated_sharpe", "n_features",
        ]
        coefs = self._model.coef_[0]
        return {name: round(float(abs(c)), 4) for name, c in zip(feature_names, coefs)}

    def save_training_example(
        self,
        strategy_id: int,
        fold_metrics: list[dict],
        notes: dict,
        n_features: int,
        label: int,
        paper_hit_rate: float | None = None,
    ) -> None:
        """
        Save a training example with an explicit label (0=failure, 1=success).
        Called from promotion gate so ALL strategies are recorded — not just those
        that reach paper trading with a measurable hit rate.
        """
        from app.models.meta_learner_data import MetaLearnerTrainingData

        features_vec = _extract_features(fold_metrics, notes, n_features)

        row = self.session.execute(
            select(MetaLearnerTrainingData).where(MetaLearnerTrainingData.strategy_id == strategy_id)
        ).scalar_one_or_none()
        if row is None:
            row = MetaLearnerTrainingData(strategy_id=strategy_id)
            self.session.add(row)
        row.features_json = features_vec
        row.label = label
        row.paper_hit_rate = paper_hit_rate
        row.created_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        self.session.commit()
        logger.info(
            "MetaLearner: save_training_example strategy=%d label=%d hit_rate=%s",
            strategy_id, label, f"{paper_hit_rate:.3f}" if paper_hit_rate is not None else "N/A",
        )

    def n_samples(self) -> int:
        """Number of training examples in DB."""
        if self._n_samples == 0:
            _, y = self._load_training_data()
            self._n_samples = len(y)
        return self._n_samples
