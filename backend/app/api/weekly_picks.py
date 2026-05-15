from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.prediction import WeeklyPrediction
from app.models.stock import Stock

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
async def generate_picks(strategy_id: int, week: str | None = None):
    """Trigger weekly prediction generation via Celery."""
    from app.tasks.pipeline_tasks import run_full_pipeline
    task = run_full_pipeline.delay()
    return {"task_id": task.id, "status": "queued"}
