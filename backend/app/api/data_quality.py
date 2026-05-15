from collections import defaultdict
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.stock import CorporateAction, Stock, StockUniverseSnapshot, TickerAlias
from app.models.price import PriceWeekly, PriceDaily
from app.models.feature import FeatureWeekly, LabelWeekly
from app.models.financial import FinancialMetric
from app.models.macro import MacroIndicator
from app.models.news import NewsArticle, NewsAnalysis, SocialSentiment
from app.models.data_quality_score import DataQualityScore
from app.services.data_quality_scoring import DataQualityScorer
from app.services.behavioral_signals import BEHAVIORAL_FEATURES
from app.services.factor_momentum_lowvol import MOMENTUM_LOWVOL_FEATURES, MOMENTUM_LOWVOL_BATCH_FEATURES
from app.services.pead_factor import PEAD_FEATURES
from app.services.short_interest_factor import SHORT_INTEREST_FEATURES
from app.services.price_nlp import PRICE_NLP_FEATURES
from app.services.alpha_factor_combiner import ALPHA_COMBO_FEATURES

router = APIRouter(prefix="/data-quality", tags=["data-quality"])

TECHNICAL_PREFIXES = ("rsi_", "macd", "sma_", "ema_", "bb_", "atr_", "volume_", "return_", "momentum", "high_52w", "low_52w", "trend_strength", "price_to_sma", "realized_vol")
FINANCIAL_PREFIXES = ("pe_", "forward_pe", "price_to_", "ev_to_", "gross_margin", "operating_margin", "net_margin", "roe", "roa", "revenue_growth", "earnings_growth", "debt_to_equity", "current_ratio", "beta", "market_cap")
MACRO_PREFIXES = ("vix", "VIX", "tnx", "TNX", "fed_", "FED_", "risk_on", "sp500_trend", "nasdaq_trend", "cpi_proxy", "sector_")
NEWS_SOCIAL_PREFIXES = ("news_", "social_", "sentiment")
ALTERNATIVE_FEATURES = set(
    BEHAVIORAL_FEATURES
    + MOMENTUM_LOWVOL_FEATURES
    + MOMENTUM_LOWVOL_BATCH_FEATURES
    + PEAD_FEATURES
    + SHORT_INTEREST_FEATURES
    + PRICE_NLP_FEATURES
    + ALPHA_COMBO_FEATURES
)

FEATURE_CATEGORIES = ("Teknik", "Finansal", "Makro", "Haber/Sosyal", "Diger")


def _feature_category(feature_name: str) -> str:
    if feature_name in ALTERNATIVE_FEATURES:
        return "Diger"
    if feature_name.startswith(TECHNICAL_PREFIXES):
        return "Teknik"
    if feature_name.startswith(FINANCIAL_PREFIXES):
        return "Finansal"
    if feature_name.startswith(MACRO_PREFIXES):
        return "Makro"
    if feature_name.startswith(NEWS_SOCIAL_PREFIXES):
        return "Haber/Sosyal"
    return "Diger"


def _range_display(start: Any, end: Any) -> str:
    if start is None and end is None:
        return "N/A"
    if start is None:
        return f"-> {end}"
    if end is None:
        return f"{start} ->"
    return f"{start} - {end}"


def _format_range(start: Any, end: Any) -> str:
    if start is None and end is None:
        return "—"
    if start is None:
        return f"→ {end}"
    if end is None:
        return f"{start} →"
    if isinstance(start, datetime):
        start = start.date()
    if isinstance(end, datetime):
        end = end.date()
    return f"{start} - {end}"


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


