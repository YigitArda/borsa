from fastapi import APIRouter

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/ingest")
async def trigger_ingest(tickers: list[str] | None = None, start: str = "2010-01-01"):
    from app.tasks.pipeline_tasks import ingest_prices
    task = ingest_prices.delay(tickers=tickers, start=start)
    return {"task_id": task.id, "status": "queued"}


@router.post("/features")
async def trigger_features(tickers: list[str] | None = None):
    from app.tasks.pipeline_tasks import compute_features
    task = compute_features.delay(tickers=tickers)
    return {"task_id": task.id, "status": "queued"}


@router.post("/run-all")
async def trigger_full_pipeline():
    from app.tasks.pipeline_tasks import run_full_pipeline
    task = run_full_pipeline.delay()
    return {"task_id": task.id, "status": "queued"}
