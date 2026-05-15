from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.stock import CorporateAction, Stock, StockUniverseSnapshot, TickerAlias
from app.models.price import PriceWeekly, PriceDaily
from app.models.feature import FeatureWeekly
from app.models.financial import FinancialMetric
from app.models.macro import MacroIndicator
from app.models.data_quality_score import DataQualityScore
from app.services.data_quality_scoring import DataQualityScorer

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


@router.get("/scores")
async def list_quality_scores(
    week: date | None = Query(None, description="Week ending date (Friday). Defaults to latest available."),
    db: AsyncSession = Depends(get_db),
):
    """Get quality scores for all stocks for a given week."""
    if week is None:
        latest = (
            await db.execute(select(func.max(DataQualityScore.week_ending)))
        ).scalar()
        week = latest

    if week is None:
        return {"week": None, "scores": [], "message": "No scores computed yet."}

    rows = (
        await db.execute(
            select(DataQualityScore, Stock.ticker, Stock.name)
            .join(Stock, DataQualityScore.stock_id == Stock.id)
            .where(DataQualityScore.week_ending == week)
            .order_by(DataQualityScore.overall_score.desc())
        )
    ).all()

    scores = []
    for row in rows:
        dq, ticker, name = row
        scores.append({
            "ticker": ticker,
            "name": name,
            "stock_id": dq.stock_id,
            "week_ending": str(dq.week_ending),
            "overall_score": dq.overall_score,
            "price_score": dq.price_score,
            "feature_score": dq.feature_score,
            "financial_score": dq.financial_score,
            "news_score": dq.news_score,
            "macro_score": dq.macro_score,
            "flag": dq.details.get("flag") if dq.details else None,
        })

    return {
        "week": str(week),
        "count": len(scores),
        "scores": scores,
    }


@router.get("/scores/{ticker}")
async def get_stock_quality_score(
    ticker: str,
    week: date | None = Query(None, description="Week ending date (Friday). Defaults to latest available."),
    db: AsyncSession = Depends(get_db),
):
    """Get quality score for a specific stock ticker."""
    stock = (
        await db.execute(select(Stock).where(Stock.ticker == ticker.upper()))
    ).scalar_one_or_none()

    if stock is None:
        return {"error": f"Ticker {ticker.upper()} not found"}

    if week is None:
        latest = (
            await db.execute(
                select(func.max(DataQualityScore.week_ending)).where(
                    DataQualityScore.stock_id == stock.id
                )
            )
        ).scalar()
        week = latest

    if week is None:
        return {"ticker": ticker.upper(), "message": "No scores computed for this stock yet."}

    dq = (
        await db.execute(
            select(DataQualityScore).where(
                and_(
                    DataQualityScore.stock_id == stock.id,
                    DataQualityScore.week_ending == week,
                )
            )
        )
    ).scalar_one_or_none()

    if dq is None:
        return {"ticker": ticker.upper(), "week": str(week), "message": "No score found for this week."}

    return {
        "ticker": ticker.upper(),
        "name": stock.name,
        "week_ending": str(dq.week_ending),
        "overall_score": dq.overall_score,
        "price_score": dq.price_score,
        "feature_score": dq.feature_score,
        "financial_score": dq.financial_score,
        "news_score": dq.news_score,
        "macro_score": dq.macro_score,
        "flag": dq.details.get("flag") if dq.details else None,
        "details": dq.details,
    }


@router.post("/scores/compute")
async def trigger_batch_scoring(
    week: date | None = Query(None, description="Week ending date (Friday). Defaults to last Friday."),
    db: AsyncSession = Depends(get_db),
):
    """Trigger batch scoring for all active stocks."""
    if week is None:
        today = date.today()
        # Last Friday
        offset = (today.weekday() - 4) % 7
        week = today - __import__("datetime").timedelta(days=offset)
        if offset == 0 and today.weekday() != 4:
            # Edge case: today is not Friday but modulo gave 0 (shouldn't happen with %7)
            week = today - __import__("datetime").timedelta(days=7)

    scorer = DataQualityScorer(db)
    results = await scorer.score_all_stocks_for_week(week)

    poor_quality = sum(1 for r in results if r.overall_score < 50)

    return {
        "week": str(week),
        "stocks_scored": len(results),
        "poor_quality_flags": poor_quality,
        "message": "Batch scoring completed successfully.",
    }
