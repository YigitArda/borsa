"""SEC EDGAR full-text search news ingestion.

Fetches 8-K / 6-K filings via SEC EFTS API.
Endpoint: https://efts.sec.gov/LATEST/search-index
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import date, datetime, timedelta

import requests
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.news import NewsArticle, NewsAnalysis
from app.services.sec_edgar import get_cik, _SEC_HEADERS
from app.services.social_sentiment_common import get_vader_analyzer

logger = logging.getLogger(__name__)

SEC_START = date(2001, 1, 1)
SEC_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

EARNINGS_KW = {"earnings", "eps", "revenue", "guidance", "quarterly", "results", "beat", "miss", "profit"}
LEGAL_KW = {"lawsuit", "sue", "sec", "investigation", "fine", "penalty", "fraud", "settlement", "doj", "ftc"}
PRODUCT_KW = {"launch", "product", "release", "unveil", "announce", "new model", "iphone", "gpt", "chip", "partnership"}
ANALYST_KW = {"upgrade", "downgrade", "price target", "buy", "sell", "overweight", "underweight", "outperform", "analyst"}
MGMT_KW = {"ceo", "cfo", "resign", "appoint", "hire", "fired", "step down", "executive", "board"}


def _classify_headline(text: str) -> dict[str, bool]:
    t = text.lower()
    tokens = set(re.findall(r"\w+", t))
    return {
        "is_earnings": bool(EARNINGS_KW & tokens),
        "is_legal": bool(LEGAL_KW & tokens),
        "is_product_launch": bool(PRODUCT_KW & tokens),
        "is_analyst_action": bool(ANALYST_KW & tokens),
        "is_management_change": bool(MGMT_KW & tokens),
    }


class SECNewsService:
    def __init__(self, session: Session):
        self.session = session

    def ingest_ticker(self, ticker: str, start: date, end: date) -> int:
        if start > end:
            return 0
        if end < SEC_START:
            return 0
        if start < SEC_START:
            start = SEC_START

        stock = self.session.execute(
            select(Stock).where(Stock.ticker == ticker)
        ).scalar_one_or_none()
        if not stock:
            return 0

        cik = get_cik(ticker)
        if not cik:
            logger.debug("SEC news: no CIK for %s", ticker)
            return 0

        vader = get_vader_analyzer()
        inserted = 0

        # SEC EFTS allows custom date ranges; fetch in 90-day windows
        window_start = start
        while window_start <= end:
            window_end = min(window_start + timedelta(days=89), end)
            try:
                inserted += self._fetch_window(ticker, stock.id, cik, window_start, window_end, vader)
            except Exception as exc:
                logger.warning("SEC news fetch failed %s %s-%s: %s", ticker, window_start, window_end, exc)
            time.sleep(0.15)
            window_start = window_end + timedelta(days=1)

        return inserted

    def _fetch_window(self, ticker: str, stock_id: int, cik: str, start: date, end: date, vader) -> int:
        params = {
            "q": f'"{ticker}"',
            "dateRange": "custom",
            "startdt": start.isoformat(),
            "enddt": end.isoformat(),
            "forms": "8-K,6-K",
        }
        r = requests.get(SEC_SEARCH_URL, params=params, headers=_SEC_HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()

        hits = data.get("hits", {}).get("hits", []) if isinstance(data, dict) else []
        inserted = 0

        for hit in hits:
            src = hit.get("_source", {})
            filed = src.get("filed")
            form_type = src.get("form") or src.get("form_type") or "8-K"
            description = (src.get("description") or src.get("display_names", [""])[0] or "").strip()
            entity = (src.get("entity") or src.get("entity_name") or ticker).strip()

            if not filed:
                continue

            try:
                filed_date = date.fromisoformat(filed) if isinstance(filed, str) else filed
            except (ValueError, TypeError):
                continue

            # Build a stable URL for deduplication
            accession = hit.get("_id") or f"{cik}_{filed}_{form_type}"
            url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form_type}&dateb=&owner=include&count=40"
            url_hash = hashlib.sha256(accession.encode()).hexdigest()[:64]

            headline = f"{entity} — {form_type}"
            if description:
                headline += f": {description}"
            headline = headline[:500]

            # PIT: published_at = filing date (market learns on this date)
            pub_dt = datetime.combine(filed_date, datetime.min.time())

            stmt = pg_insert(NewsArticle).values(
                url_hash=url_hash,
                published_at=pub_dt,
                source="sec_edgar",
                headline=headline,
                body_excerpt=description[:1000] if description else None,
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
            if vader and headline:
                scores = vader.polarity_scores(headline)
                sentiment_score = scores["compound"]
                sentiment_label = (
                    "positive" if sentiment_score > 0.05
                    else "negative" if sentiment_score < -0.05
                    else "neutral"
                )

            cats = _classify_headline(description) if description else _classify_headline(headline)

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

    def backfill(self, tickers: list[str], start: date, end: date) -> dict[str, int]:
        results = {}
        for ticker in tickers:
            try:
                results[ticker] = self.ingest_ticker(ticker, start, end)
            except Exception as exc:
                logger.error("SEC news backfill failed %s: %s", ticker, exc)
                results[ticker] = 0
            time.sleep(0.15)
        return results

    def ingest_recent(self, tickers: list[str]) -> dict[str, int]:
        end = date.today()
        start = end - timedelta(days=30)
        return self.backfill(tickers, start, end)
