"""
Social sentiment orchestrator.

Sources (in priority order):
  1. Reddit  — real data via Pushshift (historical) + PRAW (recent)
  2. Twitter — real data via X API v2 (Pro = full archive; Free = last 7 days)
  3. yfinance_proxy — fallback if neither Reddit nor Twitter has data

Point-in-time guarantee:
  Tüm kaynaklar, tweet/post yayın tarihini o haftanın Friday'ine (week_ending)
  atayarak saklar. `get_weekly_social_features` sadece istenen week_ending'i
  döndürür — backtest sırasında gelecek bilgi sızıntısı olmaz.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.news import SocialSentiment

logger = logging.getLogger(__name__)


class _FallbackSentimentIntensityAnalyzer:
    POSITIVE_WORDS = {
        "beat", "beats", "bull", "bullish", "growth", "gain", "gains", "good", "great",
        "improve", "improves", "improved", "positive", "record", "strong", "up", "win",
    }
    NEGATIVE_WORDS = {
        "bear", "bearish", "bad", "decline", "declines", "drop", "drops", "fall", "falls",
        "loss", "negative", "risk", "weak", "down", "miss", "misses", "warn", "warning",
    }

    def polarity_scores(self, text: str) -> dict[str, float]:
        tokens = re.findall(r"[a-z']+", text.lower())
        if not tokens:
            return {"compound": 0.0}
        pos = sum(token in self.POSITIVE_WORDS for token in tokens)
        neg = sum(token in self.NEGATIVE_WORDS for token in tokens)
        total = pos + neg
        compound = 0.0 if total == 0 else (pos - neg) / total
        return {"compound": max(-1.0, min(1.0, compound))}


class SocialSentimentService:
    """Orchestrates Reddit, Twitter, and yfinance-proxy ingestion."""

    def __init__(self, session: Session):
        self.session = session
        self._vader = None

    # ------------------------------------------------------------------
    # Recent ingestion (weekly pipeline hook)
    # ------------------------------------------------------------------

    def run_all(self, tickers: list[str]) -> dict[str, int]:
        """Ingest recent social data from all configured sources."""
        results: dict[str, int] = {}

        # Reddit — last 4 weeks via PRAW / Pushshift
        try:
            from app.services.reddit_sentiment import RedditSentimentService
            reddit = RedditSentimentService(self.session)
            reddit_results = reddit.ingest_recent(tickers)
            for t, n in reddit_results.items():
                results[t] = results.get(t, 0) + n
            logger.info("Reddit ingest done: %d tickers", len(reddit_results))
        except Exception as exc:
            logger.warning("Reddit ingest skipped: %s", exc)

        # Twitter — last 7 days (free tier)
        try:
            from app.services.twitter_sentiment import TwitterSentimentService
            twitter = TwitterSentimentService(self.session)
            twitter_results = twitter.ingest_recent(tickers)
            for t, n in twitter_results.items():
                results[t] = results.get(t, 0) + n
            logger.info("Twitter ingest done: %d tickers", len(twitter_results))
        except Exception as exc:
            logger.warning("Twitter ingest skipped: %s", exc)

        # yfinance proxy — only for tickers with no real data this week
        _friday = self._this_friday()
        for ticker in tickers:
            if results.get(ticker, 0) == 0:
                try:
                    n = self._ingest_yfinance_proxy(ticker, _friday)
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
        """Backfill Reddit + Twitter for a historical date range.

        Twitter backfill only works with a Pro/Academic bearer token.
        """
        from app.services.reddit_sentiment import RedditSentimentService
        from app.services.twitter_sentiment import TwitterSentimentService

        reddit = RedditSentimentService(self.session)
        twitter = TwitterSentimentService(self.session)

        reddit_results = reddit.backfill(tickers, start, end, delay_sec=delay_sec)
        twitter_results = twitter.backfill(tickers, start, end, delay_sec=delay_sec)

        combined: dict[str, dict[str, int]] = {}
        for t in tickers:
            combined[t] = {
                "reddit": reddit_results.get(t, 0),
                "twitter": twitter_results.get(t, 0),
            }

        return combined

    # ------------------------------------------------------------------
    # Feature retrieval (PIT safe — called from feature engineering)
    # ------------------------------------------------------------------

    def get_weekly_social_features(self, stock_id: int, week_ending: date) -> dict[str, float]:
        """Aggregate social features across all sources for a given week.

        PIT safe: reads only rows with the exact week_ending, which were
        written from data that existed at or before that date.
        """
        rows = self.session.execute(
            select(SocialSentiment).where(
                SocialSentiment.stock_id == stock_id,
                SocialSentiment.week_ending == str(week_ending),
            )
        ).scalars().all()

        if not rows:
            return self._zero_features()

        # Average across sources, weighted by mention count
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

        vader = self._get_vader()
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

        sorted_weeks = sorted(week_data.keys())
        mention_counts = [len(week_data[w]) for w in sorted_weeks]
        avg_mentions = sum(mention_counts) / max(len(mention_counts), 1)
        import numpy as np
        std_mentions = float(np.std(mention_counts)) or 1.0

        rows = []
        for i, week in enumerate(sorted_weeks):
            scores = week_data[week]
            n = len(scores)
            avg_sentiment = sum(scores) / max(n, 1)
            prev_n = mention_counts[i - 1] if i > 0 else n
            momentum = (n - prev_n) / max(prev_n, 1)
            abnormal = (n - avg_mentions) / std_mentions
            hype_risk = 1.0 if (n > avg_mentions + 2 * std_mentions and avg_sentiment > 0.3) else 0.0
            rows.append({
                "stock_id": stock.id,
                "week_ending": str(week),
                "mention_count": n,
                "mention_momentum": round(momentum, 4),
                "sentiment_polarity": round(avg_sentiment, 4),
                "hype_risk": hype_risk,
                "abnormal_attention": round(abnormal, 4),
                "source": "yfinance_proxy",
            })

        if not rows:
            return 0

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
        return len(rows)

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

    def _get_vader(self):
        if self._vader is None:
            try:
                from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
                self._vader = SentimentIntensityAnalyzer()
            except ImportError:
                logger.warning("vaderSentiment not installed; using fallback lexicon scorer")
                self._vader = _FallbackSentimentIntensityAnalyzer()
        return self._vader
