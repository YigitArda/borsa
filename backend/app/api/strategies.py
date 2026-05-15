from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.strategy import Strategy, ModelVersion
from app.services.model_registry import ModelRegistry

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("")
async def list_strategies(status: str | None = None, db: AsyncSession = Depends(get_db)):
    query = select(Strategy).order_by(Strategy.created_at.desc())
    if status:
        query = query.where(Strategy.status == status)
    rows = (await db.execute(query)).scalars().all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "status": s.status,
            "generation": s.generation,
            "config": s.config,
            "created_at": str(s.created_at),
            "notes": s.notes,
        }
        for s in rows
    ]


@router.post("/research/start")
async def start_research(n_iterations: int = 5, base_strategy_id: int | None = None):
    from app.tasks.pipeline_tasks import run_research_loop
    task = run_research_loop.delay(n_iterations=n_iterations, base_strategy_id=base_strategy_id)
    return {"task_id": task.id, "status": "queued", "n_iterations": n_iterations}


def _sync_promotion_gate():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings
    from app.services.promotion import PromotionGate

    engine = create_engine(settings.sync_database_url)
    SyncSession = sessionmaker(bind=engine)
    session = SyncSession()
    return session, PromotionGate(session)


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: int, db: AsyncSession = Depends(get_db)):
    strategy = await db.get(Strategy, strategy_id)
    if not strategy:
        return {"error": "not found"}
    return {
        "id": strategy.id,
        "name": strategy.name,
        "status": strategy.status,
        "config": strategy.config,
        "notes": strategy.notes,
    }


@router.get("/{strategy_id}/promotion-check")
async def promotion_check(strategy_id: int, db: AsyncSession = Depends(get_db)):
    strategy = await db.get(Strategy, strategy_id)
    if not strategy:
        raise HTTPException(404, "Strategy not found")

    session, gate = _sync_promotion_gate()
    try:
        passed, summary = gate.evaluate(strategy_id)
        return {"strategy_id": strategy_id, "passed": passed, "details": summary}
    finally:
        session.close()


@router.post("/{strategy_id}/promote")
async def promote_strategy(strategy_id: int, db: AsyncSession = Depends(get_db)):
    """Promote only after research gates and paper forward-test gates pass."""
    strategy = await db.get(Strategy, strategy_id)
    if not strategy:
        raise HTTPException(404, "Strategy not found")
    if strategy.status == "promoted":
        return {"message": "already promoted", "strategy_id": strategy_id}

    session, gate = _sync_promotion_gate()
    try:
        passed, summary = gate.promote(strategy_id)
        if not passed:
            raise HTTPException(422, {"message": "promotion gate failed", "details": summary})
        return {"message": "promoted", "strategy_id": strategy_id, "details": summary}
    finally:
        session.close()


@router.post("/{strategy_id}/archive")
async def archive_strategy(strategy_id: int, db: AsyncSession = Depends(get_db)):
    strategy = await db.get(Strategy, strategy_id)
    if not strategy:
        raise HTTPException(404, "Strategy not found")
    strategy.status = "archived"
    await db.commit()
    return {"message": "archived", "strategy_id": strategy_id}


# ---------------------------------------------------------------------------
# Model Versions
# ---------------------------------------------------------------------------

def _model_version_to_dict(mv: ModelVersion) -> dict:
    return {
        "id": mv.id,
        "strategy_id": mv.strategy_id,
        "model_path": mv.model_path,
        "feature_set_version": mv.feature_set_version,
        "train_start": mv.train_start,
        "train_end": mv.train_end,
        "metrics": mv.metrics,
        "created_at": str(mv.created_at) if mv.created_at else None,
        "status": mv.status,
        "holdout_period": mv.holdout_period,
        "validation_period": mv.validation_period,
        "parent_model_id": mv.parent_model_id,
        "promotion_reason": mv.promotion_reason,
        "rejection_reason": mv.rejection_reason,
        "hyperparams": mv.hyperparams,
        "model_file_hash": mv.model_file_hash,
    }


@router.get("/{strategy_id}/model-versions")
async def list_model_versions(strategy_id: int, db: AsyncSession = Depends(get_db)):
    """List all model versions for a strategy, newest first."""
    registry = ModelRegistry(db)
    versions = await registry.get_all_versions(strategy_id)
    return [_model_version_to_dict(v) for v in versions]


@router.get("/{strategy_id}/model-versions/{version_id}")
async def get_model_version(strategy_id: int, version_id: int, db: AsyncSession = Depends(get_db)):
    """Get details for a specific model version."""
    mv = await db.get(ModelVersion, version_id)
    if mv is None or mv.strategy_id != strategy_id:
        raise HTTPException(404, "Model version not found")
    return _model_version_to_dict(mv)


@router.post("/{strategy_id}/model-versions/{version_id}/archive")
async def archive_model_version(
    strategy_id: int,
    version_id: int,
    reason: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Archive a model version."""
    mv = await db.get(ModelVersion, version_id)
    if mv is None or mv.strategy_id != strategy_id:
        raise HTTPException(404, "Model version not found")

    registry = ModelRegistry(db)
    try:
        archived = await registry.archive_model(version_id, reason=reason)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return _model_version_to_dict(archived)
