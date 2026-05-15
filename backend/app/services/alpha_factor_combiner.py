"""
Alpha Factor Combiner

  4A. Triple Factor Composite Score — MomLowVol + PEAD + ShortSqueeze
  4B. Factor-based Kelly Sizing
  4C. Signal Decay System

Combines the three alpha factors into a single score with:
  - Alignment multiplier (1 factor = 1x, 2 = 1.5x, 3 = 2x)
  - "HIGH_CONVICTION" label when all three align
  - Decay-weighted factor scores
  - Integration hook for WeeklyPredictionService
"""
import math
import numpy as np

ALPHA_COMBO_FEATURES = [
    "alpha_factor_1",
    "alpha_factor_2",
    "alpha_factor_3",
    "alpha_alignment",
    "final_alpha_score",
]

CONVICTION_LABELS = {
    # final_alpha > threshold → label
    1.5: "HIGH_CONVICTION",
    0.8: "STRONG",
    0.4: "MODERATE",
}


# ---------------------------------------------------------------------------
# Decay functions (4C)
# ---------------------------------------------------------------------------

def pead_decay(weeks_since_earnings: float) -> float:
    """Linear decay — zero at 6 weeks."""
    return float(max(0.0, 1.0 - weeks_since_earnings / 6.0))


def momentum_decay(weeks_since_signal: float) -> float:
    """Exponential decay with 26-week half-life."""
    return float(math.exp(-weeks_since_signal / 26.0))


def squeeze_decay(weeks_since_squeeze: float) -> float:
    """Fast linear decay — zero at 2 weeks."""
    return float(max(0.0, 1.0 - weeks_since_squeeze / 2.0))


# ---------------------------------------------------------------------------
# Kelly criterion (4B)
# ---------------------------------------------------------------------------

def kelly_factor_size(
    hit_rate: float,
    avg_win_loss_ratio: float,
    fractional: float = 0.25,
    max_size: float = 0.25,
) -> float:
    """
    Fractional Kelly position size for a single factor.

    hit_rate: historical win rate (0-1)
    avg_win_loss_ratio: avg win / avg loss (b in Kelly formula)
    fractional: safety factor (default 0.25 = quarter Kelly)
    max_size: maximum position size fraction

    Returns fraction of portfolio to allocate (0-1).
    """
    if avg_win_loss_ratio <= 0 or hit_rate <= 0:
        return 0.0
    b = avg_win_loss_ratio
    p = min(max(hit_rate, 0.01), 0.99)
    kelly_f = (p * b - (1 - p)) / b
    size = fractional * max(0.0, kelly_f)
    return min(size, max_size)


# ---------------------------------------------------------------------------
# Main combiner (4A + 4B + 4C)
# ---------------------------------------------------------------------------

class AlphaFactorCombiner:
    """
    Combine three factor scores into a composite signal.

    Usage:
        combiner = AlphaFactorCombiner()
        result = combiner.compute(features)
        # result: dict with alpha_factor_1/2/3, alpha_alignment, final_alpha_score,
        #         conviction_label, kelly_size, adjusted_prob_2pct
    """

    def compute(self, features: dict) -> dict:
        """
        features dict may include:
          mom_lowvol_score      — from MomentumLowVolBatchService
          pead_signal_strength  — from PEADFactor
          pead_decay            — from PEADFactor
          squeeze_score         — from ShortInterestService (0-4 pre-increment)
          momentum_12_1         — to add momentum component to squeeze_score
          weeks_since_earnings  — for decay weighting
          prob_2pct             — model probability (to blend)
        """
        # Factor 1: Momentum × Low-Vol (already Z-scored, clamp to [-3, 3])
        mlv = features.get("mom_lowvol_score", 0.0) or 0.0
        mlv = float(np.clip(mlv, -3.0, 3.0))
        # Normalize to [−1, 1] roughly
        factor_1 = mlv / 3.0

        # Factor 2: PEAD signal
        pead_str = features.get("pead_signal_strength", 0.0) or 0.0
        pead_str = float(np.clip(pead_str, 0.0, 5.0))
        factor_2 = pead_str / 5.0  # normalize to [0, 1]

        # Factor 3: Short squeeze (0-4 raw, add momentum if available)
        sq_raw = features.get("squeeze_score", 0.0) or 0.0
        mom_12_1 = features.get("momentum_12_1", 0.0) or 0.0
        if mom_12_1 > 0:
            sq_raw = min(4.0, sq_raw + 1)
        dtc = features.get("days_to_cover", 0.0) or 0.0
        if dtc > 3.0:
            sq_raw = min(4.0, sq_raw + 1)
        factor_3 = float(sq_raw) / 4.0  # normalize to [0, 1]

        # Decay-weighted factors (4C)
        weeks_since = features.get("weeks_since_earnings")
        if weeks_since is not None and not np.isnan(float(weeks_since)):
            factor_2 *= pead_decay(float(weeks_since))

        # How many factors are positive (alignment)
        n_positive = (
            (1 if factor_1 > 0 else 0)
            + (1 if factor_2 > 0 else 0)
            + (1 if factor_3 > 0 else 0)
        )
        alignment_multiplier = {0: 0.5, 1: 1.0, 2: 1.5, 3: 2.0}[n_positive]

        # Composite alpha
        base_alpha = 0.4 * factor_1 + 0.4 * factor_2 + 0.2 * factor_3
        final_alpha = base_alpha * alignment_multiplier

        # Conviction label
        conviction = "NONE"
        for threshold in sorted(CONVICTION_LABELS, reverse=True):
            if final_alpha > threshold:
                conviction = CONVICTION_LABELS[threshold]
                break

        # Kelly sizing (4B) — placeholder hit rates; real values come from paper trading
        # Default: momentum p=0.55 b=1.3, PEAD p=0.65 b=1.5, squeeze p=0.60 b=1.8
        k1 = kelly_factor_size(0.55, 1.3) * max(0.0, factor_1)
        k2 = kelly_factor_size(0.65, 1.5) * factor_2
        k3 = kelly_factor_size(0.60, 1.8) * factor_3
        kelly_size = min(0.25, k1 * 0.4 + k2 * 0.4 + k3 * 0.2)

        # Blend with model prob_2pct
        prob_2pct = features.get("prob_2pct")
        if prob_2pct is not None and not np.isnan(float(prob_2pct)):
            # Normalize final_alpha from [-1, 2] range to [0, 1]
            alpha_norm = float(np.clip((final_alpha + 1) / 3.0, 0.0, 1.0))
            adjusted_prob = 0.6 * float(prob_2pct) + 0.4 * alpha_norm
        else:
            adjusted_prob = None

        return {
            "alpha_factor_1": round(factor_1, 4),
            "alpha_factor_2": round(factor_2, 4),
            "alpha_factor_3": round(factor_3, 4),
            "alpha_alignment": n_positive,
            "final_alpha_score": round(final_alpha, 4),
            "conviction_label": conviction,
            "kelly_size": round(kelly_size, 4),
            "adjusted_prob_2pct": round(adjusted_prob, 4) if adjusted_prob is not None else None,
        }

    def compute_features_only(self, features: dict) -> dict:
        """Return only the ALPHA_COMBO_FEATURES subset (for storage in feature_weekly)."""
        result = self.compute(features)
        return {k: result[k] for k in ALPHA_COMBO_FEATURES if k in result}
