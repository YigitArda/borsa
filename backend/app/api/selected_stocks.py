from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.model_run import SelectedStock
from app.models.stock import Stock

router = APIRouter(prefix="/selected-stocks", tags=["selected-stocks"])


@router.get("")
async def get_selected_stocks(
    week: str | None = None,
    strategy_id: int | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    query = select(SelectedStock, Stock).join(Stock, SelectedStock.stock_id == Stock.id)

    if week:
        query = query.where(SelectedStock.week_starting == week)
    else:
        subq = select(func.max(SelectedStock.week_starting)).scalar_subquery()
        query = query.where(SelectedStock.week_starting == subq)

    if strategy_id:
        query = query.where(SelectedStock.strategy_id == strategy_id)

    query = query.order_by(SelectedStock.rank).limit(limit)
    rows = (await db.execute(query)).all()

    return [
        {
            "id": sel.id,
            "week_starting": sel.week_starting,
            "ticker": stock.ticker,
            "name": stock.name,
            "sector": stock.sector,
            "strategy_id": sel.strategy_id,
            "rank": sel.rank,
            "signal": sel.signal,
            "confidence": sel.confidence,
            "risk_level": sel.risk_level,
            "reasoning": sel.reasoning,
            "created_at": str(sel.created_at) if sel.created_at else None,
        }
        for sel, stock in rows
    ]


@router.get("/{week}")
async def get_selected_stocks_by_week(
    week: str,
    strategy_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(SelectedStock, Stock).join(Stock, SelectedStock.stock_id == Stock.id)
    query = query.where(SelectedStock.week_starting == week)
    if strategy_id:
        query = query.where(SelectedStock.strategy_id == strategy_id)
    query = query.order_by(SelectedStock.rank)
    rows = (await db.execute(query)).all()

    return [
        {
            "id": sel.id,
            "week_starting": sel.week_starting,
            "ticker": stock.ticker,
            "name": stock.name,
            "sector": stock.sector,
            "strategy_id": sel.strategy_id,
            "rank": sel.rank,
            "signal": sel.signal,
            "confidence": sel.confidence,
            "risk_level": sel.risk_level,
            "reasoning": sel.reasoning,
            "created_at": str(sel.created_at) if sel.created_at else None,
        }
        for sel, stock in rows
    ]


@router.get("/history")
async def get_selected_stocks_history(
    strategy_id: int | None = None,
    ticker: str | None = None,
    limit: int = 500,
    db: AsyncSession = Depends(get_db),
):
    query = select(SelectedStock, Stock).join(Stock, SelectedStock.stock_id == Stock.id)

    if strategy_id:
        query = query.where(SelectedStock.strategy_id == strategy_id)
    if ticker:
        query = query.where(Stock.ticker.ilike(ticker))

    query = query.order_by(SelectedStock.week_starting.desc(), SelectedStock.rank).limit(limit)
    rows = (await db.execute(query)).all()

    return [
        {
            "id": sel.id,
            "week_starting": sel.week_starting,
            "ticker": stock.ticker,
            "name": stock.name,
            "sector": stock.sector,
            "strategy_id": sel.strategy_id,
            "rank": sel.rank,
            "signal": sel.signal,
            "confidence": sel.confidence,
            "risk_level": sel.risk_level,
            "reasoning": sel.reasoning,
            "created_at": str(sel.created_at) if sel.created_at else None,
        }
        for sel, stock in rows
    ]
