from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.backtest import BacktestRun, BacktestMetric

router = APIRouter(prefix="/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    strategy_config: dict
    tickers: list[str]
    min_train_years: int = 5


class DirectBacktestRequest(BaseModel):
    model_type: str = "lightgbm"
    features: list[str] | None = None
    target: str = "target_2pct_1w"
    threshold: float = 0.5
    top_n: int = 5
    holding_weeks: int = 1
    stop_loss: float | None = None
    take_profit: float | None = None
    apply_liquidity_filter: bool = True
    tickers: list[str] | None = None
    min_train_years: int = 5
    cpcv_groups: int = 6
    cpcv_test_groups: int = 2


@router.post("/run")
async def run_backtest(req: BacktestRequest, db: AsyncSession = Depends(get_db)):
    """Queue a research loop iteration with the given strategy config."""
    from app.tasks.pipeline_tasks import run_research_loop
    task = run_research_loop.delay(n_iterations=1)
    return {"task_id": task.id, "status": "queued"}


@router.post("/direct")
async def run_direct_backtest(req: DirectBacktestRequest, db: AsyncSession = Depends(get_db)):
    """Run a walk-forward backtest synchronously and return fold results.

    Strategy Lab uses this to test arbitrary configs without going through the research loop.
    """
    from app.services.feature_engineering import TECHNICAL_FEATURES
    from app.config import settings

    config = {
        "model_type": req.model_type,
        "features": req.features or TECHNICAL_FEATURES,
        "target": req.target,
        "threshold": req.threshold,
        "top_n": req.top_n,
        "embargo_weeks": 4,
        "holding_weeks": req.holding_weeks,
        "stop_loss": req.stop_loss,
        "take_profit": req.take_profit,
        "apply_liquidity_filter": req.apply_liquidity_filter,
    }
    tickers = req.tickers or settings.mvp_tickers

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings as cfg
    engine = create_engine(cfg.sync_database_url)
    SyncSession = sessionmaker(bind=engine)
    session = SyncSession()

    try:
        from app.services.model_training import ModelTrainer
        trainer = ModelTrainer(session, config)
        folds = trainer.walk_forward(
            tickers,
            min_train_years=req.min_train_years,
            apply_liquidity_filter=req.apply_liquidity_filter,
        )

        if not folds:
            return {"status": "failed", "reason": "no walk-forward folds produced"}

        fold_results = [
            {
                "fold": f.fold,
                "train_start": str(f.train_start),
                "train_end": str(f.train_end),
                "test_start": str(f.test_start),
                "test_end": str(f.test_end),
                "metrics": f.metrics,
                "equity_curve": f.equity_curve or [],
            }
            for f in folds
        ]

        # Aggregate
        import numpy as np
        all_metrics = [f.metrics for f in folds if f.metrics]
        avg_metrics = {}
        if all_metrics:
            for key in all_metrics[0]:
                vals = [m.get(key) for m in all_metrics if m.get(key) is not None]
                avg_metrics[key] = round(float(np.mean(vals)), 4) if vals else None

        return {
            "status": "ok",
            "config": config,
            "n_folds": len(folds),
            "avg_metrics": avg_metrics,
            "folds": fold_results,
        }
    finally:
        session.close()


@router.post("/cpcv")
async def run_cpcv_backtest(req: DirectBacktestRequest, db: AsyncSession = Depends(get_db)):
    """Run combinatorial purged CV for robustness checks."""
    from app.services.feature_engineering import TECHNICAL_FEATURES
    from app.config import settings
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    config = {
        "model_type": req.model_type,
        "features": req.features or TECHNICAL_FEATURES,
        "target": req.target,
        "threshold": req.threshold,
        "top_n": req.top_n,
        "embargo_weeks": 4,
        "holding_weeks": req.holding_weeks,
        "stop_loss": req.stop_loss,
        "take_profit": req.take_profit,
    }
    tickers = req.tickers or settings.mvp_tickers
    engine = create_engine(settings.sync_database_url)
    SyncSession = sessionmaker(bind=engine)
    session = SyncSession()
    try:
        from app.services.model_training import ModelTrainer
        trainer = ModelTrainer(session, config)
        folds = trainer.combinatorial_purged_cv(
            tickers,
            n_groups=req.cpcv_groups,
            n_test_groups=req.cpcv_test_groups,
            apply_liquidity_filter=req.apply_liquidity_filter,
        )
        if not folds:
            return {"status": "failed", "reason": "no CPCV folds produced"}

        import numpy as np
        all_metrics = [f.metrics for f in folds if f.metrics]
        avg_metrics = {}
        if all_metrics:
            for key in all_metrics[0]:
                vals = [m.get(key) for m in all_metrics if m.get(key) is not None]
                avg_metrics[key] = round(float(np.mean(vals)), 4) if vals else None

        return {
            "status": "ok",
            "config": config,
            "n_folds": len(folds),
            "avg_metrics": avg_metrics,
            "folds": [
                {
                    "fold": f.fold,
                    "train_start": str(f.train_start),
                    "train_end": str(f.train_end),
                    "test_start": str(f.test_start),
                    "test_end": str(f.test_end),
                    "metrics": f.metrics,
                    "equity_curve": f.equity_curve or [],
                }
                for f in folds
            ],
        }
    finally:
        session.close()


@router.get("/{run_id}")
async def get_backtest(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(BacktestRun, run_id)
    if not run:
        return {"error": "not found"}
    metrics = await db.execute(
        select(BacktestMetric).where(BacktestMetric.backtest_run_id == run_id)
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
