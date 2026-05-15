"""
Social sentiment ingestion.

Source: Reddit WSB/investing subreddits via pushshift.io (free, no auth needed)
        or yfinance .news as a proxy for attention signals.
        StockTwits requires registration; stubbed here with yfinance proxy.

Outputs stored in social_sentiment table (weekly aggregates).
"""
import logging
import hashlib
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.news import SocialSentiment

logger = logging.getLogger(__name__)


class SocialSentimentService:
    def __init__(self, session: Session):
        self.session = session
        self._vader = None

    def _get_vader(self):
        if self._vader is None:
            try:
                from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
                self._vader = SentimentIntensityAnalyzer()
            except ImportError:
                pass
        return self._vader

    def ingest_social_for_ticker(self, ticker: str) -> int:
        """
        Approximate social sentiment using yfinance news as a proxy.
        Real Reddit/StockTwits API requires credentials — this is a free-tier approximation.
        """
        stock = self.session.execute(select(Stock).where(Stock.ticker == ticker)).scalar_one_or_none()
        if not stock:
            return 0

        try:
            news_items = yf.Ticker(ticker).news or []
        except Exception as e:
            logger.warning(f"Social proxy fetch failed {ticker}: {e}")
            return 0

        vader = self._get_vader()
        if not vader or not news_items:
            return 0

        # Group by week
        week_data: dict[date, list[float]] = {}
        for item in news_items:
            headline = item.get("title", "") or ""
            pub_ts = item.get("providerPublishTime")
            if not pub_ts:
                continue
            pub_dt = datetime.fromtimestamp(pub_ts, tz=timezone.utc).date()
            # Round to Friday (week ending)
            days_to_friday = (4 - pub_dt.weekday()) % 7
            week_end = pub_dt + timedelta(days=days_to_friday)
            score = vader.polarity_scores(headline)["compound"]
            week_data.setdefault(week_end, []).append(score)

        if not week_data:
            return 0

        rows = []
        sorted_weeks = sorted(week_data.keys())
        mention_counts = [len(week_data[w]) for w in sorted_weeks]
        avg_mentions = sum(mention_counts) / len(mention_counts) if mention_counts else 1
        std_mentions = pd.Series(mention_counts).std() or 1

        for i, week in enumerate(sorted_weeks):
            scores = week_data[week]
            n = len(scores)
            avg_sentiment = sum(scores) / n
            momentum = (n - (mention_counts[i - 1] if i > 0 else n)) / max(mention_counts[i - 1], 1) if i > 0 else 0.0
            abnormal_attention = (n - avg_mentions) / std_mentions

            hype_risk = 1.0 if (n > avg_mentions + 2 * std_mentions and avg_sentiment > 0.3) else 0.0

            rows.append({
                "stock_id": stock.id,
                "week_ending": str(week),
                "mention_count": n,
                "mention_momentum": round(momentum, 4),
                "sentiment_polarity": round(avg_sentiment, 4),
                "hype_risk": hype_risk,
                "abnormal_attention": round(abnormal_attention, 4),
                "source": "yfinance_proxy",
            })

        stmt = pg_insert(SocialSentiment).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_id", "week_ending", "source"],
            set_={
                "mention_count": stmt.excluded.mention_count,
                "mention_momentum": stmt.excluded.mention_momentum,
                "sentiment_polarity": stmt.excluded.sentiment_polarity,
                "hype_risk": stmt.excluded.hype_risk,
                "abnormal_attention": stmt.excluded.abnormal_attention,
            },
        )
        self.session.execute(stmt)
        self.session.commit()
        logger.info(f"Social sentiment: {ticker} — {len(rows)} weeks")
        return len(rows)

    def get_weekly_social_features(self, stock_id: int, week_ending: date) -> dict[str, float]:
        """Return social features for the given week."""
        row = self.session.execute(
            select(SocialSentiment)
            .where(
                SocialSentiment.stock_id == stock_id,
                SocialSentiment.week_ending == str(week_ending),
            )
        ).scalar_one_or_none()

        if not row:
            return {
                "social_mention_count": 0.0,
                "social_mention_momentum": 0.0,
                "social_sentiment_polarity": 0.0,
                "social_hype_risk": 0.0,
                "social_abnormal_attention": 0.0,
            }

        return {
            "social_mention_count": float(row.mention_count or 0),
            "social_mention_momentum": float(row.mention_momentum or 0),
            "social_sentiment_polarity": float(row.sentiment_polarity or 0),
            "social_hype_risk": float(row.hype_risk or 0),
            "social_abnormal_attention": float(row.abnormal_attention or 0),
        }

    def run_all(self, tickers: list[str]) -> dict:
        results = {}
        for ticker in tickers:
            try:
                results[ticker] = self.ingest_social_for_ticker(ticker)
            except Exception as e:
                logger.error(f"Social sentiment failed {ticker}: {e}")
                results[ticker] = 0
        return results
