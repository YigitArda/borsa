from fastapi import APIRouter
from pydantic import BaseModel

from app.tasks.celery_app import enqueue_task

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class TickerList(BaseModel):
    tickers: list[str] | None = None


class ImportPath(BaseModel):
    path: str
    data_source: str | None = None
    index_name: str | None = None


@router.post("/ingest")
async def trigger_ingest(body: TickerList | None = None, start: str = "2010-01-01"):
    from app.tasks.pipeline_tasks import ingest_prices
    tickers = body.tickers if body else None
    task = enqueue_task(ingest_prices, tickers=tickers, start=start)
    return {"task_id": task.id, "status": "queued"}


@router.post("/features")
async def trigger_features(body: TickerList | None = None):
    from app.tasks.pipeline_tasks import compute_features
    tickers = body.tickers if body else None
    task = enqueue_task(compute_features, tickers=tickers)
    return {"task_id": task.id, "status": "queued"}


@router.post("/macro")
async def trigger_macro(start: str = "2010-01-01"):
    from app.tasks.pipeline_tasks import ingest_macro
    task = enqueue_task(ingest_macro, start=start)
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
