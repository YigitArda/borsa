from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.stock import Stock
from app.models.price import PriceWeekly
from app.models.feature import FeatureWeekly, LabelWeekly
from app.models.prediction import WeeklyPrediction

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get("")
async def list_stocks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Stock).where(Stock.is_active == True).order_by(Stock.ticker))
    stocks = result.scalars().all()
    return [{"id": s.id, "ticker": s.ticker, "name": s.name, "sector": s.sector} for s in stocks]


@router.get("/{ticker}")
async def get_stock(ticker: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Stock).where(Stock.ticker == ticker.upper()))
    stock = result.scalar_one_or_none()
    if not stock:
        raise HTTPException(404, f"Stock {ticker} not found")
    return {"id": stock.id, "ticker": stock.ticker, "name": stock.name, "sector": stock.sector, "industry": stock.industry}


@router.get("/{ticker}/prices")
async def get_prices(ticker: str, limit: int = 104, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Stock).where(Stock.ticker == ticker.upper()))
    stock = result.scalar_one_or_none()
    if not stock:
        raise HTTPException(404, f"Stock {ticker} not found")

    prices = await db.execute(
        select(PriceWeekly)
        .where(PriceWeekly.stock_id == stock.id)
        .order_by(PriceWeekly.week_ending.desc())
        .limit(limit)
    )
    rows = prices.scalars().all()
    return [
        {
            "week_ending": str(r.week_ending),
            "close": r.close,
            "weekly_return": r.weekly_return,
            "volume": r.volume,
            "realized_volatility": r.realized_volatility,
        }
        for r in reversed(rows)
    ]


@router.get("/{ticker}/features")
async def get_features(ticker: str, week: str | None = None, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Stock).where(Stock.ticker == ticker.upper()))
    stock = result.scalar_one_or_none()
    if not stock:
        raise HTTPException(404, f"Stock {ticker} not found")

    query = select(FeatureWeekly).where(FeatureWeekly.stock_id == stock.id)
    if week:
        query = query.where(FeatureWeekly.week_ending == week)
    else:
        # Latest week
        from sqlalchemy import func
        subq = select(func.max(FeatureWeekly.week_ending)).where(FeatureWeekly.stock_id == stock.id).scalar_subquery()
        query = query.where(FeatureWeekly.week_ending == subq)

    rows = (await db.execute(query)).scalars().all()
    return {r.feature_name: r.value for r in rows}


@router.get("/{ticker}/analysis")
async def get_analysis(ticker: str, db: AsyncSession = Depends(get_db)):
    """Summary for Stock Research Page."""
    result = await db.execute(select(Stock).where(Stock.ticker == ticker.upper()))
    stock = result.scalar_one_or_none()
    if not stock:
        raise HTTPException(404, f"Stock {ticker} not found")

    # Good entry weeks (target_2pct_1w = 1)
    labels = await db.execute(
        select(LabelWeekly)
        .where(LabelWeekly.stock_id == stock.id, LabelWeekly.target_name == "target_2pct_1w")
        .order_by(LabelWeekly.week_ending)
    )
    label_rows = labels.scalars().all()
    total = len(label_rows)
    positive = sum(1 for r in label_rows if r.value == 1.0)

    return {
        "ticker": stock.ticker,
        "name": stock.name,
        "sector": stock.sector,
        "total_weeks_analyzed": total,
        "weeks_with_2pct_return": positive,
        "historical_hit_rate": round(positive / total, 4) if total > 0 else None,
    }
