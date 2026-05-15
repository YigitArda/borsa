from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.export import ExportService

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/predictions")
async def export_predictions(
    week: str | None = None,
    format: str = "csv",
    db: AsyncSession = Depends(get_db),
):
    if format.lower() != "csv":
        raise HTTPException(400, "Only CSV format is supported")

    svc = ExportService(db)
    try:
        buffer = await svc.export_predictions_csv(week=week)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    filename = f"predictions_{week or 'all'}.csv"
    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/backtest/{run_id}")
async def export_backtest(
    run_id: int,
    format: str = "csv",
    db: AsyncSession = Depends(get_db),
):
    if format.lower() != "csv":
        raise HTTPException(400, "Only CSV format is supported")

    svc = ExportService(db)
    try:
        buffer = await svc.export_backtest_csv(run_id=run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    filename = f"backtest_run_{run_id}.csv"
    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/trades")
async def export_trades(
    strategy_id: int | None = None,
    format: str = "csv",
    db: AsyncSession = Depends(get_db),
):
    if format.lower() != "csv":
        raise HTTPException(400, "Only CSV format is supported")

    svc = ExportService(db)
    try:
        buffer = await svc.export_trades_csv(strategy_id=strategy_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    filename = f"trades_{strategy_id or 'all'}.csv"
    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
