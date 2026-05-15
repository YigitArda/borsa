from fastapi import APIRouter, Depends
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.stock import CorporateAction, Stock, StockUniverseSnapshot, TickerAlias
from app.models.price import PriceWeekly, PriceDaily
from app.models.feature import FeatureWeekly
from app.models.financial import FinancialMetric
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

    pit_financial_rows = (await db.execute(
        select(func.count()).where(FinancialMetric.as_of_date.is_not(None))
    )).scalar()
    yfinance_financial_rows = (await db.execute(
        select(func.count()).where(FinancialMetric.data_source == "yfinance")
    )).scalar()
    universe_snapshot_count = (await db.execute(select(func.count()).select_from(StockUniverseSnapshot))).scalar()
    ticker_alias_count = (await db.execute(select(func.count()).select_from(TickerAlias))).scalar()
    corporate_action_count = (await db.execute(select(func.count()).select_from(CorporateAction))).scalar()

    return {
        "stocks": stock_reports,
        "macro_freshness": macro_latest,
        "data_quality_gates": {
            "pit_financial_rows": pit_financial_rows,
            "yfinance_financial_rows": yfinance_financial_rows,
            "universe_snapshot_count": universe_snapshot_count,
            "ticker_alias_count": ticker_alias_count,
            "corporate_action_count": corporate_action_count,
            "warnings": [
                "yfinance fundamentals are restated/current approximations unless PIT CSV data is imported",
                "historical survivorship-free universe requires imported snapshots before the first live snapshot date",
                "ticker aliases and corporate actions require imported audit data for full historical repair",
            ],
        },
        "total_stocks": len(stocks),
        "stocks_with_data": sum(1 for r in stock_reports if r["status"] == "ok"),
    }
