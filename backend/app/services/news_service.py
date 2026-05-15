"""
News ingestion + sentiment analysis via VADER.

Source: yfinance .news property (free, no API key needed).
Sentiment: VADER (vaderSentiment) — lightweight, no GPU needed.
Category flags: keyword-based detection.
"""
import hashlib
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.news import NewsArticle, NewsAnalysis

logger = logging.getLogger(__name__)

# Keyword sets for category detection
EARNINGS_KW = {"earnings", "eps", "revenue", "guidance", "quarterly", "results", "beat", "miss", "profit"}
LEGAL_KW = {"lawsuit", "sue", "sec", "investigation", "fine", "penalty", "fraud", "settlement", "doj", "ftc"}
PRODUCT_KW = {"launch", "product", "release", "unveil", "announce", "new model", "iphone", "gpt", "chip", "partnership"}
ANALYST_KW = {"upgrade", "downgrade", "price target", "buy", "sell", "overweight", "underweight", "outperform", "analyst"}
MGMT_KW = {"ceo", "cfo", "resign", "appoint", "hire", "fired", "step down", "executive", "board"}


def _classify_headline(text: str) -> dict[str, bool]:
    t = text.lower()
    return {
        "is_earnings": bool(EARNINGS_KW & set(re.findall(r"\w+", t))),
        "is_legal": bool(LEGAL_KW & set(re.findall(r"\w+", t))),
        "is_product_launch": bool(PRODUCT_KW & set(re.findall(r"\w+", t))),
        "is_analyst_action": bool(ANALYST_KW & set(re.findall(r"\w+", t))),
        "is_management_change": bool(MGMT_KW & set(re.findall(r"\w+", t))),
    }


class NewsService:
    def __init__(self, session: Session):
        self.session = session
        self._vader = None

    def _get_vader(self):
        if self._vader is None:
            try:
                from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
                self._vader = SentimentIntensityAnalyzer()
            except ImportError:
                logger.warning("vaderSentiment not installed; sentiment will be None")
        return self._vader

    def ingest_news_for_ticker(self, ticker: str) -> int:
        import yfinance as yf

        stock = self.session.execute(select(Stock).where(Stock.ticker == ticker)).scalar_one_or_none()
        if not stock:
            return 0

        try:
            news_items = yf.Ticker(ticker).news or []
        except Exception as e:
            logger.error(f"News fetch failed for {ticker}: {e}")
            return 0

        vader = self._get_vader()
        inserted = 0

        for item in news_items:
            headline = item.get("title", "") or ""
            url = item.get("link", "") or item.get("url", "") or headline
            url_hash = hashlib.sha256(url.encode()).hexdigest()[:64]

            # Check if article already exists
            existing = self.session.execute(
                select(NewsArticle).where(NewsArticle.url_hash == url_hash)
            ).scalar_one_or_none()

            pub_ts = item.get("providerPublishTime")
            pub_dt = datetime.fromtimestamp(pub_ts, tz=timezone.utc) if pub_ts else None

            if not existing:
                article = NewsArticle(
                    url_hash=url_hash,
                    published_at=pub_dt,
                    source=item.get("publisher"),
                    headline=headline[:500],
                    ticker_mentions=[ticker],
                )
                self.session.add(article)
                self.session.flush()
                article_id = article.id
            else:
                article_id = existing.id

            # Sentiment
            sentiment_score = None
            sentiment_label = "neutral"
            if vader and headline:
                scores = vader.polarity_scores(headline)
                sentiment_score = scores["compound"]
                sentiment_label = "positive" if sentiment_score > 0.05 else "negative" if sentiment_score < -0.05 else "neutral"

            cats = _classify_headline(headline)

            # Upsert analysis
            existing_analysis = self.session.execute(
                select(NewsAnalysis).where(
                    NewsAnalysis.news_id == article_id,
                    NewsAnalysis.stock_id == stock.id,
                )
            ).scalar_one_or_none()

            if not existing_analysis:
                analysis = NewsAnalysis(
                    news_id=article_id,
                    stock_id=stock.id,
                    sentiment_score=sentiment_score,
                    sentiment_label=sentiment_label,
                    relevance_score=1.0,
                    **cats,
                )
                self.session.add(analysis)
                inserted += 1

        self.session.commit()
        logger.info(f"News: {ticker} — {inserted} new articles analyzed")
        return inserted

    def get_weekly_news_features(self, stock_id: int, week_ending: "date") -> dict[str, float]:
        """Aggregate news features for the week prior to week_ending."""
        from datetime import timedelta
        import numpy as np

        week_start = week_ending - timedelta(days=7)

        analyses = self.session.execute(
            select(NewsAnalysis, NewsArticle)
            .join(NewsArticle, NewsAnalysis.news_id == NewsArticle.id)
            .where(
                NewsAnalysis.stock_id == stock_id,
                NewsArticle.published_at >= week_start,
                NewsArticle.published_at < week_ending,
            )
        ).all()

        if not analyses:
            return {
                "news_sentiment_score": 0.0,
                "news_volume": 0.0,
                "news_positive_count": 0.0,
                "news_negative_count": 0.0,
                "news_earnings_flag": 0.0,
                "news_legal_flag": 0.0,
                "news_product_flag": 0.0,
                "news_analyst_flag": 0.0,
                "news_mgmt_flag": 0.0,
                "news_recency_impact": 0.0,
            }

        sentiments = [a.sentiment_score or 0.0 for a, _ in analyses]
        n = len(analyses)

        # Recency-weighted sentiment (more recent = higher weight)
        from datetime import datetime as dt
        now = dt.now(tz=timezone.utc)
        weights = []
        for _, article in analyses:
            if article.published_at:
                age_hours = max((now - article.published_at).total_seconds() / 3600, 1)
                weights.append(1 / age_hours)
            else:
                weights.append(0.01)

        total_w = sum(weights) or 1
        recency_impact = sum(s * w for s, (a, _) in zip(sentiments, zip(analyses, analyses)) for w in [weights[0]]) / total_w

        return {
            "news_sentiment_score": float(np.mean(sentiments)),
            "news_volume": float(n),
            "news_positive_count": float(sum(1 for a, _ in analyses if a.sentiment_label == "positive")),
            "news_negative_count": float(sum(1 for a, _ in analyses if a.sentiment_label == "negative")),
            "news_earnings_flag": float(any(a.is_earnings for a, _ in analyses)),
            "news_legal_flag": float(any(a.is_legal for a, _ in analyses)),
            "news_product_flag": float(any(a.is_product_launch for a, _ in analyses)),
            "news_analyst_flag": float(any(a.is_analyst_action for a, _ in analyses)),
            "news_mgmt_flag": float(any(a.is_management_change for a, _ in analyses)),
            "news_recency_impact": float(np.mean(sentiments)),  # simplified recency weighting
        }

    def run_all(self, tickers: list[str]) -> dict:
        results = {}
        for ticker in tickers:
            try:
                results[ticker] = self.ingest_news_for_ticker(ticker)
            except Exception as e:
                logger.error(f"News failed {ticker}: {e}")
                results[ticker] = 0
        return results
