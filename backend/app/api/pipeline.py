from fastapi import APIRouter
from pydantic import BaseModel

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
    task = ingest_prices.delay(tickers=tickers, start=start)
    return {"task_id": task.id, "status": "queued"}


@router.post("/features")
async def trigger_features(body: TickerList | None = None):
    from app.tasks.pipeline_tasks import compute_features
    tickers = body.tickers if body else None
    task = compute_features.delay(tickers=tickers)
    return {"task_id": task.id, "status": "queued"}


@router.post("/macro")
async def trigger_macro(start: str = "2010-01-01"):
    from app.tasks.pipeline_tasks import ingest_macro
    task = ingest_macro.delay(start=start)
    return {"task_id": task.id, "status": "queued"}


@router.post("/news")
async def trigger_news(body: TickerList | None = None):
    from app.tasks.pipeline_tasks import ingest_news
    tickers = body.tickers if body else None
    task = ingest_news.delay(tickers=tickers)
    return {"task_id": task.id, "status": "queued"}


@router.post("/financials")
async def trigger_financials(body: TickerList | None = None):
    from app.tasks.pipeline_tasks import ingest_financials
    tickers = body.tickers if body else None
    task = ingest_financials.delay(tickers=tickers)
    return {"task_id": task.id, "status": "queued"}


@router.post("/statements")
async def trigger_statements(body: TickerList | None = None):
    from app.tasks.pipeline_tasks import ingest_statements
    tickers = body.tickers if body else None
    task = ingest_statements.delay(tickers=tickers)
    return {"task_id": task.id, "status": "queued"}


@router.post("/social")
async def trigger_social(body: TickerList | None = None):
    from app.tasks.pipeline_tasks import ingest_social
    tickers = body.tickers if body else None
    task = ingest_social.delay(tickers=tickers)
    return {"task_id": task.id, "status": "queued"}


@router.post("/snapshot-universe")
async def trigger_universe_snapshot(body: TickerList | None = None, index_name: str = "SP500"):
    from app.tasks.pipeline_tasks import snapshot_universe
    tickers = body.tickers if body else None
    task = snapshot_universe.delay(index_name=index_name, tickers=tickers)
    return {"task_id": task.id, "status": "queued"}


@router.post("/run-all")
async def trigger_full_pipeline(body: TickerList | None = None, start: str = "2010-01-01"):
    from app.tasks.pipeline_tasks import run_full_pipeline
    tickers = body.tickers if body else None
    task = run_full_pipeline.delay(tickers=tickers, start=start)
    return {"task_id": task.id, "status": "queued"}


@router.post("/import/pit-financials")
async def import_pit_financials(body: ImportPath):
    from app.tasks.pipeline_tasks import import_pit_financials
    task = import_pit_financials.delay(path=body.path, data_source=body.data_source or "pit_csv")
    return {"task_id": task.id, "status": "queued"}


@router.post("/import/universe")
async def import_universe(body: ImportPath):
    from app.tasks.pipeline_tasks import import_universe_snapshots
    task = import_universe_snapshots.delay(path=body.path, index_name=body.index_name or "SP500")
    return {"task_id": task.id, "status": "queued"}


@router.post("/import/ticker-aliases")
async def import_ticker_aliases(body: ImportPath):
    from app.tasks.pipeline_tasks import import_ticker_aliases
    task = import_ticker_aliases.delay(path=body.path)
    return {"task_id": task.id, "status": "queued"}


@router.post("/import/corporate-actions")
async def import_corporate_actions(body: ImportPath):
    from app.tasks.pipeline_tasks import import_corporate_actions
    task = import_corporate_actions.delay(path=body.path, data_source=body.data_source or "csv")
    return {"task_id": task.id, "status": "queued"}
