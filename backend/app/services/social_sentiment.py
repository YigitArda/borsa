"""
Social sentiment orchestrator.

Sources (in priority order):
  1. Reddit        - Pushshift historical + PRAW recent fallback
  2. StockTwits    - free symbol-stream fallback
  3. Twitter       - X API v2 full archive / recent search
  4. yfinance_proxy - fallback if none of the above has data

Point-in-time guarantee:
  Every message is assigned to the Friday of its own week (week_ending).
  `get_weekly_social_features` only reads the exact requested week_ending,
  so backtests do not see future social data.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.news import SocialSentiment
from app.models.stock import Stock
from app.services.social_sentiment_common import get_vader_analyzer, upsert_social_weekly_rows

logger = logging.getLogger(__name__)


class SocialSentimentService:
    """Orchestrates Reddit, StockTwits, Twitter, and yfinance-proxy ingestion."""

    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------
    # Recent ingestion (weekly pipeline hook)
    # ------------------------------------------------------------------

    def run_all(self, tickers: list[str]) -> dict[str, int]:
        """Ingest recent social data from all configured sources."""
        results: dict[str, int] = {}

        # Reddit - last 4 weeks via PRAW / Pushshift
        try:
            from app.services.reddit_sentiment import RedditSentimentService
            reddit = RedditSentimentService(self.session)
            reddit_results = reddit.ingest_recent(tickers)
            for t, n in reddit_results.items():
                results[t] = results.get(t, 0) + n
            logger.info("Reddit ingest done: %d tickers", len(reddit_results))
        except Exception as exc:
            logger.warning("Reddit ingest skipped: %s", exc)

        # StockTwits - free symbol stream fallback
        try:
            from app.services.stocktwits_sentiment import StocktwitsSentimentService
            stocktwits = StocktwitsSentimentService(self.session)
            stocktwits_results = stocktwits.ingest_recent(tickers)
            for t, n in stocktwits_results.items():
                results[t] = results.get(t, 0) + n
            logger.info("StockTwits ingest done: %d tickers", len(stocktwits_results))
        except Exception as exc:
            logger.warning("StockTwits ingest skipped: %s", exc)

        # Twitter - last 7 days (free tier) or archive if bearer token exists
        try:
            from app.services.twitter_sentiment import TwitterSentimentService
            twitter = TwitterSentimentService(self.session)
            twitter_results = twitter.ingest_recent(tickers)
            for t, n in twitter_results.items():
                results[t] = results.get(t, 0) + n
            logger.info("Twitter ingest done: %d tickers", len(twitter_results))
        except Exception as exc:
            logger.warning("Twitter ingest skipped: %s", exc)

        # yfinance proxy - only for tickers with no real data this week
        this_friday = self._this_friday()
        for ticker in tickers:
            if results.get(ticker, 0) == 0:
                try:
                    n = self._ingest_yfinance_proxy(ticker, this_friday)
                    results[ticker] = n
                except Exception as exc:
                    logger.debug("yfinance proxy failed %s: %s", ticker, exc)
                    results[ticker] = 0

        return results

    # ------------------------------------------------------------------
    # Historical backfill (triggered manually or via API)
    # ------------------------------------------------------------------

    def backfill(
        self,
        tickers: list[str],
        start: date,
        end: date,
        delay_sec: float = 1.0,
    ) -> dict[str, dict[str, int]]:
        """Backfill Reddit + StockTwits + Twitter for a historical date range."""
        from app.services.reddit_sentiment import RedditSentimentService
        from app.services.stocktwits_sentiment import StocktwitsSentimentService
        from app.services.twitter_sentiment import TwitterSentimentService

        reddit = RedditSentimentService(self.session)
        stocktwits = StocktwitsSentimentService(self.session)
        twitter = TwitterSentimentService(self.session)

        reddit_results = reddit.backfill(tickers, start, end, delay_sec=delay_sec)
        stocktwits_results = stocktwits.backfill(tickers, start, end, delay_sec=delay_sec)
        twitter_results = twitter.backfill(tickers, start, end, delay_sec=delay_sec)

        combined: dict[str, dict[str, int]] = {}
        for t in tickers:
            combined[t] = {
                "reddit": reddit_results.get(t, 0),
                "stocktwits": stocktwits_results.get(t, 0),
                "twitter": twitter_results.get(t, 0),
            }

        return combined

    # ------------------------------------------------------------------
    # Feature retrieval (PIT safe - called from feature engineering)
    # ------------------------------------------------------------------

    def get_weekly_social_features(self, stock_id: int, week_ending: date) -> dict[str, float]:
        """Aggregate social features across all sources for a given week."""
        rows = self.session.execute(
            select(SocialSentiment).where(
                SocialSentiment.stock_id == stock_id,
                SocialSentiment.week_ending == str(week_ending),
            )
        ).scalars().all()

        if not rows:
            return self._zero_features()

        total_mentions = sum(r.mention_count or 0 for r in rows)
        if total_mentions == 0:
            return self._zero_features()

        def wavg(attr: str) -> float:
            return sum((r.mention_count or 0) * float(getattr(r, attr) or 0) for r in rows) / total_mentions

        return {
            "social_mention_count": float(total_mentions),
            "social_mention_momentum": wavg("mention_momentum"),
            "social_sentiment_polarity": wavg("sentiment_polarity"),
            "social_hype_risk": max(float(r.hype_risk or 0) for r in rows),
            "social_abnormal_attention": wavg("abnormal_attention"),
        }

    # ------------------------------------------------------------------
    # yfinance proxy (fallback for tickers with no real data)
    # ------------------------------------------------------------------

    def _ingest_yfinance_proxy(self, ticker: str, this_friday: date) -> int:
        stock = self.session.execute(
            select(Stock).where(Stock.ticker == ticker)
        ).scalar_one_or_none()
        if not stock:
            return 0

        try:
            news_items = yf.Ticker(ticker).news or []
        except Exception as exc:
            logger.debug("yfinance proxy fetch failed %s: %s", ticker, exc)
            return 0

        vader = get_vader_analyzer()
        week_data: dict[date, list[float]] = {}
        for item in news_items:
            headline = item.get("title", "") or ""
            pub_ts = item.get("providerPublishTime")
            if not pub_ts:
                continue
            pub_dt = datetime.fromtimestamp(pub_ts, tz=timezone.utc).date()
            days_to_friday = (4 - pub_dt.weekday()) % 7
            week_end = pub_dt + timedelta(days=days_to_friday)
            score = vader.polarity_scores(headline)["compound"]
            week_data.setdefault(week_end, []).append(score)

        if not week_data:
            return 0

        return upsert_social_weekly_rows(
            self.session,
            stock_id=stock.id,
            week_data=week_data,
            source="yfinance_proxy",
            source_used="yfinance_proxy",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _this_friday() -> date:
        today = date.today()
        days_to_friday = (4 - today.weekday()) % 7
        return today + timedelta(days=days_to_friday)

    @staticmethod
    def _zero_features() -> dict[str, float]:
        return {
            "social_mention_count": 0.0,
            "social_mention_momentum": 0.0,
            "social_sentiment_polarity": 0.0,
            "social_hype_risk": 0.0,
            "social_abnormal_attention": 0.0,
        }
