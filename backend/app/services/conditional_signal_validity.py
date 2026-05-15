"""
Conditional Signal Validity (CSV) Framework.

Core idea: a signal (e.g. RSI oversold) has different predictive power
depending on the market regime. CSV learns which signals are valid in which
conditions and outputs a regime-conditional validity score per signal.

Modules:
  1A CSV Core:     Train regime-conditional logistic models per signal.
  1B CSV Meta:     Combine signal validity scores into a meta-score.
  1C CSV Transfer: Cross-asset signal transfer (SPY signal → sector signal).
  1D CSV Causal:   Causal filter using Granger causality proxy.

Cold start: fewer than MIN_SAMPLES → fall back to signal value as-is (weight=1.0).
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_SAMPLES = 50  # minimum rows before fitting conditional models

# Signals that CSV framework evaluates
CSV_SIGNALS = [
    "rsi_14", "macd_hist", "bb_position", "momentum",
    "anchor_proximity_high", "anchor_breakout_signal",
    "disposition_gain_proxy", "overreaction_reversal",
    "volume_zscore",
]

REGIMES = ["bull", "bear", "sideways", "high_vol", "low_vol"]


# ---------------------------------------------------------------------------
# 1A: CSV Core — regime-conditional signal validity
# ---------------------------------------------------------------------------

class SignalValidityModel:
    """
    Per-signal logistic regression trained separately per regime.

    For each (signal, regime) pair, fits:
        P(target=1 | signal_value, in_regime)

    Validity score = predicted probability (0-1) conditioned on regime.
    """

    def __init__(self, signal_name: str):
        self.signal_name = signal_name
        self._models: dict[str, Any] = {}  # regime → sklearn model
        self._scalers: dict[str, Any] = {}
        self._n_samples: dict[str, int] = {}

    def fit(self, df: pd.DataFrame, signal_col: str, target_col: str, regime_col: str) -> None:
        """
        Fit one model per regime.

        Args:
            df:          DataFrame with signal, target, regime columns.
            signal_col:  Column name for the signal value.
            target_col:  Column name for binary target (0/1).
            regime_col:  Column name for regime string.
        """
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        for regime in REGIMES:
            mask = (df[regime_col] == regime) & df[signal_col].notna() & df[target_col].notna()
            sub = df[mask]
            self._n_samples[regime] = len(sub)
            if len(sub) < MIN_SAMPLES or len(sub[target_col].unique()) < 2:
                continue
            X = sub[[signal_col]].values
            y = sub[target_col].values
            scaler = StandardScaler()
            X_s = scaler.fit_transform(X)
            model = LogisticRegression(C=1.0, max_iter=500, random_state=42)
            model.fit(X_s, y)
            self._models[regime] = model
            self._scalers[regime] = scaler

    def predict_validity(self, signal_value: float, regime: str) -> float:
        """
        Return validity score [0,1] for this signal given current regime.
        Falls back to 0.5 (neutral) if model not trained for this regime.
        """
        if np.isnan(signal_value):
            return 0.0
        model = self._models.get(regime)
        scaler = self._scalers.get(regime)
        if model is None or scaler is None:
            return 0.5  # cold start: neutral weight
        X = scaler.transform([[signal_value]])
        return float(model.predict_proba(X)[0][1])


# ---------------------------------------------------------------------------
# 1B: CSV Meta — combine validity scores
# ---------------------------------------------------------------------------

class CSVMetaScorer:
    """
    Combines multiple signal validity scores into a single meta-score.

    meta_score = weighted average of (signal_value × validity_score)
    where weights are learned from historical correlation with target.
    """

    def __init__(self):
        self._signal_weights: dict[str, float] = {}

    def fit_weights(self, df: pd.DataFrame, target_col: str = "target_2pct_1w") -> None:
        """
        Learn per-signal importance weights from historical data.
        Uses absolute correlation with target as weight proxy.
        """
        weights = {}
        for sig in CSV_SIGNALS:
            if sig in df.columns and target_col in df.columns:
                corr = abs(df[sig].corr(df[target_col]))
                weights[sig] = float(corr) if pd.notna(corr) else 0.0
        total = sum(weights.values())
        if total > 0:
            self._signal_weights = {k: v / total for k, v in weights.items()}
        else:
            self._signal_weights = {s: 1.0 / len(CSV_SIGNALS) for s in CSV_SIGNALS}

    def compute_meta_score(
        self,
        signal_values: dict[str, float],
        validity_scores: dict[str, float],
    ) -> float:
        """
        Compute weighted meta-score.

        Args:
            signal_values:  {signal_name: raw_signal_value}
            validity_scores: {signal_name: validity_score ∈ [0,1]}

        Returns:
            meta_score ∈ [0, 1]
        """
        if not signal_values:
            return 0.5

        scores = []
        weights = []
        for sig, val in signal_values.items():
            if pd.isna(val):
                continue
            validity = validity_scores.get(sig, 0.5)
            w = self._signal_weights.get(sig, 1.0 / len(CSV_SIGNALS))
            # Normalize raw signal to [0,1] using sigmoid
            norm_val = float(1.0 / (1.0 + np.exp(-val)))
            scores.append(norm_val * validity)
            weights.append(w)

        if not scores:
            return 0.5

        total_w = sum(weights)
        return round(sum(s * w for s, w in zip(scores, weights)) / total_w, 4)


# ---------------------------------------------------------------------------
# 1C: CSV Transfer — cross-asset signal transfer
# ---------------------------------------------------------------------------

class SignalTransfer:
    """
    Transfer signals from a source asset (e.g., SPY) to target stocks.

    When SPY shows a strong momentum signal, sector stocks in the same
    direction tend to continue. Transfer coefficient learned via regression.
    """

    def __init__(self):
        self._transfer_coef: float = 0.0
        self._fitted = False

    def fit(self, source_signals: pd.Series, target_returns: pd.Series) -> None:
        """
        Fit transfer coefficient: how much source signal predicts target return.

        Args:
            source_signals: SPY (or sector ETF) signal values, indexed by week.
            target_returns: Target stock returns, indexed by week.
        """
        aligned = pd.concat([source_signals, target_returns], axis=1).dropna()
        if len(aligned) < 20:
            return
        X = aligned.iloc[:, 0].values.reshape(-1, 1)
        y = aligned.iloc[:, 1].values
        from sklearn.linear_model import Ridge
        model = Ridge(alpha=1.0)
        model.fit(X, y)
        self._transfer_coef = float(model.coef_[0])
        self._fitted = True

    def apply(self, source_signal: float) -> float:
        """
        Apply transfer: returns adjusted signal contribution.

        Returns 0.0 (no contribution) if not fitted or source_signal is NaN.
        """
        if not self._fitted or np.isnan(source_signal):
            return 0.0
        return round(self._transfer_coef * source_signal, 6)


# ---------------------------------------------------------------------------
# 1D: CSV Causal — Granger causality proxy filter
# ---------------------------------------------------------------------------

def granger_causality_proxy(
    cause_series: pd.Series,
    effect_series: pd.Series,
    lag: int = 1,
    min_obs: int = 30,
) -> float:
    """
    Simplified Granger causality test using linear regression.

    Tests whether cause_series (lagged) adds predictive power for effect_series
    beyond effect_series's own lagged values.

    Returns:
        F-statistic proxy (higher = stronger causality). 0.0 if insufficient data.

    Note: Full Granger test requires statsmodels; this is a lightweight proxy.
    """
    if len(cause_series) < min_obs or len(effect_series) < min_obs:
        return 0.0

    aligned = pd.concat([cause_series.shift(lag), effect_series, effect_series.shift(lag)], axis=1).dropna()
    aligned.columns = ["cause_lag", "effect", "effect_lag"]

    if len(aligned) < min_obs:
        return 0.0

    # Restricted model: effect ~ effect_lag
    # Unrestricted model: effect ~ effect_lag + cause_lag
    # F ≈ (RSS_r - RSS_u) / RSS_u * (n - k) / q
    from sklearn.linear_model import LinearRegression

    y = aligned["effect"].values
    X_r = aligned[["effect_lag"]].values
    X_u = aligned[["effect_lag", "cause_lag"]].values

    rss_r = float(np.sum((y - LinearRegression().fit(X_r, y).predict(X_r)) ** 2))
    rss_u = float(np.sum((y - LinearRegression().fit(X_u, y).predict(X_u)) ** 2))

    if rss_u <= 0:
        return 0.0

    n = len(y)
    f_stat = ((rss_r - rss_u) / 1.0) / (rss_u / (n - 3))
    return round(max(float(f_stat), 0.0), 4)


# ---------------------------------------------------------------------------
# Main CSV orchestrator
# ---------------------------------------------------------------------------

class CSVFramework:
    """
    Full Conditional Signal Validity orchestrator.

    Usage:
        csv = CSVFramework()
        csv.fit(historical_df)
        scores = csv.score(current_features, regime)
    """

    def __init__(self):
        self._validity_models: dict[str, SignalValidityModel] = {
            sig: SignalValidityModel(sig) for sig in CSV_SIGNALS
        }
        self._meta_scorer = CSVMetaScorer()
        self._fitted = False

    def fit(
        self,
        df: pd.DataFrame,
        target_col: str = "target_2pct_1w",
        regime_col: str = "regime_type",
    ) -> None:
        """
        Fit all CSV components on historical feature + regime + label data.

        Args:
            df:          DataFrame with signal columns, target, regime_type.
            target_col:  Binary label column.
            regime_col:  Regime string column.
        """
        for sig, model in self._validity_models.items():
            if sig in df.columns:
                model.fit(df, signal_col=sig, target_col=target_col, regime_col=regime_col)

        self._meta_scorer.fit_weights(df, target_col=target_col)
        self._fitted = True
        logger.info("CSVFramework: fitted on %d rows, %d signals", len(df), len(CSV_SIGNALS))

    def score(self, features: dict[str, float], regime: str) -> dict[str, float]:
        """
        Compute CSV scores for a single observation.

        Args:
            features: Dict of signal_name → signal_value.
            regime:   Current market regime string.

        Returns:
            Dict with validity scores per signal + 'csv_meta_score'.
        """
        validity_scores: dict[str, float] = {}
        for sig in CSV_SIGNALS:
            val = features.get(sig, np.nan)
            validity_scores[sig] = (
                self._validity_models[sig].predict_validity(val, regime)
                if self._fitted else 0.5
            )

        signal_values = {sig: features.get(sig, np.nan) for sig in CSV_SIGNALS}
        meta = self._meta_scorer.compute_meta_score(signal_values, validity_scores)

        result = {f"csv_{sig}_validity": v for sig, v in validity_scores.items()}
        result["csv_meta_score"] = meta
        return result
