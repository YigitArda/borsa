"""Promotion gate for moving research candidates into production signal status."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.models.backtest import WalkForwardResult
from app.models.strategy import ModelPromotion, Strategy
from app.models.regime import MarketRegime
from app.services.meta_learner import MetaPromotionModel
from app.services.paper_trading import PaperTradingService
from app.services.regime_detection import RegimeDetector


class ResearchMetricGate:
    def evaluate(self, fold_metrics: list[dict]) -> tuple[bool, dict]:
        if not fold_metrics:
            return False, {"reason": "no folds"}

        avg_sharpe = sum(m.get("sharpe", 0) for m in fold_metrics) / len(fold_metrics)
        avg_win_rate = sum(m.get("win_rate", 0) for m in fold_metrics) / len(fold_metrics)
        total_trades = sum(m.get("n_trades", 0) for m in fold_metrics)
        min_drawdown = min(m.get("max_drawdown", 0) for m in fold_metrics)
        avg_pf = sum(m.get("profit_factor", 0) for m in fold_metrics) / len(fold_metrics)

        summary = {
            "avg_sharpe": round(avg_sharpe, 4),
            "avg_win_rate": round(avg_win_rate, 4),
            "total_trades": total_trades,
            "min_drawdown": round(min_drawdown, 4),
            "avg_profit_factor": round(avg_pf, 4),
        }
        reasons = []
        if avg_sharpe < 0.5:
            reasons.append("avg_sharpe < 0.5")
        if avg_win_rate < 0.45:
            reasons.append("avg_win_rate < 0.45")
        if total_trades < settings.min_trades_for_promotion:
            reasons.append(f"total_trades < {settings.min_trades_for_promotion}")
        if min_drawdown < -0.25:
            reasons.append("max_drawdown < -25%")
        if avg_pf < 1.1:
            reasons.append("avg_profit_factor < 1.1")
        if reasons:
            summary["reason"] = "; ".join(reasons)
            return False, summary
        return True, summary


def _parse_notes(notes: str | None) -> dict:
    if not notes:
        return {}
    try:
        return json.loads(notes)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).debug("Could not parse strategy notes JSON: %s", exc)
        return {}


class PromotionGate:
    def __init__(self, session: Session):
        self.session = session
        self.research_gate = ResearchMetricGate()

    def evaluate(self, strategy_id: int) -> tuple[bool, dict]:
        strategy = self.session.get(Strategy, strategy_id)
        if not strategy:
            return False, {"reason": "strategy not found"}

        folds = self.session.query(WalkForwardResult).filter(
            WalkForwardResult.strategy_id == strategy_id
        ).order_by(WalkForwardResult.fold).all()
        fold_metrics = [f.metrics for f in folds if f.metrics]
        research_passed, research_summary = self.research_gate.evaluate(fold_metrics)

        notes = _parse_notes(strategy.notes)
        paper_summary = PaperTradingService(self.session).summary(strategy_id=strategy_id)

        reasons = []
        if not research_passed:
            reasons.append(research_summary.get("reason", "research gate failed"))

        if notes.get("deflated_sharpe", 0) <= 0:
            reasons.append("deflated_sharpe <= 0")
        if notes.get("permutation_pvalue", 1) > 0.1:
            reasons.append("permutation_pvalue > 0.10")
        if notes.get("outperforms_spy") is False:
            reasons.append("does not outperform SPY")
        concentration = notes.get("concentration") or {}
        if concentration and not concentration.get("ok", False):
            reasons.append("trade concentration check failed")

        closed_paper = paper_summary.get("closed", 0)
        hit_rate = paper_summary.get("hit_rate_2pct")
        calibration_error = paper_summary.get("calibration_error_2pct")
        if closed_paper < settings.min_paper_trades_for_promotion:
            reasons.append(f"paper closed trades {closed_paper} < {settings.min_paper_trades_for_promotion}")
        if hit_rate is None or hit_rate < settings.min_paper_hit_rate_2pct:
            reasons.append(f"paper hit_rate_2pct {hit_rate} < {settings.min_paper_hit_rate_2pct}")
        if calibration_error is None or abs(calibration_error) > settings.max_paper_calibration_error_2pct:
            reasons.append(
                f"paper calibration_error_2pct {calibration_error} > {settings.max_paper_calibration_error_2pct}"
            )

        # Regime-based performance check
        regime_summary = self._check_regime_performance(strategy_id)
        if regime_summary.get("weak_regimes"):
            reasons.append(
                f"underperforms in regimes: {', '.join(regime_summary['weak_regimes'])}"
            )
        if regime_summary.get("insufficient_regimes"):
            reasons.append(
                f"insufficient regime coverage: {', '.join(regime_summary['insufficient_regimes'])}"
            )

        meta_passed, meta_confidence, meta_reason = MetaPromotionModel(self.session).predict(
            fold_metrics=fold_metrics,
            notes=notes,
            n_features=len((strategy.config or {}).get("features", [])),
        )
        if not meta_passed:
            reasons.append(meta_reason)

        # HOLDOUT VALIDATION — gerçek OOS performans kontrolü
        from app.services.model_training import HoldoutValidator
        holdout_result = {}
        holdout_sharpe = None
        try:
            validator = HoldoutValidator(self.session, getattr(settings, "holdout_months", 18))
            holdout_result = validator.evaluate_on_holdout(
                strategy_id, settings.mvp_tickers
            )
            if "error" in holdout_result:
                reasons.append(f"holdout validation failed: {holdout_result['error']}")
            holdout_sharpe = (
                holdout_result.get("holdout_metrics", {}).get("sharpe")
                if "error" not in holdout_result
                else None
            )
            if holdout_sharpe is not None and holdout_sharpe < 0.3:
                reasons.append(
                    f"holdout Sharpe {holdout_sharpe:.2f} < 0.3 (gerçek OOS performans yetersiz)"
                )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Holdout validation failed: %s", exc)
            reasons.append(f"holdout validation failed: {exc}")
            holdout_result = {"error": str(exc)}

        summary = {
            **research_summary,
            "deflated_sharpe": notes.get("deflated_sharpe"),
            "probabilistic_sr": notes.get("probabilistic_sr"),
            "permutation_pvalue": notes.get("permutation_pvalue"),
            "spy_sharpe": notes.get("spy_sharpe"),
            "outperforms_spy": notes.get("outperforms_spy"),
            "benchmark_alpha": notes.get("benchmark_alpha"),
            "concentration": concentration,
            "paper": paper_summary,
            "regime_analysis": regime_summary,
            "meta_learner": {
                "passed": meta_passed,
                "confidence": round(meta_confidence, 4),
                "reason": meta_reason,
            },
            "holdout_validation": holdout_result,
            "holdout_sharpe": holdout_sharpe,
        }
        if reasons:
            summary["reason"] = "; ".join(reasons)
            return False, summary
        return True, summary

    def _check_regime_performance(self, strategy_id: int) -> dict:
        """Check strategy performance across market regimes.

        Flags regimes where avg_sharpe < 0.2 as weak.
        Returns dict with per-regime Sharpe and list of weak regimes.
        """
        detector = RegimeDetector(self.session)
        analysis = detector.analyze_strategy_by_regime(strategy_id)
        regimes = analysis.get("regimes", {})
        if not regimes:
            return {"per_regime": {}, "weak_regimes": []}

        per_regime = {}
        weak = []
        insufficient = []
        for regime, data in regimes.items():
            avg_sharpe = data.get("avg_sharpe")
            n_folds = data.get("n_folds", 0)
            per_regime[regime] = {
                "avg_sharpe": avg_sharpe,
                "n_folds": n_folds,
            }
            if avg_sharpe is not None and avg_sharpe < 0.2:
                weak.append(regime)
        for required in ("bull", "bear", "sideways"):
            if required in per_regime and per_regime[required].get("n_folds", 0) < 5:
                insufficient.append(required)
        return {"per_regime": per_regime, "weak_regimes": weak, "insufficient_regimes": insufficient}

    def promote(self, strategy_id: int) -> tuple[bool, dict]:
        passed, summary = self.evaluate(strategy_id)

        # Record outcome in meta-learner regardless of pass/fail so training data
        # includes both successes and failures (prevents asymmetric training).
        try:
            strategy_for_ml = self.session.get(Strategy, strategy_id)
            if strategy_for_ml:
                folds = self.session.query(WalkForwardResult).filter(
                    WalkForwardResult.strategy_id == strategy_id
                ).order_by(WalkForwardResult.fold).all()
                fold_metrics = [f.metrics for f in folds if f.metrics]
                notes = _parse_notes(strategy_for_ml.notes)
                paper_hit_rate = summary.get("paper", {}).get("hit_rate_2pct")
                MetaPromotionModel(self.session).save_training_example(
                    strategy_id=strategy_id,
                    fold_metrics=fold_metrics,
                    notes=notes,
                    n_features=len((strategy_for_ml.config or {}).get("features", [])),
                    label=1 if passed else 0,
                    paper_hit_rate=paper_hit_rate,
                )
        except Exception as exc:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "Meta-learner training example save failed for strategy %d: %s", strategy_id, exc
            )

        if not passed:
            return False, summary

        strategy = self.session.get(Strategy, strategy_id)
        strategy.status = "promoted"
        strategy.promoted_at = datetime.utcnow()
        promotion = ModelPromotion(
            strategy_id=strategy_id,
            avg_sharpe=summary.get("avg_sharpe"),
            deflated_sharpe=summary.get("deflated_sharpe"),
            probabilistic_sr=summary.get("probabilistic_sr"),
            permutation_pvalue=summary.get("permutation_pvalue"),
            spy_sharpe=summary.get("spy_sharpe"),
            outperforms_spy=bool(summary.get("outperforms_spy")),
            avg_win_rate=summary.get("avg_win_rate"),
            total_trades=summary.get("total_trades"),
            min_drawdown=summary.get("min_drawdown"),
            avg_profit_factor=summary.get("avg_profit_factor"),
            concentration_ok=bool((summary.get("concentration") or {}).get("ok", False)),
            details=summary,
        )
        self.session.add(promotion)
        self.session.commit()
        return True, summary
