"""
X / Twitter social sentiment ingestion.

API tiers:
  - Free (Bearer token only): recent search, last 7 days, up to 100 tweets/req
  - Pro/Academic: full-archive search (tweets/search/all), unlimited history

Point-in-time guarantee:
  Her tweet, yayınlandığı haftanın Friday'ine (week_ending) atanır.
  DB'de (stock_id, week_ending, source="twitter") unique row olarak saklanır.
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

SOURCE = "twitter"
SEARCH_TERMS = ['${ticker}', '#{ticker}', '"{ticker}"']  # format placeholders

# X API v2 endpoints
RECENT_SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"
FULL_ARCHIVE_URL = "https://api.twitter.com/2/tweets/search/all"

# Max results per page (API cap: 100 for recent, 500 for full-archive)
RECENT_PAGE_SIZE = 100
ARCHIVE_PAGE_SIZE = 500


def _friday_of(d: date) -> date:
    days_to_friday = (4 - d.weekday()) % 7
    return d + timedelta(days=days_to_friday)


def _vader_score(text: str, vader) -> float:
    try:
        return float(vader.polarity_scores(text)["compound"])
    except Exception:
        return 0.0


def _iso_date(d: date) -> str:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TwitterSentimentService:
    """Fetch X/Twitter mentions for a ticker and store weekly aggregates."""

    def __init__(self, session: Session, bearer_token: str | None = None):
        self.session = session
        self._bearer_token = bearer_token

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest_ticker(self, ticker: str, start: date, end: date) -> int:
        """Fetch tweets mentioning `ticker` between start and end.

        Uses full-archive search if available (Pro tier), falls back to
        recent-only search (free tier, last 7 days).
        Returns number of weeks written.
        """
        token = self._get_token()
        if not token:
            logger.debug("Twitter: no bearer token configured; skipping %s", ticker)
            record_source_health(
                self.session,
                source_name="twitter",
                source_used=None,
                status="skipped",
                target_ticker=ticker,
                week_ending=end,
                message="bearer token missing",
                details={"start": str(start), "end": str(end)},
            )
            return 0

        stock = self.session.execute(
            select(Stock).where(Stock.ticker == ticker)
        ).scalar_one_or_none()
        if stock is None:
            return 0

        # Try full-archive first; fall back to recent if 403 (tier restriction)
        posts = list(self._fetch_archive(ticker, start, end, token))
        source_used = "full_archive" if posts else None
        if not posts:
            # Only useful if date range overlaps last 7 days
            recent_cutoff = date.today() - timedelta(days=7)
            if end >= recent_cutoff:
                posts = list(self._fetch_recent(ticker, max(start, recent_cutoff), end, token))
                if posts:
                    source_used = "recent"

        if not posts:
            logger.debug("Twitter: no tweets for %s %s–%s", ticker, start, end)
            record_source_health(
                self.session,
                source_name="twitter",
                source_used=None,
                status="failure",
                target_ticker=ticker,
                week_ending=end,
                message="no tweets found",
                details={"start": str(start), "end": str(end)},
            )
            return 0

        vader = get_vader_analyzer()
        week_data: dict[date, list[float]] = {}
        for post in posts:
            text = post.get("text", "")
            created_at = post.get("created_at", "")
            try:
                pub_date = datetime.fromisoformat(created_at.replace("Z", "+00:00")).date()
            except (ValueError, AttributeError):
                continue

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
            source_used=source_used or "twitter",
        )
        record_source_health(
            self.session,
            source_name="twitter",
            source_used=source_used or "twitter",
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
        """Backfill historical X data for all tickers in a date range.

        Requires Pro/Academic tier for dates older than 7 days.
        """
        results: dict[str, int] = {}
        for ticker in tickers:
            try:
                n = self.ingest_ticker(ticker, start, end)
                results[ticker] = n
                logger.info("Twitter backfill: %s → %d weeks", ticker, n)
                time.sleep(delay_sec)
            except Exception as exc:
                logger.warning("Twitter backfill failed %s: %s", ticker, exc)
                results[ticker] = 0
        return results

    def ingest_recent(self, tickers: list[str]) -> dict[str, int]:
        """Ingest last 7 days of X data for all tickers (free tier compatible)."""
        end = date.today()
        start = end - timedelta(days=7)
        results: dict[str, int] = {}
        for ticker in tickers:
            try:
                results[ticker] = self.ingest_ticker(ticker, start, end)
            except Exception as exc:
                logger.warning("Twitter recent ingest failed %s: %s", ticker, exc)
                results[ticker] = 0
        return results

    def get_weekly_features(self, stock_id: int, week_ending: date) -> dict[str, float]:
        """Return aggregated Twitter features for this stock/week (PIT safe)."""
        row = self.session.execute(
            select(SocialSentiment).where(
                SocialSentiment.stock_id == stock_id,
                SocialSentiment.week_ending == str(week_ending),
                SocialSentiment.source == SOURCE,
            )
        ).scalar_one_or_none()

        if row is None:
            return {
                "twitter_mention_count": 0.0,
                "twitter_mention_momentum": 0.0,
                "twitter_sentiment_polarity": 0.0,
                "twitter_hype_risk": 0.0,
                "twitter_abnormal_attention": 0.0,
            }

        return {
            "twitter_mention_count": float(row.mention_count or 0),
            "twitter_mention_momentum": float(row.mention_momentum or 0),
            "twitter_sentiment_polarity": float(row.sentiment_polarity or 0),
            "twitter_hype_risk": float(row.hype_risk or 0),
            "twitter_abnormal_attention": float(row.abnormal_attention or 0),
        }

    # ------------------------------------------------------------------
    # Full-archive search (Pro/Academic tier)
    # ------------------------------------------------------------------

    def _fetch_archive(
        self,
        ticker: str,
        start: date,
        end: date,
        token: str,
    ) -> Iterator[dict]:
        """Fetch from full-archive endpoint with pagination."""
        query = f"({ticker} OR ${ticker} OR #{ticker}) lang:en -is:retweet"
        params = {
            "query": query,
            "start_time": _iso_date(start),
            "end_time": _iso_date(end + timedelta(days=1)),
            "max_results": ARCHIVE_PAGE_SIZE,
            "tweet.fields": "created_at,public_metrics,author_id",
        }
        headers = {"Authorization": f"Bearer {token}"}

        next_token = None
        fetched = 0
        while True:
            if next_token:
                params["next_token"] = next_token
            try:
                resp = requests.get(FULL_ARCHIVE_URL, params=params, headers=headers, timeout=20)
            except requests.exceptions.RequestException as exc:
                logger.debug("Twitter archive request failed: %s", exc)
                return

            if resp.status_code == 403:
                logger.debug("Twitter: full-archive not available on this tier (403)")
                return
            if resp.status_code == 429:
                logger.warning("Twitter: rate limited; sleeping 15s")
                time.sleep(15)
                continue
            if resp.status_code != 200:
                logger.debug("Twitter archive returned %d for %s", resp.status_code, ticker)
                return

            body = resp.json()
            tweets = body.get("data", [])
            for tweet in tweets:
                yield tweet
                fetched += 1

            meta = body.get("meta", {})
            next_token = meta.get("next_token")
            if not next_token or not tweets:
                break
            time.sleep(0.5)

        if fetched:
            logger.debug("Twitter archive: %s → %d tweets", ticker, fetched)

    # ------------------------------------------------------------------
    # Recent search (free tier, last 7 days)
    # ------------------------------------------------------------------

    def _fetch_recent(
        self,
        ticker: str,
        start: date,
        end: date,
        token: str,
    ) -> Iterator[dict]:
        """Fetch from recent-search endpoint (free tier, ≤7 days)."""
        query = f"({ticker} OR ${ticker} OR #{ticker}) lang:en -is:retweet"
        params = {
            "query": query,
            "start_time": _iso_date(start),
            "end_time": _iso_date(end + timedelta(days=1)),
            "max_results": RECENT_PAGE_SIZE,
            "tweet.fields": "created_at,public_metrics,author_id",
        }
        headers = {"Authorization": f"Bearer {token}"}

        next_token = None
        fetched = 0
        while True:
            if next_token:
                params["next_token"] = next_token
            try:
                resp = requests.get(RECENT_SEARCH_URL, params=params, headers=headers, timeout=20)
            except requests.exceptions.RequestException as exc:
                logger.debug("Twitter recent request failed: %s", exc)
                return

            if resp.status_code == 429:
                logger.warning("Twitter: rate limited; sleeping 15s")
                time.sleep(15)
                continue
            if resp.status_code != 200:
                logger.debug("Twitter recent returned %d for %s", resp.status_code, ticker)
                return

            body = resp.json()
            tweets = body.get("data", [])
            for tweet in tweets:
                yield tweet
                fetched += 1

            meta = body.get("meta", {})
            next_token = meta.get("next_token")
            if not next_token or not tweets:
                break
            time.sleep(0.5)

        if fetched:
            logger.debug("Twitter recent: %s → %d tweets", ticker, fetched)

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_token(self) -> str | None:
        if self._bearer_token:
            return self._bearer_token
        from app.config import settings
        return settings.twitter_bearer_token
