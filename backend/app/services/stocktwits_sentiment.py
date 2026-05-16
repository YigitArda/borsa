"""
Stocktwits social sentiment ingestion.

This is a lightweight free-source fallback for social chatter when Twitter/X
history is not available or not worth paying for.

We treat it as another PIT-safe social source and store it in the shared
social_sentiment table with source="stocktwits".
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Iterator

import requests
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.news import SocialSentiment
from app.models.stock import Stock
from app.services.data_source_health import record_source_health

logger = logging.getLogger(__name__)

SOURCE = "stocktwits"
STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"


def _friday_of(d: date) -> date:
    days_to_friday = (4 - d.weekday()) % 7
    return d + timedelta(days=days_to_friday)


def _vader_score(text: str, vader) -> float:
    try:
        return float(vader.polarity_scores(text)["compound"])
    except Exception:
        return 0.0


class StocktwitsSentimentService:
    """Fetch Stocktwits symbol stream chatter and store weekly aggregates."""

    def __init__(self, session: Session):
        self.session = session
        self._vader = None

    def ingest_ticker(self, ticker: str, start: date, end: date, max_pages: int = 5) -> int:
        stock = self.session.execute(
            select(Stock).where(Stock.ticker == ticker)
        ).scalar_one_or_none()
        if stock is None:
            return 0

        posts = list(self._fetch_messages(ticker, max_pages=max_pages))
        if not posts:
            record_source_health(
                self.session,
                source_name="stocktwits",
                source_used=None,
                status="failure",
                target_ticker=ticker,
                week_ending=end,
                message="no stocktwits messages found",
                details={"start": str(start), "end": str(end)},
            )
            return 0

        vader = self._get_vader()
        week_data: dict[date, list[float]] = {}
        for post in posts:
            created_at = post.get("created_at") or post.get("created")
            text = post.get("body") or post.get("text") or ""
            if not created_at:
                continue
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
            record_source_health(
                self.session,
                source_name="stocktwits",
                source_used="stocktwits_api",
                status="failure",
                target_ticker=ticker,
                week_ending=end,
                message="messages outside requested date range",
                details={"start": str(start), "end": str(end)},
            )
            return 0

        written = self._upsert_weeks(stock.id, week_data, source_used="stocktwits_api")
        record_source_health(
            self.session,
            source_name="stocktwits",
            source_used="stocktwits_api",
            status="success",
            target_ticker=ticker,
            week_ending=end,
            message=f"wrote {written} weekly rows",
            details={"start": str(start), "end": str(end)},
        )
        return written

    def ingest_recent(self, tickers: list[str]) -> dict[str, int]:
        end = date.today()
        start = end - timedelta(weeks=4)
        results: dict[str, int] = {}
        for ticker in tickers:
            try:
                results[ticker] = self.ingest_ticker(ticker, start, end)
            except Exception as exc:
                logger.warning("Stocktwits recent ingest failed %s: %s", ticker, exc)
                results[ticker] = 0
        return results

    def backfill(self, tickers: list[str], start: date, end: date, delay_sec: float = 1.0) -> dict[str, int]:
        results: dict[str, int] = {}
        for ticker in tickers:
            try:
                n = self.ingest_ticker(ticker, start, end)
                results[ticker] = n
                logger.info("Stocktwits backfill: %s → %d weeks", ticker, n)
                time.sleep(delay_sec)
            except Exception as exc:
                logger.warning("Stocktwits backfill failed %s: %s", ticker, exc)
                results[ticker] = 0
        return results

    def get_weekly_features(self, stock_id: int, week_ending: date) -> dict[str, float]:
        row = self.session.execute(
            select(SocialSentiment).where(
                SocialSentiment.stock_id == stock_id,
                SocialSentiment.week_ending == str(week_ending),
                SocialSentiment.source == SOURCE,
            )
        ).scalar_one_or_none()

        if row is None:
            return {
                "stocktwits_mention_count": 0.0,
                "stocktwits_mention_momentum": 0.0,
                "stocktwits_sentiment_polarity": 0.0,
                "stocktwits_hype_risk": 0.0,
                "stocktwits_abnormal_attention": 0.0,
            }

        return {
            "stocktwits_mention_count": float(row.mention_count or 0),
            "stocktwits_mention_momentum": float(row.mention_momentum or 0),
            "stocktwits_sentiment_polarity": float(row.sentiment_polarity or 0),
            "stocktwits_hype_risk": float(row.hype_risk or 0),
            "stocktwits_abnormal_attention": float(row.abnormal_attention or 0),
        }

    def _fetch_messages(self, ticker: str, max_pages: int = 5) -> Iterator[dict]:
        url = STOCKTWITS_URL.format(ticker=ticker)
        page = 1
        seen = 0
        while page <= max_pages:
            try:
                resp = requests.get(url, params={"page": page}, timeout=20)
            except requests.exceptions.RequestException as exc:
                logger.debug("Stocktwits request failed %s: %s", ticker, exc)
                return

            if resp.status_code != 200:
                logger.debug("Stocktwits returned %d for %s", resp.status_code, ticker)
                return

            body = resp.json()
            messages = body.get("messages", []) or []
            if not messages:
                break
            for msg in messages:
                yield msg
                seen += 1
            if len(messages) < 30:
                break
            page += 1

        if seen:
            logger.debug("Stocktwits: %s → %d messages", ticker, seen)

    def _upsert_weeks(self, stock_id: int, week_data: dict[date, list[float]], source_used: str) -> int:
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
                "stock_id": stock_id,
                "week_ending": str(week),
                "mention_count": n,
                "mention_momentum": round(momentum, 4),
                "sentiment_polarity": round(avg_sentiment, 4),
                "hype_risk": hype_risk,
                "abnormal_attention": round(abnormal, 4),
                "source": SOURCE,
                "source_used": source_used,
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
                "source_used": stmt.excluded.source_used,
            },
        )
        self.session.execute(stmt)
        self.session.commit()
        return len(rows)

    def _get_vader(self):
        if self._vader is None:
            try:
                from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
                self._vader = SentimentIntensityAnalyzer()
            except ImportError:
                from app.services.social_sentiment import _FallbackSentimentIntensityAnalyzer
                self._vader = _FallbackSentimentIntensityAnalyzer()
        return self._vader
