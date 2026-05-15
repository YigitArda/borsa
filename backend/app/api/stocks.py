from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.stock import Stock, StockUniverseSnapshot
from app.models.price import PriceWeekly
from app.models.feature import FeatureWeekly, LabelWeekly
from app.models.prediction import WeeklyPrediction
from app.models.financial import FinancialMetric
from app.models.news import NewsArticle, NewsAnalysis

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get("/universe/{index_name}/{snapshot_date}")
async def get_universe_snapshot(index_name: str, snapshot_date: str, db: AsyncSession = Depends(get_db)):
    """Return universe membership as of a given date (or closest prior snapshot)."""
    rows = await db.execute(
        select(StockUniverseSnapshot)
        .where(
            StockUniverseSnapshot.index_name == index_name,
            StockUniverseSnapshot.snapshot_date <= snapshot_date,
        )
        .order_by(StockUniverseSnapshot.snapshot_date.desc())
        .limit(500)
    )
    snaps = rows.scalars().all()
    if not snaps:
        # Fall back to current active stocks
        active = await db.execute(select(Stock).where(Stock.is_active == True))
        return {
            "index_name": index_name,
            "snapshot_date": snapshot_date,
            "source": "active_stocks_fallback",
            "tickers": [s.ticker for s in active.scalars().all()],
        }
    # Most recent snapshot date
    latest_date = str(snaps[0].snapshot_date)
    tickers = [s.ticker for s in snaps if str(s.snapshot_date) == latest_date]
    return {"index_name": index_name, "snapshot_date": latest_date, "tickers": tickers}


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
        "industry": stock.industry,
        "total_weeks_analyzed": total,
        "weeks_with_2pct_return": positive,
        "historical_hit_rate": round(positive / total, 4) if total > 0 else None,
    }


@router.get("/{ticker}/research")
async def get_research(ticker: str, db: AsyncSession = Depends(get_db)):
    """Full research view: return distribution, best/worst weeks, technicals, financials, news."""
    result = await db.execute(select(Stock).where(Stock.ticker == ticker.upper()))
    stock = result.scalar_one_or_none()
    if not stock:
        raise HTTPException(404, f"Stock {ticker} not found")

    # Weekly returns (all time)
    prices_q = await db.execute(
        select(PriceWeekly)
        .where(PriceWeekly.stock_id == stock.id)
        .order_by(PriceWeekly.week_ending)
    )
    price_rows = prices_q.scalars().all()
    weekly_returns = [
        {"week_ending": str(r.week_ending), "return": r.weekly_return, "volume": r.volume}
        for r in price_rows if r.weekly_return is not None
    ]

    # Best / worst weeks
    sorted_by_ret = sorted(weekly_returns, key=lambda x: x["return"])
    worst_weeks = sorted_by_ret[:10]
    best_weeks = sorted_by_ret[-10:][::-1]

    # Return distribution buckets
    import numpy as np
    returns_arr = [x["return"] for x in weekly_returns]
    if returns_arr:
        hist, edges = np.histogram(returns_arr, bins=20)
        distribution = [
            {"bucket": round(float(edges[i]), 4), "count": int(hist[i])}
            for i in range(len(hist))
        ]
    else:
        distribution = []

    # Risk metrics
    if returns_arr:
        arr = np.array(returns_arr)
        avg_return = float(arr.mean())
        vol = float(arr.std())
        sharpe = float(arr.mean() / arr.std() * (52 ** 0.5)) if arr.std() > 0 else 0.0
        skewness = float(((arr - arr.mean()) ** 3).mean() / (arr.std() ** 3 + 1e-10))
        win_rate = float((arr > 0).mean())
        max_dd = 0.0
        equity = 1.0
        peak = 1.0
        for r in returns_arr:
            equity *= (1 + r)
            peak = max(peak, equity)
            max_dd = min(max_dd, (equity - peak) / peak)
    else:
        avg_return = vol = sharpe = skewness = win_rate = max_dd = 0.0

    # Latest technical features
    from sqlalchemy import func
    latest_week_q = await db.execute(
        select(func.max(FeatureWeekly.week_ending)).where(FeatureWeekly.stock_id == stock.id)
    )
    latest_week = latest_week_q.scalar()
    technicals = {}
    if latest_week:
        feat_q = await db.execute(
            select(FeatureWeekly).where(
                FeatureWeekly.stock_id == stock.id,
                FeatureWeekly.week_ending == latest_week,
                FeatureWeekly.feature_name.in_([
                    "rsi_14", "macd", "macd_hist", "volume_zscore",
                    "bb_position", "price_to_sma50", "price_to_sma200",
                    "return_1w", "return_4w", "return_12w",
                    "high_52w_distance", "low_52w_distance",
                    "trend_strength", "realized_vol", "atr_14",
                ])
            )
        )
        technicals = {r.feature_name: r.value for r in feat_q.scalars().all()}

    # Latest financials
    fin_q = await db.execute(
        select(FinancialMetric)
        .where(FinancialMetric.stock_id == stock.id)
        .order_by(FinancialMetric.as_of_date.desc())
    )
    seen_fin: dict = {}
    for r in fin_q.scalars().all():
        if r.metric_name not in seen_fin:
            seen_fin[r.metric_name] = r.value
    key_financials = {k: seen_fin.get(k) for k in [
        "pe_ratio", "forward_pe", "price_to_book", "ev_to_ebitda",
        "gross_margin", "operating_margin", "net_margin",
        "roe", "roa", "revenue_growth", "earnings_growth",
        "debt_to_equity", "current_ratio", "beta", "market_cap",
    ] if seen_fin.get(k) is not None}

    # Recent news (join analysis → article via stock_id)
    news_q = await db.execute(
        select(NewsArticle, NewsAnalysis)
        .join(NewsAnalysis, NewsAnalysis.news_id == NewsArticle.id)
        .where(NewsAnalysis.stock_id == stock.id)
        .order_by(NewsArticle.published_at.desc())
        .limit(10)
    )
    news = [
        {
            "headline": article.headline,
            "published_at": str(article.published_at) if article.published_at else None,
            "source": article.source,
            "sentiment_score": analysis.sentiment_score,
            "sentiment_label": analysis.sentiment_label,
            "is_earnings": analysis.is_earnings,
            "is_analyst_action": analysis.is_analyst_action,
        }
        for article, analysis in news_q.all()
    ]

    # Signal history (last 12 predictions)
    sig_q = await db.execute(
        select(WeeklyPrediction)
        .where(WeeklyPrediction.stock_id == stock.id)
        .order_by(WeeklyPrediction.week_ending.desc())
        .limit(12)
    )
    signals = [
        {"week_ending": str(s.week_ending), "probability": s.probability, "rank": s.rank}
        for s in sig_q.scalars().all()
    ]

    return {
        "ticker": stock.ticker,
        "name": stock.name,
        "sector": stock.sector,
        "industry": stock.industry,
        "risk": {
            "avg_weekly_return": round(avg_return, 4),
            "weekly_volatility": round(vol, 4),
            "annualized_sharpe": round(sharpe, 4),
            "skewness": round(skewness, 4),
            "win_rate": round(win_rate, 4),
            "max_drawdown": round(max_dd, 4),
            "total_weeks": len(returns_arr),
        },
        "distribution": distribution,
        "best_weeks": best_weeks,
        "worst_weeks": worst_weeks,
        "technicals": technicals,
        "financials": key_financials,
        "news": news,
        "signals": signals,
    }
