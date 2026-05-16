"""
Reddit social sentiment ingestion.

Sources:
  - Pushshift API  : tarihi veri (herhangi bir tarih aralığı)
  - PRAW (Reddit)  : güncel veri (son ~1000 post)

Subreddits: r/wallstreetbets, r/investing, r/stocks, r/options

Point-in-time guarantee:
  Her post, yayınlandığı haftanın Friday'ine (week_ending) atanır.
  DB'de (stock_id, week_ending, source="reddit") unique row olarak saklanır.
  Böylece geçmiş backtest'lerde sadece o tarihte mevcut olan veri kullanılır.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Iterator

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.data_source_health import record_source_health
from app.models.news import SocialSentiment
from app.models.stock import Stock
from app.services.social_sentiment_common import get_vader_analyzer, upsert_social_weekly_rows

logger = logging.getLogger(__name__)

SUBREDDITS = ["wallstreetbets", "investing", "stocks", "options"]
SOURCE = "reddit"

# Pushshift mirrors (try in order if one fails)
PUSHSHIFT_ENDPOINTS = [
    "https://api.pushshift.io/reddit/search/submission/",
    "https://api.pullpush.io/reddit/search/submission/",  # community mirror
]


def _to_unix(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _friday_of(d: date) -> date:
    """Round a date to the Friday of its week."""
    days_to_friday = (4 - d.weekday()) % 7
    return d + timedelta(days=days_to_friday)


def _vader_score(text: str, vader) -> float:
    try:
        return float(vader.polarity_scores(text)["compound"])
    except Exception:
        return 0.0


class RedditSentimentService:
    """Fetch Reddit mentions for a ticker and store weekly aggregates."""

    def __init__(self, session: Session):
        self.session = session
        self._praw = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest_ticker(
        self,
        ticker: str,
        start: date,
        end: date,
    ) -> int:
        """Fetch Reddit posts mentioning `ticker` between start and end.

        Uses Pushshift for historical data, PRAW as fallback for recent weeks.
        Returns number of weeks written.
        """
        stock = self.session.execute(
            select(Stock).where(Stock.ticker == ticker)
        ).scalar_one_or_none()
        if stock is None:
            return 0

        posts, source_used = self._fetch_best_posts(ticker, start, end)

        if not posts:
            logger.debug("Reddit: no posts for %s %s–%s", ticker, start, end)
            record_source_health(
                self.session,
                source_name="reddit",
                source_used=source_used,
                status="failure",
                target_ticker=ticker,
                week_ending=end,
                message="no reddit posts found",
                details={"start": str(start), "end": str(end)},
            )
            return 0

        vader = get_vader_analyzer()
        week_data: dict[date, list[float]] = {}
        for post in posts:
            text = (post.get("title") or "") + " " + (post.get("selftext") or "")
            created_utc = post.get("created_utc", 0)
            try:
                pub_date = datetime.fromtimestamp(float(created_utc), tz=timezone.utc).date()
            except (ValueError, OSError):
                continue

            # Only keep posts in the requested range
            if pub_date < start or pub_date > end:
                continue

            week_end = _friday_of(pub_date)
            score = _vader_score(text, vader)
            week_data.setdefault(week_end, []).append(score)

        if not week_data:
            return 0

        written = upsert_social_weekly_rows(
            self.session,
            stock_id=stock.id,
            week_data=week_data,
            source=SOURCE,
            source_used=source_used or SOURCE,
        )
        record_source_health(
            self.session,
            source_name="reddit",
            source_used=source_used or SOURCE,
            status="success",
            target_ticker=ticker,
            week_ending=end,
            message=f"wrote {written} weekly rows",
            details={"start": str(start), "end": str(end)},
        )
        return written

    def backfill(
        self,
        tickers: list[str],
        start: date,
        end: date,
        delay_sec: float = 1.0,
    ) -> dict[str, int]:
        """Backfill historical Reddit data for all tickers in a date range."""
        results: dict[str, int] = {}
        for ticker in tickers:
            try:
                n = self.ingest_ticker(ticker, start, end)
                results[ticker] = n
                logger.info("Reddit backfill: %s → %d weeks", ticker, n)
                time.sleep(delay_sec)
            except Exception as exc:
                logger.warning("Reddit backfill failed %s: %s", ticker, exc)
                results[ticker] = 0
        return results

    def ingest_recent(self, tickers: list[str]) -> dict[str, int]:
        """Ingest last 4 weeks of Reddit data for all tickers."""
        end = date.today()
        start = end - timedelta(weeks=4)
        results: dict[str, int] = {}
        for ticker in tickers:
            try:
                results[ticker] = self.ingest_ticker(ticker, start, end)
            except Exception as exc:
                logger.warning("Reddit recent ingest failed %s: %s", ticker, exc)
                results[ticker] = 0
        return results

    def get_weekly_features(self, stock_id: int, week_ending: date) -> dict[str, float]:
        """Return aggregated Reddit features for this stock/week (PIT safe)."""
        row = self.session.execute(
            select(SocialSentiment).where(
                SocialSentiment.stock_id == stock_id,
                SocialSentiment.week_ending == str(week_ending),
                SocialSentiment.source == SOURCE,
            )
        ).scalar_one_or_none()

        if row is None:
            return {
                "reddit_mention_count": 0.0,
                "reddit_mention_momentum": 0.0,
                "reddit_sentiment_polarity": 0.0,
                "reddit_hype_risk": 0.0,
                "reddit_abnormal_attention": 0.0,
            }

        return {
            "reddit_mention_count": float(row.mention_count or 0),
            "reddit_mention_momentum": float(row.mention_momentum or 0),
            "reddit_sentiment_polarity": float(row.sentiment_polarity or 0),
            "reddit_hype_risk": float(row.hype_risk or 0),
            "reddit_abnormal_attention": float(row.abnormal_attention or 0),
        }

    # ------------------------------------------------------------------
    # Pushshift
    # ------------------------------------------------------------------

    def _fetch_best_posts(
        self,
        ticker: str,
        start: date,
        end: date,
    ) -> tuple[list[dict], str | None]:
        """Try Pushshift, then PRAW month/year fallbacks."""
        posts = list(self._fetch_pushshift(ticker, start, end))
        if posts:
            record_source_health(
                self.session,
                source_name="reddit_pushshift",
                source_used="pushshift",
                status="success",
                target_ticker=ticker,
                week_ending=end,
                message=f"fetched {len(posts)} posts",
                details={"endpoint": "pushshift"},
            )
            return posts, "pushshift"

        record_source_health(
            self.session,
            source_name="reddit_pushshift",
            source_used=None,
            status="failure",
            target_ticker=ticker,
            week_ending=end,
            message="pushshift unavailable or empty",
            details={"start": str(start), "end": str(end)},
        )

        for time_filter in ("month", "year"):
            posts = list(self._fetch_praw(ticker, time_filter=time_filter))
            if posts:
                source_used = f"praw_{time_filter}"
                record_source_health(
                    self.session,
                    source_name="reddit_praw",
                    source_used=source_used,
                    status="success",
                    target_ticker=ticker,
                    week_ending=end,
                    message=f"fetched {len(posts)} posts",
                    details={"time_filter": time_filter},
                )
                return posts, source_used

        record_source_health(
            self.session,
            source_name="reddit_praw",
            source_used=None,
            status="failure",
            target_ticker=ticker,
            week_ending=end,
            message="praw month/year fallback exhausted",
            details={"start": str(start), "end": str(end)},
        )
        return [], None

    def _fetch_pushshift(
        self,
        ticker: str,
        start: date,
        end: date,
        batch_size: int = 100,
    ) -> Iterator[dict]:
        """Fetch posts from Pushshift in batches. Yields raw post dicts."""
        params = {
            "q": f'"{ticker}"',
            "subreddit": ",".join(SUBREDDITS),
            "after": _to_unix(start),
            "before": _to_unix(end),
            "size": batch_size,
            "sort": "asc",
            "sort_type": "created_utc",
            "fields": "title,selftext,created_utc,score,subreddit",
        }

        for endpoint in PUSHSHIFT_ENDPOINTS:
            try:
                fetched = 0
                after = _to_unix(start)
                while True:
                    params["after"] = after
                    resp = requests.get(endpoint, params=params, timeout=15)
                    if resp.status_code != 200:
                        logger.debug("Pushshift %s returned %d", endpoint, resp.status_code)
                        break
                    data = resp.json().get("data", [])
                    if not data:
                        break
                    for post in data:
                        yield post
                        fetched += 1
                    # Next page: after = last post's timestamp
                    after = int(data[-1]["created_utc"]) + 1
                    if len(data) < batch_size:
                        break
                    time.sleep(0.5)

                if fetched > 0:
                    logger.debug("Pushshift: %s → %d posts from %s", ticker, fetched, endpoint)
                    return  # success, don't try next mirror
            except requests.exceptions.RequestException as exc:
                logger.debug("Pushshift endpoint %s failed: %s", endpoint, exc)
                continue

    # ------------------------------------------------------------------
    # PRAW (recent data fallback)
    # ------------------------------------------------------------------

    def _fetch_praw(self, ticker: str, limit: int = 500, time_filter: str = "month") -> Iterator[dict]:
        """Fetch recent posts via PRAW. Falls back from month to year if needed."""
        praw = self._get_praw()
        if praw is None:
            return

        for subreddit_name in SUBREDDITS:
            try:
                sub = praw.subreddit(subreddit_name)
                for post in sub.search(
                    f'"{ticker}"',
                    sort="new",
                    time_filter=time_filter,
                    limit=limit // len(SUBREDDITS),
                ):
                    yield {
                        "title": post.title,
                        "selftext": post.selftext,
                        "created_utc": post.created_utc,
                        "score": post.score,
                        "subreddit": subreddit_name,
                    }
            except Exception as exc:
                logger.debug("PRAW subreddit %s failed: %s", subreddit_name, exc)

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    def _get_praw(self):
        if self._praw is not None:
            return self._praw
        from app.config import settings
        if not settings.reddit_client_id or not settings.reddit_client_secret:
            logger.debug("Reddit API credentials not configured; PRAW unavailable")
            return None
        try:
            import praw
            self._praw = praw.Reddit(
                client_id=settings.reddit_client_id,
                client_secret=settings.reddit_client_secret,
                user_agent=settings.reddit_user_agent,
            )
            return self._praw
        except Exception as exc:
            logger.warning("PRAW init failed: %s", exc)
            return None
