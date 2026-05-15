"""
Probability calibration analysis service.

Provides tools to evaluate how well predicted probabilities match observed
frequencies, and to adjust future confidence levels based on historical
calibration data.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from statistics import mean
from typing import Sequence

import numpy as np
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.calibration import ProbabilityCalibration
from app.models.prediction import WeeklyPrediction, PaperTrade

logger = logging.getLogger(__name__)


def _has_sklearn() -> bool:
    try:
        import sklearn.calibration  # noqa: F401
        return True
    except Exception:
        return False


class CalibrationAnalyzer:
    """Analyze and adjust probability calibration for a strategy."""

    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------ #
    # Core metrics
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_brier_score(predictions: Sequence[float], actuals: Sequence[float]) -> float | None:
        """Return the Brier score (mean squared error of probabilities).

        Lower is better; 0 is perfect, 0.25 is random for binary outcomes.
        """
        if not predictions or len(predictions) != len(actuals):
            return None
        return float(mean((p - a) ** 2 for p, a in zip(predictions, actuals)))

    @staticmethod
    def compute_calibration_curve(
        predictions: Sequence[float],
        actuals: Sequence[float],
        n_buckets: int = 10,
    ) -> list[dict]:
        """Bucket predictions into equal-width bins and compare with actual hit rates.

        Returns a list of bucket dicts with keys:
            bucket, predicted_avg, actual_rate, count
        """
        if not predictions or len(predictions) != len(actuals):
            return []

        preds = np.asarray(predictions, dtype=float)
        acts = np.asarray(actuals, dtype=float)

        # Equal-width bins in [0, 1]
        bin_edges = np.linspace(0.0, 1.0, n_buckets + 1)
        buckets = []
        for i in range(n_buckets):
            lo, hi = bin_edges[i], bin_edges[i + 1]
            if i == n_buckets - 1:
                mask = (preds >= lo) & (preds <= hi)
            else:
                mask = (preds >= lo) & (preds < hi)

            count = int(mask.sum())
            if count == 0:
                buckets.append({
                    "bucket": f"{lo:.2f}-{hi:.2f}",
                    "predicted_avg": None,
                    "actual_rate": None,
                    "count": 0,
                })
                continue

            pred_avg = float(preds[mask].mean())
            actual_rate = float(acts[mask].mean())
            buckets.append({
                "bucket": f"{lo:.2f}-{hi:.2f}",
                "predicted_avg": round(pred_avg, 4),
                "actual_rate": round(actual_rate, 4),
                "count": count,
            })

        return buckets

    @staticmethod
    def compute_reliability_diagram(
        predictions: Sequence[float],
        actuals: Sequence[float],
        n_buckets: int = 10,
    ) -> dict:
        """Return structured data for a reliability diagram.

        Output keys:
            prob_pred  – mean predicted probability per bin
            prob_true  – observed frequency per bin
            counts     – number of samples per bin
            bin_edges  – edges used for binning
        """
        if not predictions or len(predictions) != len(actuals):
            return {"prob_pred": [], "prob_true": [], "counts": [], "bin_edges": []}

        preds = np.asarray(predictions, dtype=float)
        acts = np.asarray(actuals, dtype=float)
        bin_edges = np.linspace(0.0, 1.0, n_buckets + 1)

        prob_pred = []
        prob_true = []
        counts = []

        for i in range(n_buckets):
            lo, hi = bin_edges[i], bin_edges[i + 1]
            if i == n_buckets - 1:
                mask = (preds >= lo) & (preds <= hi)
            else:
                mask = (preds >= lo) & (preds < hi)

            cnt = int(mask.sum())
            counts.append(cnt)
            if cnt > 0:
                prob_pred.append(round(float(preds[mask].mean()), 4))
                prob_true.append(round(float(acts[mask].mean()), 4))
            else:
                prob_pred.append(None)
                prob_true.append(None)

        return {
            "prob_pred": prob_pred,
            "prob_true": prob_true,
            "counts": counts,
            "bin_edges": [round(float(e), 4) for e in bin_edges],
        }

    # ------------------------------------------------------------------ #
    # Strategy-level analysis
    # ------------------------------------------------------------------ #

    def analyze_strategy(
        self,
        strategy_id: int,
        weeks_lookback: int = 52,
        n_buckets: int = 10,
    ) -> dict | None:
        """Analyze historical predictions for a strategy using closed paper trades.

        Returns a dict with brier_score, calibration_error, prob_buckets,
        reliability_data, and sample_count.  If insufficient data, returns None.
        """
        cutoff = date.today() - timedelta(weeks=weeks_lookback)

        rows = self.session.execute(
            select(PaperTrade)
            .where(
                PaperTrade.strategy_id == strategy_id,
                PaperTrade.status == "closed",
                PaperTrade.week_starting >= cutoff,
                PaperTrade.prob_2pct is not None,
                PaperTrade.hit_2pct is not None,
            )
            .order_by(PaperTrade.week_starting)
        ).scalars().all()

        if len(rows) < 20:
            logger.warning(
                "Insufficient closed paper trades for strategy %s (found %s, need 20+)",
                strategy_id,
                len(rows),
            )
            return None

        predictions = [r.prob_2pct for r in rows]
        actuals = [1.0 if r.hit_2pct else 0.0 for r in rows]

        brier = self.compute_brier_score(predictions, actuals)
        buckets = self.compute_calibration_curve(predictions, actuals, n_buckets=n_buckets)
        reliability = self.compute_reliability_diagram(predictions, actuals, n_buckets=n_buckets)

        # Calibration error = mean absolute difference between predicted and actual
        # across non-empty buckets
        cal_errors = [
            abs(b["predicted_avg"] - b["actual_rate"])
            for b in buckets
            if b["predicted_avg"] is not None and b["actual_rate"] is not None
        ]
        calibration_error = float(mean(cal_errors)) if cal_errors else None

        # Use sklearn calibration_curve if available for a cross-check
        if _has_sklearn():
            try:
                from sklearn.calibration import calibration_curve
                sk_prob_true, sk_prob_pred = calibration_curve(
                    actuals, predictions, n_bins=n_buckets, strategy="uniform"
                )
                reliability["sklearn_prob_true"] = [round(float(v), 4) for v in sk_prob_true]
                reliability["sklearn_prob_pred"] = [round(float(v), 4) for v in sk_prob_pred]
            except Exception as exc:
                logger.debug("sklearn calibration_curve failed: %s", exc)

        return {
            "strategy_id": strategy_id,
            "week_starting": rows[-1].week_starting,
            "brier_score": round(brier, 6) if brier is not None else None,
            "calibration_error": round(calibration_error, 6) if calibration_error is not None else None,
            "prob_buckets": buckets,
            "reliability_data": reliability,
            "sample_count": len(rows),
        }

    def save_analysis(self, analysis: dict) -> ProbabilityCalibration:
        """Persist calibration analysis to the database."""
        cal = ProbabilityCalibration(
            strategy_id=analysis["strategy_id"],
            week_starting=analysis["week_starting"],
            brier_score=analysis.get("brier_score"),
            calibration_error=analysis.get("calibration_error"),
            prob_buckets=analysis.get("prob_buckets"),
            reliability_data=analysis.get("reliability_data"),
        )
        self.session.add(cal)
        self.session.commit()
        return cal

    # ------------------------------------------------------------------ #
    # Confidence adjustment
    # ------------------------------------------------------------------ #

    @staticmethod
    def adjust_confidence(
        prob_2pct: float,
        calibration_data: dict | ProbabilityCalibration | None,
    ) -> tuple[str, float]:
        """Return adjusted (confidence_label, calibrated_probability).

        Uses the most recent calibration bucket data to map the raw predicted
        probability to the observed actual rate for that bucket.  If no
        calibration data is available, falls back to the original threshold
        logic (high >= 0.65, medium >= 0.5).
        """
        if calibration_data is None:
            confidence = "high" if prob_2pct >= 0.65 else "medium" if prob_2pct >= 0.5 else "low"
            return confidence, prob_2pct

        # Extract buckets from either a dict or the ORM object
        if isinstance(calibration_data, ProbabilityCalibration):
            buckets = calibration_data.prob_buckets or []
        else:
            buckets = calibration_data.get("prob_buckets") or []

        if not buckets:
            confidence = "high" if prob_2pct >= 0.65 else "medium" if prob_2pct >= 0.5 else "low"
            return confidence, prob_2pct

        # Find the bucket that contains prob_2pct
        for b in buckets:
            bucket_label = b["bucket"]
            try:
                lo_str, hi_str = bucket_label.split("-")
                lo, hi = float(lo_str), float(hi_str)
            except (ValueError, KeyError):
                continue

            if lo <= prob_2pct < hi or (prob_2pct == hi == 1.0):
                actual_rate = b.get("actual_rate")
                if actual_rate is not None:
                    calibrated_prob = float(actual_rate)
                    confidence = (
                        "high" if calibrated_prob >= 0.65
                        else "medium" if calibrated_prob >= 0.5
                        else "low"
                    )
                    return confidence, round(calibrated_prob, 4)
                break

        # Fallback if bucket not found or empty
        confidence = "high" if prob_2pct >= 0.65 else "medium" if prob_2pct >= 0.5 else "low"
        return confidence, prob_2pct

    def get_latest_calibration(self, strategy_id: int) -> ProbabilityCalibration | None:
        """Return the most recent calibration record for a strategy."""
        return self.session.execute(
            select(ProbabilityCalibration)
            .where(ProbabilityCalibration.strategy_id == strategy_id)
            .order_by(ProbabilityCalibration.week_starting.desc())
            .limit(1)
        ).scalars().first()