@router.get("/summary")
async def data_status_summary(db: AsyncSession = Depends(get_db)):
    active_stocks = (await db.execute(
        select(Stock).where(Stock.is_active == True).order_by(Stock.ticker)
    )).scalars().all()

    price_rows = (
        await db.execute(
            select(
                Stock.id,
                Stock.ticker,
                func.count(PriceWeekly.id).label("weeks"),
                func.min(PriceWeekly.week_ending).label("start"),
                func.max(PriceWeekly.week_ending).label("end"),
            )
            .select_from(Stock)
            .outerjoin(PriceWeekly, PriceWeekly.stock_id == Stock.id)
            .where(Stock.is_active == True)
            .group_by(Stock.id, Stock.ticker)
            .order_by(Stock.ticker)
        )
    ).all()

    price_details = [
        {
            "ticker": row.ticker,
            "weeks": int(row.weeks or 0),
            "years": round((row.weeks or 0) / 52.0, 1),
            "start": str(row.start) if row.start else None,
            "end": str(row.end) if row.end else None,
        }
        for row in price_rows
    ]
    price_total_rows = sum(row["weeks"] for row in price_details)
    price_covered = sum(1 for row in price_details if row["weeks"] > 0)
    price_start = min((row["start"] for row in price_details if row["start"]), default=None)
    price_end = max((row["end"] for row in price_details if row["end"]), default=None)

    feature_name_rows = await db.execute(
        select(FeatureWeekly.feature_name).distinct().order_by(FeatureWeekly.feature_name)
    )
    feature_names = [row[0] for row in feature_name_rows.all()]
    feature_total_rows = (
        await db.execute(select(func.count()).select_from(FeatureWeekly))
    ).scalar() or 0
    feature_categories: list[dict[str, Any]] = []
    for category in FEATURE_CATEGORIES:
        names = [name for name in feature_names if _feature_category(name) == category]
        if not names:
            continue
        feature_categories.append(
            {
                "category": category,
                "count": len(names),
                "examples": ", ".join(names[:5]),
            }
        )

    label_total_rows = (
        await db.execute(select(func.count()).select_from(LabelWeekly))
    ).scalar() or 0
    label_target_count = (
        await db.execute(select(func.count(func.distinct(LabelWeekly.target_name))))
    ).scalar() or 0
    label_week_range = await db.execute(
        select(func.min(LabelWeekly.week_ending), func.max(LabelWeekly.week_ending))
    )
    label_start, label_end = label_week_range.one()

    financial_total_rows = (
        await db.execute(select(func.count()).select_from(FinancialMetric))
    ).scalar() or 0
    financial_metric_count = (
        await db.execute(select(func.count(func.distinct(FinancialMetric.metric_name))))
    ).scalar() or 0
    financial_range = await db.execute(
        select(func.min(FinancialMetric.as_of_date), func.max(FinancialMetric.as_of_date))
    )
    financial_start, financial_end = financial_range.one()

    macro_total_rows = (
        await db.execute(select(func.count()).select_from(MacroIndicator))
    ).scalar() or 0
    macro_indicator_count = (
        await db.execute(select(func.count(func.distinct(MacroIndicator.indicator_code))))
    ).scalar() or 0
    macro_range = await db.execute(
        select(func.min(MacroIndicator.date), func.max(MacroIndicator.date))
    )
    macro_start, macro_end = macro_range.one()

    news_article_count = (
        await db.execute(select(func.count()).select_from(NewsArticle))
    ).scalar() or 0
    news_analysis_count = (
        await db.execute(select(func.count()).select_from(NewsAnalysis))
    ).scalar() or 0
    social_count = (
        await db.execute(select(func.count()).select_from(SocialSentiment))
    ).scalar() or 0
    news_range = await db.execute(
        select(func.min(NewsArticle.published_at), func.max(NewsArticle.published_at))
    )
    news_start, news_end = news_range.one()

    def _status_for(count: int, covered: int | None = None, total: int | None = None) -> str:
        if count == 0:
            return "Pasif"
        if covered is not None and total is not None and covered < total:
            return "Kismi"
        return "Aktif"

    data_sources = [
        {
            "name": "Fiyat Verisi",
            "source": "Yahoo Finance (yfinance)",
            "period": "Haftalik (Cuma kapanis)",
            "range": _range_display(price_start, price_end),
            "totalRecords": f"{price_total_rows:,} weekly rows",
            "coverage": f"{price_covered}/{len(active_stocks)} stocks with prices",
            "status": _status_for(price_total_rows, price_covered, len(active_stocks)),
        },
        {
            "name": "Feature'lar",
            "source": "FeatureEngineeringService",
            "period": "Haftalik",
            "range": _range_display(price_start, price_end),
            "totalRecords": f"{feature_total_rows:,} rows / {len(feature_names)} distinct features",
            "coverage": f"{len(feature_categories)} active feature families",
            "status": _status_for(feature_total_rows),
        },
        {
            "name": "Labels (Hedef)",
            "source": "Computed from forward returns",
            "period": "Haftalik",
            "range": _range_display(label_start, label_end),
            "totalRecords": f"{label_total_rows:,} rows",
            "coverage": f"{label_target_count} target variables",
            "status": _status_for(label_total_rows),
        },
        {
            "name": "Finansal Metrikler",
            "source": "Yahoo Finance / Manual",
            "period": "Ceyreklik/Yillik",
            "range": _range_display(financial_start, financial_end),
            "totalRecords": f"{financial_total_rows:,} rows",
            "coverage": f"{financial_metric_count} distinct metrics",
            "status": _status_for(financial_total_rows),
        },
        {
            "name": "Makro Veriler",
            "source": "FRED / Yahoo Finance",
            "period": "Haftalik/Gunluk",
            "range": _range_display(macro_start, macro_end),
            "totalRecords": f"{macro_total_rows:,} rows",
            "coverage": f"{macro_indicator_count} indicators",
            "status": _status_for(macro_total_rows),
        },
        {
            "name": "Haber/Sentiment",
            "source": "News + Social feeds",
            "period": "Gunluk/Haftalik",
            "range": _range_display(news_start, news_end),
            "totalRecords": f"{news_article_count:,} articles / {news_analysis_count:,} analyses / {social_count:,} social rows",
            "coverage": "Mixed news and social coverage",
            "status": _status_for(news_article_count + news_analysis_count + social_count),
        },
    ]

    redis_status = {"name": "Redis", "status": "Bilinmiyor", "detail": "Not checked"}
    try:
        import redis as redis_lib
        from app.config import settings

        redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True)
        redis_client.ping()
        redis_client.close()
        redis_status = {"name": "Redis", "status": "Aktif", "detail": settings.redis_url}
    except Exception as exc:
        redis_status = {"name": "Redis", "status": "Pasif", "detail": str(exc)}

    celery_status = {"name": "Celery Worker", "status": "Bilinmiyor", "detail": "No worker reply"}
    try:
        from app.tasks.celery_app import celery_app

        inspector = celery_app.control.inspect(timeout=1.0)
        reply = inspector.ping() if inspector else None
        if reply:
            celery_status = {
                "name": "Celery Worker",
                "status": "Aktif",
                "detail": ", ".join(sorted(reply.keys())),
            }
        else:
            celery_status = {
                "name": "Celery Worker",
                "status": "Kismi",
                "detail": "No worker replied within 1s",
            }
    except Exception as exc:
        celery_status = {"name": "Celery Worker", "status": "Pasif", "detail": str(exc)}

    system_status = [
        {"name": "Backend API", "status": "Aktif", "detail": "Summary endpoint responded"},
        {"name": "PostgreSQL", "status": "Aktif", "detail": f"{len(active_stocks)} active stocks indexed"},
        redis_status,
        celery_status,
    ]

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "stock_count": len(active_stocks),
        "price_coverage": {
            "total_rows": price_total_rows,
            "covered_stocks": price_covered,
            "range_start": price_start,
            "range_end": price_end,
            "details": price_details,
        },
        "feature_coverage": {
            "total_rows": feature_total_rows,
            "distinct_features": len(feature_names),
            "categories": feature_categories,
        },
        "label_coverage": {
            "total_rows": label_total_rows,
            "distinct_targets": label_target_count,
            "range_start": str(label_start) if label_start else None,
            "range_end": str(label_end) if label_end else None,
        },
        "data_sources": data_sources,
        "system_status": system_status,
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
        raise HTTPException(404, f"Ticker {ticker.upper()} not found")

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
