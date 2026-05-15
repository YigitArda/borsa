from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.prediction import PaperTrade, WeeklyPrediction
from app.models.stock import Stock
from app.tasks.celery_app import enqueue_task

router = APIRouter(prefix="/weekly-picks", tags=["weekly-picks"])


@router.get("")
async def get_weekly_picks(week: str | None = None, strategy_id: int | None = None, db: AsyncSession = Depends(get_db)):
    query = select(WeeklyPrediction, Stock).join(Stock, WeeklyPrediction.stock_id == Stock.id)

    if week:
        query = query.where(WeeklyPrediction.week_starting == week)
    else:
        from sqlalchemy import func
        subq = select(func.max(WeeklyPrediction.week_starting)).scalar_subquery()
        query = query.where(WeeklyPrediction.week_starting == subq)

    if strategy_id:
        query = query.where(WeeklyPrediction.strategy_id == strategy_id)

    query = query.order_by(WeeklyPrediction.rank)
    rows = (await db.execute(query)).all()

    return [
        {
            "rank": pred.rank,
            "ticker": stock.ticker,
            "name": stock.name,
            "sector": stock.sector,
            "week_starting": str(pred.week_starting),
            "prob_2pct": pred.prob_2pct,
            "prob_loss_2pct": pred.prob_loss_2pct,
            "expected_return": pred.expected_return,
            "confidence": pred.confidence,
            "signal_summary": pred.signal_summary,
        }
        for pred, stock in rows
    ]


@router.post("/generate")
async def generate_picks(strategy_id: int | None = None, week: str | None = None, open_paper: bool = True):
    """Trigger weekly prediction generation via Celery."""
    from app.tasks.pipeline_tasks import generate_weekly_predictions
    task = enqueue_task(
        generate_weekly_predictions,
        week_starting=week,
        strategy_id=strategy_id,
        open_paper=open_paper,
    )
    return {"task_id": task.id, "status": "queued"}


@router.get("/paper")
async def get_paper_trades(
    week: str | None = None,
    strategy_id: int | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    query = select(PaperTrade, Stock).join(Stock, PaperTrade.stock_id == Stock.id)
    if week:
        query = query.where(PaperTrade.week_starting == date.fromisoformat(week))
    if strategy_id:
        query = query.where(PaperTrade.strategy_id == strategy_id)
    query = query.order_by(PaperTrade.week_starting.desc(), PaperTrade.rank).limit(limit)
    rows = (await db.execute(query)).all()

    trades = [
        {
            "id": trade.id,
            "ticker": stock.ticker,
            "name": stock.name,
            "sector": stock.sector,
            "strategy_id": trade.strategy_id,
            "rank": trade.rank,
            "week_starting": str(trade.week_starting),
            "entry_date": str(trade.entry_date) if trade.entry_date else None,
            "planned_exit_date": str(trade.planned_exit_date),
            "exit_date": str(trade.exit_date) if trade.exit_date else None,
            "prob_2pct": trade.prob_2pct,
            "prob_loss_2pct": trade.prob_loss_2pct,
            "expected_return": trade.expected_return,
            "realized_return": trade.realized_return,
            "max_rise_in_period": trade.max_rise_in_period,
            "max_drawdown_in_period": trade.max_drawdown_in_period,
            "hit_2pct": trade.hit_2pct,
            "hit_3pct": trade.hit_3pct,
            "hit_loss_2pct": trade.hit_loss_2pct,
            "status": trade.status,
            "confidence": trade.confidence,
            "signal_summary": trade.signal_summary,
        }
        for trade, stock in rows
    ]

    closed = [t for t in trades if t["status"] == "closed" and t["realized_return"] is not None]
    hit_actuals = [1.0 if t["hit_2pct"] else 0.0 for t in closed if t["hit_2pct"] is not None]
    probs = [t["prob_2pct"] for t in closed if t["prob_2pct"] is not None]
    returns = [t["realized_return"] for t in closed if t["realized_return"] is not None]

    def _avg(vals: list[float]) -> float | None:
        return round(sum(vals) / len(vals), 4) if vals else None

    summary = {
        "total": len(trades),
        "open": sum(1 for t in trades if t["status"] == "open"),
        "pending_data": sum(1 for t in trades if t["status"] == "pending_data"),
        "closed": len(closed),
        "hit_rate_2pct": _avg(hit_actuals),
        "avg_prob_2pct": _avg(probs),
        "avg_realized_return": _avg(returns),
    }
    if summary["hit_rate_2pct"] is not None and summary["avg_prob_2pct"] is not None:
        summary["calibration_error_2pct"] = round(summary["avg_prob_2pct"] - summary["hit_rate_2pct"], 4)
    else:
        summary["calibration_error_2pct"] = None

    return {"summary": summary, "trades": trades}


@router.post("/paper/open")
async def open_paper_trades(week: str | None = None, strategy_id: int | None = None, top_n: int | None = None):
    from app.tasks.pipeline_tasks import open_paper_trades as open_task
    task = enqueue_task(open_task, week_starting=week, strategy_id=strategy_id, top_n=top_n)
    return {"task_id": task.id, "status": "queued"}


@router.post("/paper/evaluate")
async def evaluate_paper_trades(as_of: str | None = None):
    from app.tasks.pipeline_tasks import evaluate_paper_trades as eval_task
    task = enqueue_task(eval_task, as_of=as_of)
    return {"task_id": task.id, "status": "queued"}
