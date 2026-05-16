from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.stock import Stock
from app.tasks.celery_app import enqueue_task

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


async def _validate_tickers(tickers: list[str] | None, db: AsyncSession) -> list[str]:
    """Return tickers that exist in DB; warn about unknown ones."""
    if not tickers:
        return tickers or []
    rows = await db.execute(select(Stock.ticker).where(Stock.ticker.in_(tickers)))
    known = {r[0] for r in rows.all()}
    unknown = [t for t in tickers if t not in known]
    if unknown:
        import logging
        logging.getLogger(__name__).warning("Unknown tickers (not in DB): %s", unknown)
    return tickers


class TickerList(BaseModel):
    tickers: list[str] | None = None


class ImportPath(BaseModel):
    path: str
    data_source: str | None = None
    index_name: str | None = None


@router.post("/ingest")
async def trigger_ingest(body: TickerList | None = None, start: str = "2010-01-01", db: AsyncSession = Depends(get_db)):
    from app.tasks.pipeline_tasks import ingest_prices
    tickers = body.tickers if body else None
    if tickers:
        await _validate_tickers(tickers, db)
    task = enqueue_task(ingest_prices, tickers=tickers, start=start)
    return {"task_id": task.id, "status": "queued"}


@router.post("/features")
async def trigger_features(body: TickerList | None = None):
    from app.tasks.pipeline_tasks import compute_features
    tickers = body.tickers if body else None
    task = enqueue_task(compute_features, tickers=tickers)
    return {"task_id": task.id, "status": "queued"}


@router.post("/macro")
async def trigger_macro(start: str = "2010-01-01", include_external_sources: bool = True):
    from app.tasks.pipeline_tasks import ingest_macro
    task = enqueue_task(ingest_macro, start=start, include_external_sources=include_external_sources)
    return {"task_id": task.id, "status": "queued"}


@router.post("/ingest-fred")
async def trigger_fred(start: str = "2010-01-01"):
    from app.tasks.pipeline_tasks import ingest_fred
    task = enqueue_task(ingest_fred, start=start)
    return {"task_id": task.id, "status": "queued"}


@router.post("/ingest-dbnomics")
async def trigger_dbnomics(start: str = "2010-01-01"):
    from app.tasks.pipeline_tasks import ingest_dbnomics
    task = enqueue_task(ingest_dbnomics, start=start)
    return {"task_id": task.id, "status": "queued"}


@router.post("/news")
async def trigger_news(body: TickerList | None = None):
    from app.tasks.pipeline_tasks import ingest_news
    tickers = body.tickers if body else None
    task = enqueue_task(ingest_news, tickers=tickers)
    return {"task_id": task.id, "status": "queued"}


@router.post("/financials")
async def trigger_financials(body: TickerList | None = None):
    from app.tasks.pipeline_tasks import ingest_financials
    tickers = body.tickers if body else None
    task = enqueue_task(ingest_financials, tickers=tickers)
    return {"task_id": task.id, "status": "queued"}


@router.post("/statements")
async def trigger_statements(body: TickerList | None = None):
    from app.tasks.pipeline_tasks import ingest_statements
    tickers = body.tickers if body else None
    task = enqueue_task(ingest_statements, tickers=tickers)
    return {"task_id": task.id, "status": "queued"}


@router.post("/social")
async def trigger_social(body: TickerList | None = None):
    from app.tasks.pipeline_tasks import ingest_social
    tickers = body.tickers if body else None
    task = enqueue_task(ingest_social, tickers=tickers)
    return {"task_id": task.id, "status": "queued"}


@router.post("/snapshot-universe")
async def trigger_universe_snapshot(body: TickerList | None = None, index_name: str = "SP500"):
    from app.tasks.pipeline_tasks import snapshot_universe
    tickers = body.tickers if body else None
    task = enqueue_task(snapshot_universe, index_name=index_name, tickers=tickers)
    return {"task_id": task.id, "status": "queued"}


@router.post("/run-all")
async def trigger_full_pipeline(body: TickerList | None = None, start: str = "2010-01-01"):
    from app.tasks.pipeline_tasks import run_full_pipeline
    tickers = body.tickers if body else None
    task = enqueue_task(run_full_pipeline, tickers=tickers, start=start)
    return {"task_id": task.id, "status": "queued"}


@router.post("/import/pit-financials")
async def import_pit_financials(body: ImportPath):
    from app.tasks.pipeline_tasks import import_pit_financials
    task = enqueue_task(import_pit_financials, path=body.path, data_source=body.data_source or "pit_csv")
    return {"task_id": task.id, "status": "queued"}


@router.post("/import/universe")
async def import_universe(body: ImportPath):
    from app.tasks.pipeline_tasks import import_universe_snapshots
    task = enqueue_task(import_universe_snapshots, path=body.path, index_name=body.index_name or "SP500")
    return {"task_id": task.id, "status": "queued"}


@router.post("/import/ticker-aliases")
async def import_ticker_aliases(body: ImportPath):
    from app.tasks.pipeline_tasks import import_ticker_aliases
    task = enqueue_task(import_ticker_aliases, path=body.path)
    return {"task_id": task.id, "status": "queued"}


@router.post("/import/corporate-actions")
async def import_corporate_actions(body: ImportPath):
    from app.tasks.pipeline_tasks import import_corporate_actions
    task = enqueue_task(import_corporate_actions, path=body.path, data_source=body.data_source or "csv")
    return {"task_id": task.id, "status": "queued"}
