import csv
import io
from datetime import date
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prediction import WeeklyPrediction, PaperTrade
from app.models.backtest import BacktestRun, BacktestTrade, BacktestMetric
from app.models.stock import Stock


class ExportService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _to_csv_buffer(rows: list[dict], fieldnames: list[str]) -> io.StringIO:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (v.isoformat() if isinstance(v, date) else v) for k, v in row.items()})
        buffer.seek(0)
        return buffer

    # ------------------------------------------------------------------
    # Predictions
    # ------------------------------------------------------------------
    async def export_predictions_csv(self, week: str | None = None) -> io.StringIO:
        query = select(WeeklyPrediction, Stock).join(Stock, WeeklyPrediction.stock_id == Stock.id)
        if week:
            query = query.where(WeeklyPrediction.week_starting == week)
        query = query.order_by(WeeklyPrediction.week_starting.desc(), WeeklyPrediction.rank)
        rows = (await self.db.execute(query)).all()

        data = []
        for pred, stock in rows:
            data.append(
                {
                    "week_starting": pred.week_starting,
                    "ticker": stock.ticker,
                    "name": stock.name,
                    "sector": stock.sector,
                    "strategy_id": pred.strategy_id,
                    "rank": pred.rank,
                    "prob_2pct": pred.prob_2pct,
                    "prob_loss_2pct": pred.prob_loss_2pct,
                    "expected_return": pred.expected_return,
                    "confidence": pred.confidence,
                    "signal_summary": pred.signal_summary,
                }
            )

        fieldnames = [
            "week_starting",
            "ticker",
            "name",
            "sector",
            "strategy_id",
            "rank",
            "prob_2pct",
            "prob_loss_2pct",
            "expected_return",
            "confidence",
            "signal_summary",
        ]
        return self._to_csv_buffer(data, fieldnames)

    # ------------------------------------------------------------------
    # Backtest
    # ------------------------------------------------------------------
    async def export_backtest_csv(self, run_id: int) -> io.StringIO:
        run = await self.db.get(BacktestRun, run_id)
        if run is None:
            raise ValueError(f"Backtest run {run_id} not found")

        metrics_result = await self.db.execute(
            select(BacktestMetric).where(BacktestMetric.backtest_run_id == run_id)
        )
        metrics = {m.metric_name: m.value for m in metrics_result.scalars().all()}

        trades_result = await self.db.execute(
            select(BacktestTrade, Stock)
            .join(Stock, BacktestTrade.stock_id == Stock.id)
            .where(BacktestTrade.backtest_run_id == run_id)
            .order_by(BacktestTrade.entry_date)
        )
        trade_rows = trades_result.all()

        data = []
        for trade, stock in trade_rows:
            data.append(
                {
                    "run_id": run_id,
                    "strategy_id": run.strategy_id,
                    "run_type": run.run_type,
                    "ticker": stock.ticker if stock else None,
                    "entry_date": trade.entry_date,
                    "exit_date": trade.exit_date,
                    "entry_price": trade.entry_price,
                    "exit_price": trade.exit_price,
                    "return_pct": trade.return_pct,
                    "pnl": trade.pnl,
                    "signal_strength": trade.signal_strength,
                    "exit_reason": trade.exit_reason,
                    "sharpe_ratio": metrics.get("sharpe_ratio"),
                    "win_rate": metrics.get("win_rate"),
                    "profit_factor": metrics.get("profit_factor"),
                    "max_drawdown": metrics.get("max_drawdown"),
                }
            )

        fieldnames = [
            "run_id",
            "strategy_id",
            "run_type",
            "ticker",
            "entry_date",
            "exit_date",
            "entry_price",
            "exit_price",
            "return_pct",
            "pnl",
            "signal_strength",
            "exit_reason",
            "sharpe_ratio",
            "win_rate",
            "profit_factor",
            "max_drawdown",
        ]
        return self._to_csv_buffer(data, fieldnames)

    # ------------------------------------------------------------------
    # Trades (paper trades)
    # ------------------------------------------------------------------
    async def export_trades_csv(self, strategy_id: int | None = None) -> io.StringIO:
        query = select(PaperTrade, Stock).join(Stock, PaperTrade.stock_id == Stock.id)
        if strategy_id:
            query = query.where(PaperTrade.strategy_id == strategy_id)
        query = query.order_by(PaperTrade.week_starting.desc(), PaperTrade.rank)
        rows = (await self.db.execute(query)).all()

        data = []
        for trade, stock in rows:
            data.append(
                {
                    "id": trade.id,
                    "prediction_id": trade.prediction_id,
                    "week_starting": trade.week_starting,
                    "ticker": stock.ticker if stock else None,
                    "name": stock.name if stock else None,
                    "sector": stock.sector if stock else None,
                    "strategy_id": trade.strategy_id,
                    "rank": trade.rank,
                    "prob_2pct": trade.prob_2pct,
                    "prob_loss_2pct": trade.prob_loss_2pct,
                    "expected_return": trade.expected_return,
                    "confidence": trade.confidence,
                    "entry_date": trade.entry_date,
                    "planned_exit_date": trade.planned_exit_date,
                    "exit_date": trade.exit_date,
                    "entry_price": trade.entry_price,
                    "exit_price": trade.exit_price,
                    "realized_return": trade.realized_return,
                    "max_rise_in_period": trade.max_rise_in_period,
                    "max_drawdown_in_period": trade.max_drawdown_in_period,
                    "hit_2pct": trade.hit_2pct,
                    "hit_3pct": trade.hit_3pct,
                    "hit_loss_2pct": trade.hit_loss_2pct,
                    "status": trade.status,
                }
            )

        fieldnames = [
            "id",
            "prediction_id",
            "week_starting",
            "ticker",
            "name",
            "sector",
            "strategy_id",
            "rank",
            "prob_2pct",
            "prob_loss_2pct",
            "expected_return",
            "confidence",
            "entry_date",
            "planned_exit_date",
            "exit_date",
            "entry_price",
            "exit_price",
            "realized_return",
            "max_rise_in_period",
            "max_drawdown_in_period",
            "hit_2pct",
            "hit_3pct",
            "hit_loss_2pct",
            "status",
        ]
        return self._to_csv_buffer(data, fieldnames)
