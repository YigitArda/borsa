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

from sqlalchemy import func, select
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
        stmt = stmt.on_conflict_do_nothing(index_elements=["prediction_id"])
        result = self.session.execute(stmt)
        self.session.commit()
        inserted = result.rowcount or 0
        logger.info("Opened %s paper trades for week %s", inserted, week_starting)
        return inserted

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
            if not entry_price or not exit_price:
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
        hit_rate = paper.get("hit_rate_2pct")
        if hit_rate is None:
            return

        import json

        notes = {}
        if strategy.notes:
            try:
                notes = json.loads(strategy.notes)
            except Exception:
                notes = {}
        folds = self.session.execute(
            select(WalkForwardResult)
            .where(WalkForwardResult.strategy_id == strategy_id)
            .order_by(WalkForwardResult.fold)
        ).scalars().all()
        fold_metrics = [f.metrics for f in folds if f.metrics]
        try:
            MetaPromotionModel(self.session).record_outcome(
                strategy_id=strategy_id,
                fold_metrics=fold_metrics,
                notes=notes,
                n_features=len((strategy.config or {}).get("features", [])),
                paper_hit_rate=float(hit_rate),
            )
        except Exception as exc:
            logger.warning("Meta learner outcome recording failed for strategy %s: %s", strategy_id, exc)

    def summary(self, week_starting: date | None = None, strategy_id: int | None = None) -> dict:
        query = select(PaperTrade)
        if week_starting is not None:
            query = query.where(PaperTrade.week_starting == week_starting)
        if strategy_id is not None:
            query = query.where(PaperTrade.strategy_id == strategy_id)

        rows = self.session.execute(query).scalars().all()
        closed = [r for r in rows if r.status == "closed" and r.realized_return is not None]
        probs = [r.prob_2pct for r in closed if r.prob_2pct is not None]
        actuals = [1.0 if r.hit_2pct else 0.0 for r in closed if r.hit_2pct is not None]

        hit_rate = mean(actuals) if actuals else None
        avg_prob = mean(probs) if probs else None
        brier = None
        if probs and len(probs) == len(actuals):
            brier = mean((p - a) ** 2 for p, a in zip(probs, actuals))

        returns = [r.realized_return for r in closed if r.realized_return is not None]
        expected = [r.expected_return for r in closed if r.expected_return is not None]

        return {
            "total": len(rows),
            "open": sum(1 for r in rows if r.status == "open"),
            "pending_data": sum(1 for r in rows if r.status == "pending_data"),
            "closed": len(closed),
            "hit_rate_2pct": round(hit_rate, 4) if hit_rate is not None else None,
            "hit_rate_3pct": round(mean(1.0 if r.hit_3pct else 0.0 for r in closed), 4) if closed else None,
            "loss_rate_2pct": round(mean(1.0 if r.hit_loss_2pct else 0.0 for r in closed), 4) if closed else None,
            "avg_prob_2pct": round(avg_prob, 4) if avg_prob is not None else None,
            "calibration_error_2pct": round(avg_prob - hit_rate, 4) if avg_prob is not None and hit_rate is not None else None,
            "brier_score_2pct": round(brier, 4) if brier is not None else None,
            "avg_expected_return": round(mean(expected), 4) if expected else None,
            "avg_realized_return": round(mean(returns), 4) if returns else None,
        }
