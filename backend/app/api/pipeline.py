from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class TickerList(BaseModel):
    tickers: list[str] | None = None


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


@router.post("/run-all")
async def trigger_full_pipeline():
    from app.tasks.pipeline_tasks import run_full_pipeline
    task = run_full_pipeline.delay()
    return {"task_id": task.id, "status": "queued"}
