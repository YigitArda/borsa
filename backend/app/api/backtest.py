from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.backtest import BacktestRun, BacktestMetric

router = APIRouter(prefix="/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    strategy_config: dict
    tickers: list[str]
    min_train_years: int = 5


@router.post("/run")
async def run_backtest(req: BacktestRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    from app.tasks.pipeline_tasks import run_research_loop
    task = run_research_loop.delay(n_iterations=1)
    return {"task_id": task.id, "status": "queued"}


@router.get("/{run_id}")
async def get_backtest(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(BacktestRun, run_id)
    if not run:
        return {"error": "not found"}
    metrics = await db.execute(
        __import__("sqlalchemy", fromlist=["select"]).select(BacktestMetric).where(BacktestMetric.backtest_run_id == run_id)
    )
    metric_rows = metrics.scalars().all()
    return {
        "id": run.id,
        "strategy_id": run.strategy_id,
        "status": run.status,
        "train_start": str(run.train_start),
        "train_end": str(run.train_end),
        "test_start": str(run.test_start),
        "test_end": str(run.test_end),
        "metrics": {m.metric_name: m.value for m in metric_rows},
    }
