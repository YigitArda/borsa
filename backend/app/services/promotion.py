"""Promotion gate for moving research candidates into production signal status."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.models.backtest import WalkForwardResult
from app.models.strategy import ModelPromotion, Strategy
from app.services.paper_trading import PaperTradingService


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
    except Exception:
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
        }
        if reasons:
            summary["reason"] = "; ".join(reasons)
            return False, summary
        return True, summary

    def promote(self, strategy_id: int) -> tuple[bool, dict]:
        passed, summary = self.evaluate(strategy_id)
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
            outperforms_spy=str(summary.get("outperforms_spy")),
            avg_win_rate=summary.get("avg_win_rate"),
            total_trades=summary.get("total_trades"),
            min_drawdown=summary.get("min_drawdown"),
            avg_profit_factor=summary.get("avg_profit_factor"),
            concentration_ok=str((summary.get("concentration") or {}).get("ok", False)),
            details=summary,
        )
        self.session.add(promotion)
        self.session.commit()
        return True, summary
