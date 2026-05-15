from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.strategy import Strategy

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


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: int, db: AsyncSession = Depends(get_db)):
    s = await db.get(Strategy, strategy_id)
    if not s:
        return {"error": "not found"}
    return {"id": s.id, "name": s.name, "status": s.status, "config": s.config, "notes": s.notes}


@router.post("/research/start")
async def start_research(n_iterations: int = 5, base_strategy_id: int | None = None):
    from app.tasks.pipeline_tasks import run_research_loop
    task = run_research_loop.delay(n_iterations=n_iterations, base_strategy_id=base_strategy_id)
    return {"task_id": task.id, "status": "queued", "n_iterations": n_iterations}
