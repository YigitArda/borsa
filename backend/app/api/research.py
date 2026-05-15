from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.backtest import WalkForwardResult, BacktestMetric, BacktestRun
from app.models.model_run import ModelRun
from app.models.strategy import Strategy, ModelPromotion

router = APIRouter(prefix="/research", tags=["research"])


@router.get("/feature-importance/{strategy_id}")
async def get_feature_importance(strategy_id: int, db: AsyncSession = Depends(get_db)):
    runs = await db.execute(
        select(ModelRun)
        .where(ModelRun.strategy_id == strategy_id)
        .order_by(ModelRun.created_at.desc())
        .limit(1)
    )
    run = runs.scalar_one_or_none()
    if not run or not run.feature_importance:
        return {"strategy_id": strategy_id, "feature_importance": {}}
    return {"strategy_id": strategy_id, "feature_importance": run.feature_importance}


@router.get("/walk-forward/{strategy_id}")
async def get_walk_forward(strategy_id: int, db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(WalkForwardResult)
        .where(WalkForwardResult.strategy_id == strategy_id)
        .order_by(WalkForwardResult.fold)
    )
    folds = rows.scalars().all()
    return [
        {
            "fold": f.fold,
            "train_start": str(f.train_start),
            "train_end": str(f.train_end),
            "test_start": str(f.test_start),
            "test_end": str(f.test_end),
            "metrics": f.metrics,
        }
        for f in folds
    ]


@router.get("/compare")
async def compare_strategies(strategy_ids: str, db: AsyncSession = Depends(get_db)):
    """Compare multiple strategies. Pass strategy_ids as comma-separated."""
    ids = [int(i) for i in strategy_ids.split(",") if i.strip().isdigit()]
    result = []
    for sid in ids:
        strategy = await db.get(Strategy, sid)
        if not strategy:
            continue
        runs = await db.execute(
            select(WalkForwardResult).where(WalkForwardResult.strategy_id == sid)
        )
        folds = runs.scalars().all()
        if not folds:
            continue
        all_metrics = [f.metrics for f in folds if f.metrics]
        if not all_metrics:
            continue
        avg = {}
        for key in all_metrics[0]:
            vals = [m.get(key) for m in all_metrics if m.get(key) is not None]
            avg[key] = round(sum(vals) / len(vals), 4) if vals else None
        result.append({
            "strategy_id": sid,
            "name": strategy.name,
            "status": strategy.status,
            "generation": strategy.generation,
            "avg_metrics": avg,
        })
    return result


@router.get("/risk-warnings")
async def get_risk_warnings(db: AsyncSession = Depends(get_db)):
    """Identify strategies that are underperforming or have data quality issues."""
    warnings = []

    promoted = await db.execute(
        select(Strategy).where(Strategy.status == "promoted")
    )
    for s in promoted.scalars().all():
        folds = await db.execute(
            select(WalkForwardResult)
            .where(WalkForwardResult.strategy_id == s.id)
            .order_by(WalkForwardResult.fold.desc())
            .limit(3)
        )
        recent_folds = folds.scalars().all()
        if not recent_folds:
            continue
        recent_sharpes = [f.metrics.get("sharpe", 0) for f in recent_folds if f.metrics]
        if recent_sharpes and sum(recent_sharpes) / len(recent_sharpes) < 0.2:
            warnings.append({
                "strategy_id": s.id,
                "name": s.name,
                "warning": "Recent 3-fold avg Sharpe < 0.2 — strategy may be degrading",
                "severity": "high",
            })

    return {"warnings": warnings, "count": len(warnings)}


@router.post("/sector-models")
async def run_sector_models(tickers: list[str] | None = None):
    """Train and evaluate sector-segmented models (Technology, Financials, etc.)."""
    from app.tasks.pipeline_tasks import _get_sync_session
    from app.services.model_training import ModelTrainer
    from app.services.research_loop import BASE_STRATEGY
    from app.config import settings as cfg
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(cfg.sync_database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        trainer = ModelTrainer(session, BASE_STRATEGY)
        results = trainer.train_per_sector(tickers or cfg.mvp_tickers)
        return {"status": "ok", "sectors": results}
    finally:
        session.close()


@router.get("/promotions")
async def get_promotions(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """All promotion events with statistical validation details."""
    rows = await db.execute(
        select(ModelPromotion).order_by(ModelPromotion.promoted_at.desc()).limit(limit)
    )
    promotions = rows.scalars().all()
    return [
        {
            "id": p.id,
            "strategy_id": p.strategy_id,
            "promoted_at": str(p.promoted_at),
            "avg_sharpe": p.avg_sharpe,
            "deflated_sharpe": p.deflated_sharpe,
            "probabilistic_sr": p.probabilistic_sr,
            "permutation_pvalue": p.permutation_pvalue,
            "spy_sharpe": p.spy_sharpe,
            "outperforms_spy": p.outperforms_spy,
            "avg_win_rate": p.avg_win_rate,
            "total_trades": p.total_trades,
            "min_drawdown": p.min_drawdown,
            "concentration_ok": p.concentration_ok,
            "details": p.details,
        }
        for p in promotions
    ]
