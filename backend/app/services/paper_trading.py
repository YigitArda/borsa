"""
Paper-trading forward test service.

The service snapshots weekly predictions into paper_trades and later marks
them closed once the planned exit week has enough price data. This is a
research-only audit trail for prediction quality, not a live trading bridge.
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from statistics import mean

from sqlalchemy import Float, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.prediction import PaperTrade, WeeklyPrediction
from app.models.price import PriceDaily
from app.models.backtest import WalkForwardResult
from app.models.strategy import Strategy
from app.services.meta_learner import MetaPromotionModel
from app.services.price_adjustments import adjusted_ohlc
from app.services.strategy_bandit import StrategyBandit

logger = logging.getLogger(__name__)


class PaperTradingService:
    def __init__(self, session: Session):
        self.session = session

    def open_from_predictions(
        self,
        week_starting: date | None = None,
        strategy_id: int | None = None,
        top_n: int | None = None,
    ) -> int:
        """Create open paper-trade rows from weekly predictions."""
        if week_starting is None:
            week_starting = self.session.execute(
                select(func.max(WeeklyPrediction.week_starting))
            ).scalar_one_or_none()
        if week_starting is None:
            return 0

        query = select(WeeklyPrediction).where(WeeklyPrediction.week_starting == week_starting)
        if strategy_id is not None:
            query = query.where(WeeklyPrediction.strategy_id == strategy_id)
        query = query.order_by(WeeklyPrediction.rank)
        if top_n is not None:
            query = query.limit(top_n)

        predictions = self.session.execute(query).scalars().all()
        if not predictions:
            return 0

        rows = []
        for pred in predictions:
            rows.append({
                "prediction_id": pred.id,
                "week_starting": pred.week_starting,
                "stock_id": pred.stock_id,
                "strategy_id": pred.strategy_id,
                "rank": pred.rank,
                "prob_2pct": pred.prob_2pct,
                "prob_loss_2pct": pred.prob_loss_2pct,
                "expected_return": pred.expected_return,
                "confidence": pred.confidence,
                "signal_summary": pred.signal_summary,
                "entry_date": None,
                "planned_exit_date": pred.week_starting + timedelta(days=4),
                "status": "open",
            })

        stmt = pg_insert(PaperTrade).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["prediction_id"],
            set_={
                "week_starting": stmt.excluded.week_starting,
                "stock_id": stmt.excluded.stock_id,
                "strategy_id": stmt.excluded.strategy_id,
                "rank": stmt.excluded.rank,
                "prob_2pct": stmt.excluded.prob_2pct,
                "prob_loss_2pct": stmt.excluded.prob_loss_2pct,
                "expected_return": stmt.excluded.expected_return,
                "confidence": stmt.excluded.confidence,
                "signal_summary": stmt.excluded.signal_summary,
                "planned_exit_date": stmt.excluded.planned_exit_date,
                "status": stmt.excluded.status,
            },
            where=PaperTrade.status != "closed",
        )
        result = self.session.execute(stmt)
        self.session.commit()
        affected = result.rowcount
        if affected is None or affected < 0:
            affected = len(rows)
        if affected == 0:
            logger.info("Paper trades already closed for week %s; no rows refreshed", week_starting)
        else:
            logger.info("Opened or refreshed %s paper trades for week %s", affected, week_starting)
        return affected

    def evaluate_open_positions(self, as_of: date | None = None) -> dict:
        """Close paper trades whose planned exit date has passed and prices exist."""
        as_of = as_of or date.today()
        open_rows = self.session.execute(
            select(PaperTrade)
            .where(PaperTrade.status.in_(["open", "pending_data"]))
            .order_by(PaperTrade.week_starting, PaperTrade.rank)
        ).scalars().all()

        evaluated = 0
        pending = 0
        bandit_outcomes: list[tuple[int, bool]] = []
        touched_strategy_ids: set[int] = set()

        for trade in open_rows:
            if as_of < trade.planned_exit_date:
                continue

            prices = self.session.execute(
                select(PriceDaily)
                .where(
                    PriceDaily.stock_id == trade.stock_id,
                    PriceDaily.date >= trade.week_starting,
                    PriceDaily.date <= trade.planned_exit_date,
                )
                .order_by(PriceDaily.date)
            ).scalars().all()

            if not prices:
                trade.status = "pending_data"
                pending += 1
                continue

            entry_row = prices[0]
            exit_row = prices[-1]
            if exit_row.date < trade.planned_exit_date - timedelta(days=3):
                trade.status = "pending_data"
                pending += 1
                continue

            entry_prices = adjusted_ohlc(
                entry_row.open, entry_row.high, entry_row.low, entry_row.close, entry_row.adj_close
            )
            exit_prices = adjusted_ohlc(
                exit_row.open, exit_row.high, exit_row.low, exit_row.close, exit_row.adj_close
            )
            entry_price = entry_prices["open"] or entry_prices["close"]
            exit_price = exit_prices["close"] or exit_prices["open"]
            if entry_price is None or exit_price is None or entry_price <= 0 or exit_price <= 0:
                trade.status = "pending_data"
                pending += 1
                continue

            adjusted_prices = [
                adjusted_ohlc(p.open, p.high, p.low, p.close, p.adj_close)
                for p in prices
            ]
            highs = [p["high"] for p in adjusted_prices if p["high"] is not None]
            lows = [p["low"] for p in adjusted_prices if p["low"] is not None]
            realized_return = (exit_price - entry_price) / entry_price

            trade.entry_date = entry_row.date
            trade.exit_date = exit_row.date
            trade.entry_price = float(entry_price)
            trade.exit_price = float(exit_price)
            trade.realized_return = float(realized_return)
            trade.max_rise_in_period = float(max(highs) / entry_price - 1) if highs else None
            trade.max_drawdown_in_period = float(min(lows) / entry_price - 1) if lows else None
            trade.hit_2pct = realized_return >= 0.02
            trade.hit_3pct = realized_return >= 0.03
            trade.hit_loss_2pct = realized_return <= -0.02
            trade.status = "closed"
            trade.evaluated_at = datetime.now(UTC).replace(tzinfo=None)
            evaluated += 1
            bandit_outcomes.append((trade.strategy_id, bool(trade.hit_2pct)))
            touched_strategy_ids.add(trade.strategy_id)

        self.session.commit()

        if bandit_outcomes:
            bandit = StrategyBandit(self.session)
            for strategy_id, hit in bandit_outcomes:
                try:
                    bandit.record_outcome(strategy_id, hit)
                except Exception as exc:
                    logger.warning("Bandit update failed for strategy %s: %s", strategy_id, exc)

        for strategy_id in touched_strategy_ids:
            self._record_meta_learner_outcome(strategy_id)

        summary = self.summary()
        summary.update({"evaluated_now": evaluated, "pending_now": pending})
        logger.info("Evaluated paper trades: %s closed, %s pending", evaluated, pending)
        return summary

    def _record_meta_learner_outcome(self, strategy_id: int) -> None:
        strategy = self.session.get(Strategy, strategy_id)
        if not strategy:
            return
        paper = self.summary(strategy_id=strategy_id)
        closed = paper.get("closed", 0)
        if closed == 0:
            return  # no closed trades yet — cannot determine outcome

        hit_rate = paper.get("hit_rate_2pct")
        calibration_error = paper.get("calibration_error_2pct")

        import json
        from app.config import settings

        notes = {}
        if strategy.notes:
            try:
                notes = json.loads(strategy.notes)
            except Exception as exc:
                logger.debug("Could not parse strategy notes JSON for strategy %s: %s", strategy_id, exc)
                notes = {}
        folds = self.session.execute(
            select(WalkForwardResult)
            .where(WalkForwardResult.strategy_id == strategy_id)
            .order_by(WalkForwardResult.fold)
        ).scalars().all()
        fold_metrics = [f.metrics for f in folds if f.metrics]

        is_successful = (
            hit_rate is not None
            and hit_rate >= settings.min_paper_hit_rate_2pct
            and calibration_error is not None
            and abs(calibration_error) <= settings.max_paper_calibration_error_2pct
        )
        label = 1 if is_successful else 0

        try:
            MetaPromotionModel(self.session).save_training_example(
                strategy_id=strategy_id,
                fold_metrics=fold_metrics,
                notes=notes,
                n_features=len((strategy.config or {}).get("features", [])),
                label=label,
                paper_hit_rate=float(hit_rate) if hit_rate is not None else None,
            )
        except Exception as exc:
            logger.warning("Meta learner outcome recording failed for strategy %s: %s", strategy_id, exc)

    def summary(self, week_starting: date | None = None, strategy_id: int | None = None) -> dict:
        """Return aggregated paper trade metrics using SQL aggregates (not Python loops)."""
        filters = []
        if week_starting is not None:
            filters.append(PaperTrade.week_starting == week_starting)
        if strategy_id is not None:
            filters.append(PaperTrade.strategy_id == strategy_id)

        # Status counts via SQL GROUP BY
        status_q = self.session.execute(
            select(PaperTrade.status, func.count().label("cnt"))
            .where(*filters)
            .group_by(PaperTrade.status)
        ).all()
        by_status = {row.status: row.cnt for row in status_q}
        total = sum(by_status.values())

        # Aggregate metrics for closed trades only
        closed_filters = [*filters, PaperTrade.status == "closed", PaperTrade.realized_return.is_not(None)]
        agg = self.session.execute(
            select(
                func.count().label("closed"),
                func.avg(PaperTrade.realized_return).label("avg_realized_return"),
                func.avg(PaperTrade.expected_return).label("avg_expected_return"),
                func.avg(PaperTrade.prob_2pct).label("avg_prob_2pct"),
                func.avg(func.cast(PaperTrade.hit_2pct, Float)).label("hit_rate_2pct"),
                func.avg(func.cast(PaperTrade.hit_3pct, Float)).label("hit_rate_3pct"),
                func.avg(func.cast(PaperTrade.hit_loss_2pct, Float)).label("loss_rate_2pct"),
            ).where(*closed_filters)
        ).one()

        closed_count = agg.closed or 0
        hit_rate = agg.hit_rate_2pct
        avg_prob = agg.avg_prob_2pct

        calibration_error = None
        if avg_prob is not None and hit_rate is not None:
            calibration_error = round(avg_prob - hit_rate, 4)

        # Brier score requires per-row data — only load if we have closed trades
        brier = None
        if closed_count > 0:
            brier_rows = self.session.execute(
                select(PaperTrade.prob_2pct, PaperTrade.hit_2pct)
                .where(*closed_filters, PaperTrade.prob_2pct.is_not(None), PaperTrade.hit_2pct.is_not(None))
            ).all()
            if brier_rows:
                brier = round(mean((r.prob_2pct - (1.0 if r.hit_2pct else 0.0)) ** 2 for r in brier_rows), 4)

        def _r(v):
            return round(float(v), 4) if v is not None else None

        return {
            "total": total,
            "open": by_status.get("open", 0),
            "pending_data": by_status.get("pending_data", 0),
            "closed": closed_count,
            "kill_switch_closed": by_status.get("kill_switch_closed", 0),
            "hit_rate_2pct": _r(hit_rate),
            "hit_rate_3pct": _r(agg.hit_rate_3pct),
            "loss_rate_2pct": _r(agg.loss_rate_2pct),
            "avg_prob_2pct": _r(avg_prob),
            "calibration_error_2pct": calibration_error,
            "brier_score_2pct": brier,
            "avg_expected_return": _r(agg.avg_expected_return),
            "avg_realized_return": _r(agg.avg_realized_return),
        }
