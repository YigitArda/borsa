"""
Kill Switch engine — monitors system health and blocks dangerous operations.

When a kill switch is active:
  - New predictions are blocked
  - Dashboard shows a warning
  - Notifications are sent (logged for now)
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.kill_switch import KillSwitchConfig, KillSwitchEvent
from app.models.data_quality_score import DataQualityScore
from app.models.feature import FeatureWeekly
from app.models.macro import MacroIndicator
from app.models.prediction import PaperTrade, WeeklyPrediction
from app.models.strategy import Strategy

logger = logging.getLogger(__name__)


class KillSwitchMonitor:
    """Runs all kill-switch checks and manages event lifecycle."""

    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------
    def _get_config(self) -> KillSwitchConfig:
        """Return the first (and expected only) config row, creating defaults if missing."""
        config = self.session.execute(
            select(KillSwitchConfig).order_by(KillSwitchConfig.id)
        ).scalars().first()
        if config is None:
            config = KillSwitchConfig()
            self.session.add(config)
            self.session.commit()
            self.session.refresh(config)
        return config

    def _is_enabled(self) -> bool:
        cfg = self._get_config()
        return str(cfg.enabled).lower() in ("true", "1", "yes", "on")

    # ------------------------------------------------------------------
    # Core checks
    # ------------------------------------------------------------------
    def check_all(self) -> list[KillSwitchEvent]:
        """Run every kill-switch check and return any newly triggered events."""
        if not self._is_enabled():
            return []

        triggered: list[KillSwitchEvent] = []

        # Strategy-agnostic checks
        triggered.extend(self.check_data_quality())
        triggered.extend(self.check_vix_spike())
        triggered.extend(self.check_prediction_count())
        triggered.extend(self.check_feature_drift())

        # Strategy-specific checks for all promoted strategies
        strategies = self.session.execute(
            select(Strategy).where(Strategy.status == "promoted")
        ).scalars().all()
        for s in strategies:
            triggered.extend(self.check_paper_trading_performance(s.id))
            triggered.extend(self.check_model_drawdown(s.id))
            triggered.extend(self.check_confidence_distribution(s.id))

        return triggered

    def check_paper_trading_performance(
        self, strategy_id: int
    ) -> list[KillSwitchEvent]:
        """Check if paper trading drawdown over last N weeks exceeds limit."""
        cfg = self._get_config()
        max_weeks = cfg.max_paper_drawdown_weeks
        max_pct = cfg.max_paper_drawdown_pct

        cutoff = date.today() - timedelta(weeks=max_weeks)
        trades = self.session.execute(
            select(PaperTrade)
            .where(
                PaperTrade.strategy_id == strategy_id,
                PaperTrade.status == "closed",
                PaperTrade.week_starting >= cutoff,
                PaperTrade.realized_return.isnot(None),
            )
            .order_by(PaperTrade.week_starting)
        ).scalars().all()

        if not trades:
            return []

        returns = [t.realized_return for t in trades if t.realized_return is not None]
        if not returns:
            return []

        # Group by week_starting and compute portfolio-level weekly returns (equal weight).
        # Chaining individual position returns would overstate drawdown when top_n > 1.
        from collections import defaultdict
        weekly_buckets: dict = defaultdict(list)
        for t in trades:
            weekly_buckets[t.week_starting].append(t.realized_return)
        portfolio_returns = [
            sum(rs) / len(rs)
            for rs in (weekly_buckets[w] for w in sorted(weekly_buckets))
        ]

        equity = 1.0
        peak = equity
        max_dd = 0.0
        for r in portfolio_returns:
            equity *= (1 + r)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd

        if max_dd >= max_pct:
            event = self.trigger_kill_switch(
                trigger_type="paper_poor",
                strategy_id=strategy_id,
                severity="critical",
                reason=f"Paper trading drawdown {max_dd:.2%} over last {max_weeks} weeks exceeds {max_pct:.2%}",
                details={
                    "max_drawdown": round(max_dd, 4),
                    "lookback_weeks": max_weeks,
                    "trade_count": len(trades),
                    "avg_return": round(mean(returns), 4) if returns else None,
                },
            )
            return [event] if event else []
        return []

    def check_model_drawdown(self, strategy_id: int) -> list[KillSwitchEvent]:
        """Check if the promoted model's backtest drawdown exceeds limit."""
        from app.models.backtest import WalkForwardResult

        cfg = self._get_config()
        max_pct = cfg.max_model_drawdown_pct

        folds = self.session.execute(
            select(WalkForwardResult)
            .where(WalkForwardResult.strategy_id == strategy_id)
            .order_by(WalkForwardResult.fold)
        ).scalars().all()

        if not folds:
            return []

        # max_drawdown stored as negative float (e.g. -0.15); take abs for comparison.
        max_dd = 0.0
        for fold in folds:
            metrics = fold.metrics or {}
            fold_dd = metrics.get("max_drawdown")
            if fold_dd is not None and abs(fold_dd) > max_dd:
                max_dd = abs(fold_dd)

        if max_dd >= max_pct:
            event = self.trigger_kill_switch(
                trigger_type="drawdown",
                strategy_id=strategy_id,
                severity="critical",
                reason=f"Model max drawdown {max_dd:.2%} exceeds limit {max_pct:.2%}",
                details={
                    "max_drawdown": round(max_dd, 4),
                    "limit": max_pct,
                    "fold_count": len(folds),
                },
            )
            return [event] if event else []
        return []

    def check_data_quality(self) -> list[KillSwitchEvent]:
        """Check overall data quality score across active stocks."""
        cfg = self._get_config()
        min_score = cfg.min_data_quality_score

        latest_week = self.session.execute(
            select(func.max(DataQualityScore.week_ending))
        ).scalar_one_or_none()
        if latest_week is None:
            return []

        scores = self.session.execute(
            select(DataQualityScore.overall_score)
            .where(DataQualityScore.week_ending == latest_week)
        ).scalars().all()

        if not scores:
            return []

        avg_score = mean(scores)
        if avg_score < min_score:
            event = self.trigger_kill_switch(
                trigger_type="data_quality",
                severity="warning",
                reason=f"Average data quality score {avg_score:.1f} below threshold {min_score:.1f}",
                details={
                    "avg_score": round(avg_score, 2),
                    "threshold": min_score,
                    "stocks_checked": len(scores),
                    "week_ending": str(latest_week),
                },
            )
            return [event] if event else []
        return []

    def check_vix_spike(self) -> list[KillSwitchEvent]:
        """Check if VIX exceeds configured threshold."""
        cfg = self._get_config()
        max_vix = cfg.max_vix_level

        latest = self.session.execute(
            select(MacroIndicator)
            .where(MacroIndicator.indicator_code == "VIX")
            .order_by(MacroIndicator.date.desc())
            .limit(1)
        ).scalar_one_or_none()

        if latest is None or latest.value is None:
            return []

        if latest.value >= max_vix:
            event = self.trigger_kill_switch(
                trigger_type="vix_spike",
                severity="warning",
                reason=f"VIX {latest.value:.2f} exceeds threshold {max_vix:.2f}",
                details={
                    "vix_value": round(latest.value, 2),
                    "threshold": max_vix,
                    "date": str(latest.date),
                },
            )
            return [event] if event else []
        return []

    def check_confidence_distribution(self, strategy_id: int) -> list[KillSwitchEvent]:
        """Detect abnormal shifts in prediction confidence distribution."""
        cfg = self._get_config()
        threshold = cfg.confidence_distribution_threshold

        # Get last 2 weeks of predictions
        two_weeks_ago = date.today() - timedelta(weeks=2)
        preds = self.session.execute(
            select(WeeklyPrediction.confidence)
            .where(
                WeeklyPrediction.strategy_id == strategy_id,
                WeeklyPrediction.week_starting >= two_weeks_ago,
                WeeklyPrediction.confidence.isnot(None),
            )
        ).scalars().all()

        if len(preds) < 20:
            return []

        # Compare low-confidence ratio to historical baseline (~20%)
        low_count = sum(1 for c in preds if c == "low")
        low_ratio = low_count / len(preds)

        if abs(low_ratio - 0.20) > threshold:
            event = self.trigger_kill_switch(
                trigger_type="confidence_anomaly",
                strategy_id=strategy_id,
                severity="warning",
                reason=f"Low-confidence prediction ratio {low_ratio:.2%} deviates >{threshold:.0%} from baseline",
                details={
                    "low_ratio": round(low_ratio, 4),
                    "baseline": 0.20,
                    "threshold": threshold,
                    "sample_size": len(preds),
                },
            )
            return [event] if event else []
        return []

    def check_prediction_count(self) -> list[KillSwitchEvent]:
        """Check if actual predictions generated meets expected minimum."""
        cfg = self._get_config()
        min_preds = cfg.min_predictions_per_week

        latest_week = self.session.execute(
            select(func.max(WeeklyPrediction.week_starting))
        ).scalar_one_or_none()
        if latest_week is None:
            return []

        count = self.session.execute(
            select(func.count())
            .where(WeeklyPrediction.week_starting == latest_week)
        ).scalar() or 0

        if count < min_preds:
            event = self.trigger_kill_switch(
                trigger_type="prediction_count",
                severity="warning",
                reason=f"Only {count} predictions generated for {latest_week}, expected >= {min_preds}",
                details={
                    "actual_count": count,
                    "expected_count": min_preds,
                    "week_starting": str(latest_week),
                },
            )
            return [event] if event else []
        return []

    def check_feature_drift(self) -> list[KillSwitchEvent]:
        """Check if feature distributions have drifted significantly."""
        cfg = self._get_config()
        max_drift = cfg.max_feature_drift_pct

        now = date.today()
        cutoff_recent = now - timedelta(days=30)
        cutoff_old = now - timedelta(days=60)

        drift_features = ["rsi_14", "volume_zscore", "return_1w", "VIX", "macd"]
        issues = []

        for fname in drift_features:
            recent_q = self.session.execute(
                select(func.avg(FeatureWeekly.value))
                .where(
                    FeatureWeekly.feature_name == fname,
                    FeatureWeekly.week_ending >= cutoff_recent,
                )
            ).scalar()
            old_q = self.session.execute(
                select(func.avg(FeatureWeekly.value))
                .where(
                    FeatureWeekly.feature_name == fname,
                    FeatureWeekly.week_ending >= cutoff_old,
                    FeatureWeekly.week_ending < cutoff_recent,
                )
            ).scalar()

            if recent_q is None or old_q is None or old_q == 0:
                continue
            pct_change = abs(recent_q - old_q) / abs(old_q)
            if pct_change > max_drift:
                issues.append({
                    "feature": fname,
                    "pct_change": round(pct_change, 4),
                    "recent_avg": round(recent_q, 4),
                    "old_avg": round(old_q, 4),
                })

        if issues:
            event = self.trigger_kill_switch(
                trigger_type="feature_drift",
                severity="warning",
                reason=f"Feature drift detected: {len(issues)} features shifted >{max_drift:.0%}",
                details={
                    "drifted_features": issues,
                    "threshold": max_drift,
                    "lookback_days": 30,
                },
            )
            return [event] if event else []
        return []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def trigger_kill_switch(
        self,
        trigger_type: str,
        reason: str,
        details: dict[str, Any] | None = None,
        strategy_id: int | None = None,
        severity: str = "warning",
    ) -> KillSwitchEvent | None:
        """Create a kill-switch event if one of the same type is not already active."""
        existing = self.session.execute(
            select(KillSwitchEvent)
            .where(
                KillSwitchEvent.trigger_type == trigger_type,
                KillSwitchEvent.status == "active",
            )
        ).scalars().first()

        if existing:
            logger.info(
                "Kill switch %s already active (id=%s); skipping duplicate trigger",
                trigger_type,
                existing.id,
            )
            return None

        event = KillSwitchEvent(
            trigger_type=trigger_type,
            strategy_id=strategy_id,
            severity=severity,
            reason=reason,
            details=details or {},
            status="active",
        )
        self.session.add(event)
        self.session.commit()
        self.session.refresh(event)

        logger.warning(
            "KILL SWITCH TRIGGERED [%s] id=%s severity=%s: %s",
            trigger_type,
            event.id,
            severity,
            reason,
        )

        if severity == "critical":
            closed = self._close_open_positions(strategy_id)
            logger.warning(
                "Kill switch: %d açık paper trade kapatıldı (strategy_id=%s)",
                closed, strategy_id,
            )
            if closed > 0:
                event.details = {**(event.details or {}), "positions_closed": closed}
                self.session.commit()

        self._send_notification(event)
        return event

    def _close_open_positions(self, strategy_id: int | None = None) -> int:
        """Close open paper trades when a critical kill switch is triggered."""
        query = select(PaperTrade).where(
            PaperTrade.status.in_(["open", "pending_data"])
        )
        if strategy_id is not None:
            query = query.where(PaperTrade.strategy_id == strategy_id)

        open_trades = self.session.execute(query).scalars().all()
        closed_count = 0
        for trade in open_trades:
            trade.status = "kill_switch_closed"
            trade.exit_date = date.today()
            trade.evaluated_at = datetime.now(UTC).replace(tzinfo=None)
            trade.hit_2pct = False
            trade.hit_3pct = False
            trade.hit_loss_2pct = True
            closed_count += 1

        if closed_count > 0:
            self.session.commit()
        return closed_count

    def resolve_kill_switch(
        self, event_id: int, resolved_by: str
    ) -> KillSwitchEvent | None:
        """Mark a kill-switch event as resolved."""
        event = self.session.get(KillSwitchEvent, event_id)
        if event is None:
            return None
        event.status = "resolved"
        event.resolved_at = datetime.now(UTC).replace(tzinfo=None)
        event.resolved_by = resolved_by
        self.session.commit()
        logger.info("Kill switch event %s resolved by %s", event_id, resolved_by)
        return event

    def is_kill_switch_active(self) -> bool:
        """Return True if any active kill-switch event exists."""
        count = self.session.execute(
            select(func.count())
            .where(KillSwitchEvent.status == "active")
        ).scalar() or 0
        return count > 0

    def get_active_warnings(self) -> list[KillSwitchEvent]:
        """Return all active kill-switch events."""
        return self.session.execute(
            select(KillSwitchEvent)
            .where(KillSwitchEvent.status == "active")
            .order_by(KillSwitchEvent.triggered_at.desc())
        ).scalars().all()

    # ------------------------------------------------------------------
    # Notification stub
    # ------------------------------------------------------------------
    def _send_notification(self, event: KillSwitchEvent) -> None:
        """Placeholder for notification channel (email/Slack/PagerDuty)."""
        logger.warning(
            "[NOTIFICATION] Kill Switch %s (severity=%s): %s",
            event.trigger_type,
            event.severity,
            event.reason,
        )
