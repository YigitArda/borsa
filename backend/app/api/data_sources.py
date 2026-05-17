from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.data_source_health import DataConnector
from app.services.connectors.registry import ConnectorRegistry
from app.tasks.celery_app import enqueue_task

router = APIRouter(prefix="/data-sources", tags=["data-sources"])


class ConnectorRunRequest(BaseModel):
    categories: list[str] | None = None
    providers: list[str] | None = None
    tickers: list[str] | None = None
    start: str = "2010-01-01"
    as_of: str | None = None
    lookback_days: int | None = None


class ConnectorUpdateRequest(BaseModel):
    enabled: bool | None = None


@router.get("")
async def list_data_sources(category: str | None = None, db: AsyncSession = Depends(get_db)):
    rows = await db.execute(select(DataConnector))
    state = {row.provider_id: row for row in rows.scalars().all()}
    payload = []
    for definition in ConnectorRegistry.definitions():
        if category and definition.category != category:
            continue
        row = state.get(definition.provider_id)
        connector_cls = ConnectorRegistry.get_class(definition.provider_id)
        configured = connector_cls(None).is_configured() if connector_cls else False
        payload.append(
            {
                "provider_id": definition.provider_id,
                "name": definition.name,
                "category": definition.category,
                "enabled": row.enabled if row else definition.enabled_by_default,
                "requires_api_key": definition.requires_api_key,
                "configured": row.configured if row else configured,
                "priority": definition.priority,
                "rate_limit_per_minute": definition.rate_limit_per_minute,
                "capabilities": list(definition.capabilities),
                "last_status": row.last_status if row else "unknown",
                "last_success_at": row.last_success_at.isoformat() if row and row.last_success_at else None,
                "last_failure_at": row.last_failure_at.isoformat() if row and row.last_failure_at else None,
                "last_message": row.last_message if row else None,
                "coverage_score": row.coverage_score if row else None,
                "freshness_score": row.freshness_score if row else None,
                "quality_score": row.quality_score if row else None,
            }
        )
    payload.sort(key=lambda item: (item["category"], item["priority"], item["provider_id"]))
    return {"status": "ok", "connectors": payload}


@router.get("/health")
async def data_source_health(category: str | None = None, db: AsyncSession = Depends(get_db)):
    return await list_data_sources(category=category, db=db)


@router.patch("/{provider_id}")
async def update_data_source(provider_id: str, body: ConnectorUpdateRequest, db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(DataConnector).where(DataConnector.provider_id == provider_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Connector not found. Run /data-sources/sync first.")
    if body.enabled is not None:
        row.enabled = body.enabled
    await db.commit()
    await db.refresh(row)
    return {
        "status": "ok",
        "connector": {
            "provider_id": row.provider_id,
            "enabled": row.enabled,
            "configured": row.configured,
            "last_status": row.last_status,
        },
    }


@router.post("/sync")
async def sync_data_sources():
    from app.tasks.pipeline_tasks import sync_data_connectors

    task = enqueue_task(sync_data_connectors)
    return {"task_id": task.id, "status": "queued"}


@router.post("/run")
async def run_data_sources(body: ConnectorRunRequest):
    from app.tasks.pipeline_tasks import ingest_connectors

    task = enqueue_task(
        ingest_connectors,
        categories=body.categories,
        providers=body.providers,
        tickers=body.tickers,
        start=body.start,
        as_of=body.as_of,
        lookback_days=body.lookback_days,
    )
    return {"task_id": task.id, "status": "queued"}
