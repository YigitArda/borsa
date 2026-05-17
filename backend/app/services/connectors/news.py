from __future__ import annotations

import hashlib
import re
import time
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.news import NewsAnalysis, NewsArticle
from app.models.stock import Stock
from app.services.connectors.base import BaseConnector, ConnectorDefinition, ConnectorRunResult, NormalizedNewsItem
from app.services.gdelt_news import GDELTNewsService
from app.services.sec_news import SECNewsService
from app.services.social_sentiment_common import get_vader_analyzer

EARNINGS_KW = {"earnings", "eps", "revenue", "guidance", "quarterly", "results", "beat", "miss", "profit"}
LEGAL_KW = {"lawsuit", "sue", "sec", "investigation", "fine", "penalty", "fraud", "settlement", "doj", "ftc"}
PRODUCT_KW = {"launch", "product", "release", "unveil", "announce", "new model", "iphone", "gpt", "chip", "partnership"}
ANALYST_KW = {"upgrade", "downgrade", "price target", "buy", "sell", "overweight", "underweight", "outperform", "analyst"}
MGMT_KW = {"ceo", "cfo", "resign", "appoint", "hire", "fired", "step down", "executive", "board"}


def _classify_headline(text: str) -> dict[str, bool]:
    tokens = set(re.findall(r"\w+", text.lower()))
    return {
        "is_earnings": bool(EARNINGS_KW & tokens),
        "is_legal": bool(LEGAL_KW & tokens),
        "is_product_launch": bool(PRODUCT_KW & tokens),
        "is_analyst_action": bool(ANALYST_KW & tokens),
        "is_management_change": bool(MGMT_KW & tokens),
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class NewsConnectorIngestionService:
    def __init__(self, session: Session):
        self.session = session

    def upsert_news_items(self, ticker: str, items: list[NormalizedNewsItem]) -> int:
        stock = self.session.execute(select(Stock).where(Stock.ticker == ticker)).scalar_one_or_none()
        if not stock:
            return 0

        vader = get_vader_analyzer()
        inserted = 0

        for item in items:
            if not item.headline:
                continue

            stable_url = item.url or f"{item.provider_id}:{ticker}:{item.headline}:{item.published_at}"
            url_hash = hashlib.sha256(stable_url.encode()).hexdigest()[:64]
            article = self.session.execute(
                select(NewsArticle).where(NewsArticle.url_hash == url_hash)
            ).scalar_one_or_none()

            if article is None:
                article = NewsArticle(
                    url_hash=url_hash,
                    published_at=item.published_at,
                    available_at=item.available_at or item.published_at,
                    source=item.source,
                    provider_id=item.provider_id,
                    headline=item.headline[:500],
                    body_excerpt=item.body_excerpt[:1000] if item.body_excerpt else None,
                    ticker_mentions=[ticker],
                    source_quality=item.source_quality,
                    fallback_used=item.fallback_used,
                    raw_payload=item.raw_payload,
                )
                self.session.add(article)
                self.session.flush()
            else:
                mentions = article.ticker_mentions or []
                if ticker not in mentions:
                    article.ticker_mentions = [*mentions, ticker]
                article.available_at = article.available_at or item.available_at or item.published_at
                article.provider_id = article.provider_id or item.provider_id
                article.source_quality = article.source_quality if article.source_quality is not None else item.source_quality
                article.fallback_used = bool(article.fallback_used or item.fallback_used)

            sentiment_score = None
            sentiment_label = "neutral"
            if vader and item.headline:
                scores = vader.polarity_scores(item.headline)
                sentiment_score = scores["compound"]
                if sentiment_score > 0.05:
                    sentiment_label = "positive"
                elif sentiment_score < -0.05:
                    sentiment_label = "negative"

            existing_analysis = self.session.execute(
                select(NewsAnalysis).where(
                    NewsAnalysis.news_id == article.id,
                    NewsAnalysis.stock_id == stock.id,
                )
            ).scalar_one_or_none()
            if existing_analysis is None:
                self.session.add(
                    NewsAnalysis(
                        news_id=article.id,
                        stock_id=stock.id,
                        sentiment_score=sentiment_score,
                        sentiment_label=sentiment_label,
                        relevance_score=item.source_quality or 1.0,
                        **_classify_headline(item.headline),
                    )
                )
                inserted += 1

        self.session.commit()
        return inserted


class YFinanceNewsConnector(BaseConnector):
    definition = ConnectorDefinition(
        provider_id="yfinance_news",
        name="Yahoo Finance News",
        category="news",
        enabled_by_default=True,
        priority=90,
        rate_limit_per_minute=30,
        capabilities=("company_news", "free_fallback"),
    )

    def run(
        self,
        *,
        tickers: list[str],
        as_of_date: date | None = None,
        lookback_days: int = 7,
        **_: Any,
    ) -> ConnectorRunResult:
        try:
            import yfinance as yf
        except ImportError:
            return self.skipped("yfinance_missing")

        ingestor = NewsConnectorIngestionService(self.session)
        results: dict[str, int] = {}
        errors: dict[str, str] = {}
        end_dt = datetime.combine(as_of_date, datetime.max.time(), tzinfo=timezone.utc) if as_of_date else _utc_now()
        start_dt = end_dt - timedelta(days=lookback_days)

        for ticker in tickers:
            try:
                raw_items = yf.Ticker(ticker).news or []
                normalized: list[NormalizedNewsItem] = []
                for raw in raw_items:
                    title = (raw.get("title") or "").strip()
                    if not title:
                        continue
                    pub_ts = raw.get("providerPublishTime")
                    pub_dt = datetime.fromtimestamp(pub_ts, tz=timezone.utc) if pub_ts else None
                    if pub_dt and not (start_dt <= pub_dt <= end_dt):
                        continue
                    normalized.append(
                        NormalizedNewsItem(
                            ticker=ticker,
                            headline=title,
                            url=(raw.get("link") or raw.get("url") or "").strip(),
                            published_at=pub_dt,
                            available_at=pub_dt or end_dt,
                            source=raw.get("publisher") or "yfinance",
                            provider_id=self.provider_id,
                            source_quality=0.55,
                            fallback_used=True,
                            raw_payload=dict(raw),
                        )
                    )
                results[ticker] = ingestor.upsert_news_items(ticker, normalized)
            except Exception as exc:
                errors[ticker] = str(exc)
                results[ticker] = 0
            time.sleep(0.15)

        status = "partial" if errors else "ok"
        return ConnectorRunResult(self.provider_id, status, sum(results.values()), details={"tickers": results, "errors": errors})


class GDELTNewsConnector(BaseConnector):
    definition = ConnectorDefinition(
        provider_id="gdelt_news",
        name="GDELT Global News",
        category="news",
        enabled_by_default=True,
        priority=40,
        rate_limit_per_minute=60,
        capabilities=("global_news", "historical_news", "free_provider"),
    )

    def run(
        self,
        *,
        tickers: list[str],
        as_of_date: date | None = None,
        lookback_days: int = 7,
        **_: Any,
    ) -> ConnectorRunResult:
        end = as_of_date or _utc_now().date()
        start = end - timedelta(days=lookback_days)
        results = GDELTNewsService(self.session).backfill(tickers, start, end, delay_sec=1.0)
        return ConnectorRunResult(self.provider_id, "ok", sum(results.values()), details={"tickers": results})


class SECNewsConnector(BaseConnector):
    definition = ConnectorDefinition(
        provider_id="sec_edgar_news",
        name="SEC EDGAR Filings",
        category="news",
        enabled_by_default=True,
        priority=10,
        rate_limit_per_minute=600,
        capabilities=("8-k", "6-k", "filing_events", "point_in_time"),
    )

    def run(
        self,
        *,
        tickers: list[str],
        as_of_date: date | None = None,
        lookback_days: int = 30,
        **_: Any,
    ) -> ConnectorRunResult:
        end = as_of_date or _utc_now().date()
        start = end - timedelta(days=lookback_days)
        results = SECNewsService(self.session).backfill(tickers, start, end)
        return ConnectorRunResult(self.provider_id, "ok", sum(results.values()), details={"tickers": results})


class RSSNewsConnector(BaseConnector):
    definition = ConnectorDefinition(
        provider_id="rss_news",
        name="Curated RSS News",
        category="news",
        enabled_by_default=True,
        priority=95,
        rate_limit_per_minute=30,
        capabilities=("rss", "free_fallback"),
        config={"feeds": ["https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"]},
    )

    def run(
        self,
        *,
        tickers: list[str],
        as_of_date: date | None = None,
        lookback_days: int = 7,
        **_: Any,
    ) -> ConnectorRunResult:
        ingestor = NewsConnectorIngestionService(self.session)
        end_dt = datetime.combine(as_of_date, datetime.max.time(), tzinfo=timezone.utc) if as_of_date else _utc_now()
        start_dt = end_dt - timedelta(days=lookback_days)
        results: dict[str, int] = {}
        errors: dict[str, str] = {}

        for ticker in tickers:
            items: list[NormalizedNewsItem] = []
            for feed in self.definition.config["feeds"]:
                url = feed.format(ticker=ticker)
                try:
                    response = requests.get(url, timeout=15)
                    response.raise_for_status()
                    items.extend(self._parse_feed(ticker, response.text, start_dt, end_dt))
                except Exception as exc:
                    errors[f"{ticker}:{url}"] = str(exc)
            results[ticker] = ingestor.upsert_news_items(ticker, items)
            time.sleep(0.5)

        status = "partial" if errors else "ok"
        return ConnectorRunResult(self.provider_id, status, sum(results.values()), details={"tickers": results, "errors": errors})

    def _parse_feed(
        self,
        ticker: str,
        xml_text: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[NormalizedNewsItem]:
        root = ElementTree.fromstring(xml_text)
        items: list[NormalizedNewsItem] = []
        for node in root.findall(".//item"):
            title = (node.findtext("title") or "").strip()
            link = (node.findtext("link") or "").strip()
            description = (node.findtext("description") or "").strip()
            published_at = self._parse_pub_date(node.findtext("pubDate"))
            if published_at and not (start_dt <= published_at <= end_dt):
                continue
            haystack = f"{title} {description}".upper()
            if ticker.upper() not in haystack:
                continue
            items.append(
                NormalizedNewsItem(
                    ticker=ticker,
                    headline=title,
                    url=link,
                    published_at=published_at,
                    available_at=published_at or end_dt,
                    source="rss",
                    provider_id=self.provider_id,
                    body_excerpt=description,
                    source_quality=0.45,
                    fallback_used=True,
                    raw_payload={"title": title, "link": link, "description": description},
                )
            )
        return items

    def _parse_pub_date(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None


NEWS_CONNECTORS = (
    SECNewsConnector,
    GDELTNewsConnector,
    YFinanceNewsConnector,
    RSSNewsConnector,
)
