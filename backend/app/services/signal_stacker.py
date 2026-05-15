"""
Hierarchical Signal Stacking (Meta-Aggregation).

Combines four signal layers into a single final_signal_score:
  - micro_score:  behavioral/CSV signals (anchoring, herding, disposition)
  - tech_score:   LightGBM prob_2pct (existing model output)
  - fund_score:   fundamental layer (ERM, valuation momentum)
  - macro_score:  macro regime score

Stacking model: LogisticRegression (interpretable, fast).
Regime-conditional weights: different importance per layer based on regime.
Weights stored in signal_stacker_weights table (restart-safe).

Cold start: fewer than MIN_SAMPLES → equal-weight average.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MIN_SAMPLES = 100
PREDICT_THRESHOLD = 0.50

# Default regime-conditional weights (used as prior before fitting)
# Format: {regime: {layer: weight}}
DEFAULT_WEIGHTS = {
    "bull":     {"tech": 0.50, "fund": 0.20, "micro": 0.15, "macro": 0.15},
    "bear":     {"tech": 0.15, "fund": 0.30, "micro": 0.15, "macro": 0.40},
    "sideways": {"tech": 0.30, "fund": 0.25, "micro": 0.25, "macro": 0.20},
    "high_vol": {"tech": 0.20, "fund": 0.20, "micro": 0.40, "macro": 0.20},
    "low_vol":  {"tech": 0.40, "fund": 0.30, "micro": 0.15, "macro": 0.15},
    "risk_on":  {"tech": 0.45, "fund": 0.25, "micro": 0.15, "macro": 0.15},
    "risk_off": {"tech": 0.15, "fund": 0.25, "micro": 0.20, "macro": 0.40},
    "unknown":  {"tech": 0.30, "fund": 0.25, "micro": 0.25, "macro": 0.20},
}

LAYER_NAMES = ["tech", "fund", "micro", "macro"]


# ---------------------------------------------------------------------------
# Fundamental score computation
# ---------------------------------------------------------------------------

def compute_fund_score(features: dict[str, float]) -> float:
    """
    Compute fundamental layer score from available features.

    Earnings Revision Momentum (ERM) + valuation momentum.
    Returns [0, 1] probability-like score.
    """
    signals = []

    # ERM: earnings revision momentum
    erm = features.get("erm_score", np.nan)
    if pd.notna(erm):
        # sigmoid on ERM
        signals.append(float(1.0 / (1.0 + np.exp(-erm * 5))))

    # Valuation momentum: declining forward PE = cheaper → bullish
    fpe_change = features.get("forward_pe_change", np.nan)
    if pd.notna(fpe_change):
        signals.append(float(1.0 / (1.0 + np.exp(fpe_change * 2))))  # lower PE → higher score

    # Quality metrics
    roe = features.get("roe", np.nan)
    if pd.notna(roe) and roe > 0:
        signals.append(float(np.clip(roe / 0.30, 0, 1)))  # 30% ROE → score=1

    rev_growth = features.get("revenue_growth", np.nan)
    if pd.notna(rev_growth):
        signals.append(float(np.clip(rev_growth / 0.20 + 0.5, 0, 1)))

    if not signals:
        return 0.5
    return round(float(np.mean(signals)), 4)


def compute_micro_score(features: dict[str, float]) -> float:
    """
    Compute micro/behavioral score from behavioral and CSV features.

    Returns [0, 1] score.
    """
    signals = []

    # CSV meta score (already [0,1])
    csv_meta = features.get("csv_meta_score", np.nan)
    if pd.notna(csv_meta):
        signals.append(float(csv_meta))

    # Anchor breakout → strong bullish
    breakout = features.get("anchor_breakout_signal", np.nan)
    if pd.notna(breakout):
        signals.append(float(breakout))  # 0 or 1

    # Overreaction reversal: negative → reversal signal
    reversal = features.get("overreaction_reversal", np.nan)
    if pd.notna(reversal):
        signals.append(float(np.clip(reversal / 0.10 + 0.5, 0, 1)))

    # Herding: high herding → momentum continuation (bull), reversal risk (bear)
    herding = features.get("herding_score", np.nan)
    if pd.notna(herding):
        signals.append(float(herding))

    # N-gram bullish score from price NLP
    ngram_bull = features.get("ngram_bullish_score", np.nan)
    if pd.notna(ngram_bull):
        signals.append(float(np.clip(ngram_bull, 0, 1)))

    if not signals:
        return 0.5
    return round(float(np.mean(signals)), 4)


def compute_macro_score(features: dict[str, float]) -> float:
    """
    Compute macro layer score from macro features.

    Returns [0, 1] score.
    """
    signals = []

    # VIX: high VIX → fear → bearish
    vix = features.get("VIX", np.nan)
    if pd.notna(vix) and vix > 0:
        signals.append(float(np.clip(1.0 - (vix - 10) / 40, 0, 1)))  # VIX 10→1.0, 50→0.0

    # Risk-on score (already computed)
    risk_on = features.get("RISK_ON_SCORE", np.nan)
    if pd.notna(risk_on):
        signals.append(float(np.clip(risk_on, 0, 1)))

    # SPY trend
    spy_trend = features.get("sp500_trend_20w", np.nan)
    if pd.notna(spy_trend):
        signals.append(float(np.clip(spy_trend / 0.1 + 0.5, 0, 1)))

    if not signals:
        return 0.5
    return round(float(np.mean(signals)), 4)


# ---------------------------------------------------------------------------
# Stacker model
# ---------------------------------------------------------------------------

class SignalStacker:
    """
    Meta-aggregation model combining four signal layers.

    Usage:
        stacker = SignalStacker(session)
        stacker.fit(historical_df)
        final_score = stacker.predict(features, regime)
    """

    def __init__(self, session: Session | None = None):
        self.session = session
        self._models: dict[str, Any] = {}   # regime → LogisticRegression
        self._scalers: dict[str, Any] = {}
        self._weights: dict[str, dict] = dict(DEFAULT_WEIGHTS)
        self._n_samples: dict[str, int] = {}
        self._fitted = False

    # ------------------------------------------------------------------
    # Fit
    # ------------------------------------------------------------------

    def fit(
        self,
        df: pd.DataFrame,
        target_col: str = "target_2pct_1w",
        regime_col: str = "regime_type",
    ) -> None:
        """
        Fit regime-conditional stacking models.

        Args:
            df:          DataFrame with tech_score, fund_score, micro_score,
                         macro_score, regime_type, and target columns.
            target_col:  Binary label.
            regime_col:  Regime string column.
        """
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        required = ["tech_score", "fund_score", "micro_score", "macro_score"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            logger.warning("SignalStacker.fit: missing columns %s", missing)
            return

        for regime in DEFAULT_WEIGHTS:
            mask = (df[regime_col] == regime) & df[target_col].notna()
            sub = df[mask].dropna(subset=required)
            self._n_samples[regime] = len(sub)
            if len(sub) < MIN_SAMPLES or len(sub[target_col].unique()) < 2:
                continue
            X = sub[required].values
            y = sub[target_col].values
            scaler = StandardScaler()
            X_s = scaler.fit_transform(X)
            model = LogisticRegression(C=1.0, max_iter=500, random_state=42)
            model.fit(X_s, y)
            self._models[regime] = model
            self._scalers[regime] = scaler
            # Extract learned weights from coefficients
            coefs = model.coef_[0]
            coef_sum = sum(abs(c) for c in coefs) or 1.0
            self._weights[regime] = {
                layer: round(abs(float(c)) / coef_sum, 4)
                for layer, c in zip(LAYER_NAMES, coefs)
            }

        self._fitted = True
        self._persist_weights()
        logger.info("SignalStacker: fitted for %d regimes", len(self._models))

    # ------------------------------------------------------------------
    # Predict
    # ------------------------------------------------------------------

    def predict(
        self,
        features: dict[str, float],
        regime: str,
        tech_score: float | None = None,
    ) -> tuple[float, dict]:
        """
        Compute final_signal_score for one observation.

        Args:
            features:   Full feature dict (all layers' raw features).
            regime:     Current market regime.
            tech_score: Overrides tech layer if provided (e.g., from existing LightGBM).

        Returns:
            (final_signal_score ∈ [0,1], component_scores dict)
        """
        tech = tech_score if tech_score is not None else float(features.get("prob_2pct", 0.5))
        fund = compute_fund_score(features)
        micro = compute_micro_score(features)
        macro = compute_macro_score(features)

        components = {
            "tech_score": round(tech, 4),
            "fund_score": fund,
            "micro_score": micro,
            "macro_score": macro,
        }

        model = self._models.get(regime)
        scaler = self._scalers.get(regime)

        if model is not None and scaler is not None:
            X = scaler.transform([[tech, fund, micro, macro]])
            final = float(model.predict_proba(X)[0][1])
        else:
            # Fall back to regime-conditional weighted average
            w = self._weights.get(regime, self._weights["unknown"])
            final = (
                w["tech"] * tech
                + w["fund"] * fund
                + w["micro"] * micro
                + w["macro"] * macro
            )

        return round(final, 4), components

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_weights(self) -> None:
        if self.session is None:
            return
        try:
            from app.models.signal_stacker_weights import SignalStackerWeights
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            for regime, w in self._weights.items():
                stmt = pg_insert(SignalStackerWeights).values(
                    regime_type=regime,
                    weights_json=w,
                    n_samples=self._n_samples.get(regime, 0),
                    last_trained=datetime.now(tz=timezone.utc),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["regime_type"],
                    set_={"weights_json": stmt.excluded.weights_json,
                          "n_samples": stmt.excluded.n_samples,
                          "last_trained": stmt.excluded.last_trained},
                )
                self.session.execute(stmt)
            self.session.commit()
        except Exception as exc:
            logger.debug("SignalStacker: could not persist weights: %s", exc)

    def load_weights(self) -> None:
        """Load weights from DB if available."""
        if self.session is None:
            return
        try:
            from app.models.signal_stacker_weights import SignalStackerWeights
            rows = self.session.execute(select(SignalStackerWeights)).scalars().all()
            for r in rows:
                self._weights[r.regime_type] = r.weights_json
        except Exception as exc:
            logger.debug("SignalStacker: could not load weights: %s", exc)

    def weights_summary(self) -> dict:
        return {"weights_by_regime": self._weights, "n_samples": self._n_samples}
