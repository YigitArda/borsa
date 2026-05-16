"""GDELT Project news ingestion.

GDELT provides global news coverage from 2013 onward.
Endpoint: https://api.gdeltproject.org/api/v2/doc/doc
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import date, datetime, timedelta

import requests
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.news import NewsArticle, NewsAnalysis
from app.services.social_sentiment_common import get_vader_analyzer

logger = logging.getLogger(__name__)

GDELT_START = date(2013, 1, 1)
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

EARNINGS_KW = {"earnings", "eps", "revenue", "guidance", "quarterly", "results", "beat", "miss", "profit"}
LEGAL_KW = {"lawsuit", "sue", "sec", "investigation", "fine", "penalty", "fraud", "settlement", "doj", "ftc"}
PRODUCT_KW = {"launch", "product", "release", "unveil", "announce", "new model", "iphone", "gpt", "chip", "partnership"}
ANALYST_KW = {"upgrade", "downgrade", "price target", "buy", "sell", "overweight", "underweight", "outperform", "analyst"}
MGMT_KW = {"ceo", "cfo", "resign", "appoint", "hire", "fired", "step down", "executive", "board"}


def _classify_headline(text: str) -> dict[str, bool]:
    import re
    t = text.lower()
    tokens = set(re.findall(r"\w+", t))
    return {
        "is_earnings": bool(EARNINGS_KW & tokens),
        "is_legal": bool(LEGAL_KW & tokens),
        "is_product_launch": bool(PRODUCT_KW & tokens),
        "is_analyst_action": bool(ANALYST_KW & tokens),
        "is_management_change": bool(MGMT_KW & tokens),
    }


class GDELTNewsService:
    def __init__(self, session: Session):
        self.session = session

    def ingest_ticker(self, ticker: str, start: date, end: date) -> int:
        if start > end:
            return 0
        if end < GDELT_START:
            return 0
        if start < GDELT_START:
            start = GDELT_START

        stock = self.session.execute(
            select(Stock).where(Stock.ticker == ticker)
        ).scalar_one_or_none()
        if not stock:
            return 0

        vader = get_vader_analyzer()
        inserted = 0

        # GDELT allows date ranges but large ranges can be slow;
        # split into 7-day windows.
        window_start = start
        while window_start <= end:
            window_end = min(window_start + timedelta(days=6), end)
            try:
                inserted += self._fetch_window(ticker, stock.id, window_start, window_end, vader)
            except Exception as exc:
                logger.warning("GDELT fetch failed %s %s-%s: %s", ticker, window_start, window_end, exc)
            time.sleep(1.0)
            window_start = window_end + timedelta(days=1)

        return inserted

    def _fetch_window(self, ticker: str, stock_id: int, start: date, end: date, vader) -> int:
        params = {
            "query": f'"{ticker}"',
            "mode": "ArtList",
            "format": "json",
            "startdatetime": start.strftime("%Y%m%d%H%M%S"),
            "enddatetime": (end + timedelta(days=1)).strftime("%Y%m%d%H%M%S"),
            "maxrecords": 250,
        }
        r = requests.get(GDELT_URL, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        articles = data.get("articles", []) if isinstance(data, dict) else []

        inserted = 0
        for art in articles:
            title = (art.get("title") or "").strip()
            url = (art.get("url") or "").strip()
            if not url:
                continue

            # Skip non-English
            lang = (art.get("lang") or art.get("language") or "").lower()
            country = (art.get("sourcecountry") or "").upper()
            if lang and lang not in ("en", "eng", "english"):
                continue
            if country and country != "US":
                continue

            url_hash = hashlib.sha256(url.encode()).hexdigest()[:64]

            seendate = art.get("seendate") or ""
            pub_dt = None
            if seendate and len(seendate) >= 14:
                try:
                    pub_dt = datetime.strptime(seendate[:14], "%Y%m%d%H%M%S")
                except ValueError:
                    pass

            # PIT: use GDELT's seendate, never datetime.now()
            if pub_dt is None:
                continue

            stmt = pg_insert(NewsArticle).values(
                url_hash=url_hash,
                published_at=pub_dt,
                source="gdelt",
                headline=title[:500],
                ticker_mentions=[ticker],
            )
            stmt = stmt.on_conflict_do_nothing(index_elements=["url_hash"])
            self.session.execute(stmt)
            self.session.flush()

            article = self.session.execute(
                select(NewsArticle).where(NewsArticle.url_hash == url_hash)
            ).scalar_one_or_none()
            if not article:
                continue

            sentiment_score = None
            sentiment_label = "neutral"
            if vader and title:
                scores = vader.polarity_scores(title)
                sentiment_score = scores["compound"]
                sentiment_label = (
                    "positive" if sentiment_score > 0.05
                    else "negative" if sentiment_score < -0.05
                    else "neutral"
                )

            cats = _classify_headline(title)

            existing = self.session.execute(
                select(NewsAnalysis).where(
                    NewsAnalysis.news_id == article.id,
                    NewsAnalysis.stock_id == stock_id,
                )
            ).scalar_one_or_none()
            if not existing:
                self.session.add(NewsAnalysis(
                    news_id=article.id,
                    stock_id=stock_id,
                    sentiment_score=sentiment_score,
                    sentiment_label=sentiment_label,
                    relevance_score=1.0,
                    **cats,
                ))
                inserted += 1

        self.session.commit()
        return inserted

    def backfill(self, tickers: list[str], start: date, end: date, delay_sec: float = 1.0) -> dict[str, int]:
        results = {}
        for ticker in tickers:
            try:
                results[ticker] = self.ingest_ticker(ticker, start, end)
            except Exception as exc:
                logger.error("GDELT backfill failed %s: %s", ticker, exc)
                results[ticker] = 0
            if delay_sec > 0:
                time.sleep(delay_sec)
        return results

    def ingest_recent(self, tickers: list[str]) -> dict[str, int]:
        end = date.today()
        start = end - timedelta(days=7)
        return self.backfill(tickers, start, end, delay_sec=1.0)
