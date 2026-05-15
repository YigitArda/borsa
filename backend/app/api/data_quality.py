from fastapi import APIRouter, Depends
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.stock import Stock
from app.models.price import PriceWeekly, PriceDaily
from app.models.feature import FeatureWeekly
from app.models.macro import MacroIndicator

router = APIRouter(prefix="/data-quality", tags=["data-quality"])


@router.get("")
async def data_quality_report(db: AsyncSession = Depends(get_db)):
    stocks = (await db.execute(select(Stock).where(Stock.is_active == True))).scalars().all()

    stock_reports = []
    for s in stocks:
        # Count weekly prices
        weekly_count = (await db.execute(
            select(func.count()).where(PriceWeekly.stock_id == s.id)
        )).scalar()

        # Count daily prices
        daily_count = (await db.execute(
            select(func.count()).where(PriceDaily.stock_id == s.id)
        )).scalar()

        # Count features
        feature_count = (await db.execute(
            select(func.count()).where(FeatureWeekly.stock_id == s.id)
        )).scalar()

        # Latest weekly date
        latest = (await db.execute(
            select(func.max(PriceWeekly.week_ending)).where(PriceWeekly.stock_id == s.id)
        )).scalar()

        stock_reports.append({
            "ticker": s.ticker,
            "name": s.name,
            "weekly_price_rows": weekly_count,
            "daily_price_rows": daily_count,
            "feature_rows": feature_count,
            "latest_week": str(latest) if latest else None,
            "status": "ok" if weekly_count and weekly_count > 50 else "insufficient_data",
        })

    # Macro freshness
    macro_latest = {}
    macro_rows = (await db.execute(
        select(MacroIndicator.indicator_code, func.max(MacroIndicator.date).label("latest"))
        .group_by(MacroIndicator.indicator_code)
    )).all()
    for row in macro_rows:
        macro_latest[row.indicator_code] = str(row.latest)

    return {
        "stocks": stock_reports,
        "macro_freshness": macro_latest,
        "total_stocks": len(stocks),
        "stocks_with_data": sum(1 for r in stock_reports if r["status"] == "ok"),
    }
