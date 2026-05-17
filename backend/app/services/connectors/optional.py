from __future__ import annotations

import hashlib
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models.macro import MacroIndicator
from app.models.news import NewsArticle, NewsAnalysis
from app.models.price import PriceDaily
from app.services.connectors.base import BaseConnector, ConnectorDefinition, ConnectorRunResult, NormalizedNewsItem
from app.services.connectors.news import NewsConnectorIngestionService
from app.services.connectors.retry import RetryPolicy, with_retry
from app.services.social_sentiment_common import get_vader_analyzer

import importlib.util
import logging

logger = logging.getLogger(__name__)

_POLYGON_RETRY = RetryPolicy(max_attempts=3, backoff_seconds=2.0)


class PolygonNewsConnector(BaseConnector):
    definition = ConnectorDefinition(
        provider_id="polygon_news",
        name="Polygon News",
        category="news",
        enabled_by_default=False,
        requires_api_key=True,
        priority=20,
        rate_limit_per_minute=5,
        capabilities=("company_news", "market_news", "paid_provider"),
    )

    def is_configured(self) -> bool:
        return bool(settings.polygon_api_key)

    def run(self, *, tickers: list[str], start: str = "2010-01-01", as_of_date: date | None = None, lookback_days: int = 7, **_: Any) -> ConnectorRunResult:
        if not self.is_configured():
            return self.skipped("polygon_api_key_missing")

        end = as_of_date or datetime.now(timezone.utc).date()
        start_date = end - timedelta(days=lookback_days)
        start_str = start_date.isoformat()
        end_str = end.isoformat()

        ingestor = NewsConnectorIngestionService(self.session)
        results: dict[str, int] = {}
        errors: dict[str, str] = {}

        for ticker in tickers:
            try:
                items = self._fetch_ticker_news(ticker, start_str, end_str)
                results[ticker] = ingestor.upsert_news_items(ticker, items)
            except Exception as exc:
                logger.warning("Polygon news failed %s: %s", ticker, exc)
                errors[ticker] = str(exc)
                results[ticker] = 0
            time.sleep(0.2)

        status = "partial" if errors else "ok"
        return ConnectorRunResult(self.provider_id, status, sum(results.values()), details={"tickers": results, "errors": errors})

    def _fetch_ticker_news(self, ticker: str, start: str, end: str) -> list[NormalizedNewsItem]:
        url = f"https://api.polygon.io/v2/reference/news"
        params = {
            "ticker": ticker,
            "published_utc.gte": start,
            "published_utc.lte": end,
            "limit": 1000,
            "apiKey": settings.polygon_api_key,
        }

        def _get():
            r = requests.get(url, params=params, timeout=settings.connector_request_timeout)
            r.raise_for_status()
            return r.json()

        data = with_retry(_get, _POLYGON_RETRY)
        articles = data.get("results", []) if isinstance(data, dict) else []
        items: list[NormalizedNewsItem] = []
        for art in articles:
            pub_str = art.get("published_utc") or ""
            pub_dt = None
            if pub_str:
                try:
                    pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except ValueError:
                    pass
            url_val = art.get("article_url") or ""
            url_hash = hashlib.sha256(url_val.encode()).hexdigest()[:64]
            items.append(
                NormalizedNewsItem(
                    ticker=ticker,
                    headline=(art.get("title") or "")[:500],
                    url=url_val,
                    published_at=pub_dt,
                    available_at=pub_dt,
                    source=art.get("publisher", {}).get("name", "polygon") if isinstance(art.get("publisher"), dict) else "polygon",
                    provider_id=self.provider_id,
                    body_excerpt=(art.get("description") or "")[:1000],
                    source_quality=0.85,
                    fallback_used=False,
                    raw_payload=art,
                )
            )
        return items


class PolygonPricesConnector(BaseConnector):
    definition = ConnectorDefinition(
        provider_id="polygon_prices",
        name="Polygon Prices",
        category="price",
        enabled_by_default=False,
        requires_api_key=True,
        priority=20,
        rate_limit_per_minute=5,
        capabilities=("ohlcv", "corporate_actions", "paid_provider"),
    )

    def is_configured(self) -> bool:
        return bool(settings.polygon_api_key)

    def run(self, *, tickers: list[str], start: str = "2010-01-01", as_of_date: date | None = None, **_: Any) -> ConnectorRunResult:
        if not self.is_configured():
            return self.skipped("polygon_api_key_missing")

        from sqlalchemy import select
        from app.models.stock import Stock

        end = (as_of_date or datetime.now(timezone.utc).date()).isoformat()
        results: dict[str, int] = {}
        errors: dict[str, str] = {}

        for ticker in tickers:
            try:
                rows = self._ingest_ticker(ticker, start, end)
                results[ticker] = rows
            except Exception as exc:
                logger.warning("Polygon prices failed %s: %s", ticker, exc)
                errors[ticker] = str(exc)
                results[ticker] = 0
            time.sleep(0.2)

        status = "partial" if errors else "ok"
        return ConnectorRunResult(self.provider_id, status, sum(results.values()), details={"tickers": results, "errors": errors})

    def _ingest_ticker(self, ticker: str, from_: str, to: str) -> int:
        from sqlalchemy import select
        from app.models.stock import Stock

        stock = self.session.execute(select(Stock).where(Stock.ticker == ticker)).scalar_one_or_none()
        if not stock:
            return 0

        url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{from_}/{to}"
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
            "apiKey": settings.polygon_api_key,
        }

        def _get():
            r = requests.get(url, params=params, timeout=settings.connector_request_timeout)
            r.raise_for_status()
            return r.json()

        data = with_retry(_get, _POLYGON_RETRY)
        results_raw = data.get("results", []) if isinstance(data, dict) else []

        rows: list[dict] = []
        for bar in results_raw:
            ts_ms = bar.get("t")
            if not ts_ms:
                continue
            bar_date = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()
            available_at = datetime.combine(bar_date + timedelta(days=1), datetime.min.time())
            rows.append({
                "stock_id": stock.id,
                "date": bar_date,
                "open": bar.get("o"),
                "high": bar.get("h"),
                "low": bar.get("l"),
                "close": bar.get("c"),
                "volume": bar.get("v"),
                "data_source": "polygon",
                "available_at": available_at,
                "provider_id": self.provider_id,
                "source_quality": 0.95,
            })

        if not rows:
            return 0

        stmt = pg_insert(PriceDaily).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["stock_id", "date"])
        self.session.execute(stmt)
        self.session.commit()
        return len(rows)


class WorldBankMacroConnector(BaseConnector):
    definition = ConnectorDefinition(
        provider_id="worldbank_macro",
        name="World Bank Macro",
        category="macro",
        enabled_by_default=False,
        priority=70,
        rate_limit_per_minute=30,
        capabilities=("global_macro", "annual_series"),
    )

    _INDICATORS = [
        "NY.GDP.MKTP.CD",
        "FP.CPI.TOTL.ZG",
        "SL.UEM.TOTL.ZS",
        "FR.INR.RINR",
        "BN.CAB.XOKA.GD.ZS",
        "GC.DOD.TOTL.GD.ZS",
    ]

    def is_configured(self) -> bool:
        return True

    def run(self, *, start: str = "2010-01-01", as_of_date: date | None = None, **_: Any) -> ConnectorRunResult:
        start_year = int(start[:4])
        end_year = (as_of_date or datetime.now(timezone.utc).date()).year
        countries = settings.worldbank_default_countries

        total = 0
        errors: list[str] = []
        for country in countries:
            for indicator in self._INDICATORS:
                try:
                    n = self._ingest(country, indicator, start_year, end_year)
                    total += n
                except Exception as exc:
                    msg = f"{country}/{indicator}: {exc}"
                    logger.warning("WorldBank failed %s", msg)
                    errors.append(msg)
                time.sleep(0.3)

        status = "failed" if (total == 0 and errors) else ("partial" if errors else "ok")
        return ConnectorRunResult(self.provider_id, status, total, details={"errors": errors})

    def _ingest(self, country: str, indicator: str, start_year: int, end_year: int) -> int:
        url = f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
        params = {"format": "json", "per_page": 1000, "date": f"{start_year}:{end_year}"}

        def _get():
            r = requests.get(url, params=params, timeout=settings.connector_request_timeout)
            r.raise_for_status()
            return r.json()

        data = with_retry(_get, RetryPolicy(max_attempts=3))
        if not isinstance(data, list) or len(data) < 2:
            return 0

        observations = data[1] or []
        rows: list[dict] = []
        for obs in observations:
            value = obs.get("value")
            if value is None:
                continue
            year_str = obs.get("date") or ""
            try:
                obs_date = date(int(year_str), 1, 1)
            except (ValueError, TypeError):
                continue
            available_at = datetime.combine(obs_date + timedelta(days=90), datetime.min.time())
            rows.append({
                "indicator_code": f"WB_{indicator}_{country}",
                "date": obs_date,
                "available_at": available_at,
                "provider_id": self.provider_id,
                "value": float(value),
                "source_quality": 0.8,
            })

        if not rows:
            return 0

        stmt = pg_insert(MacroIndicator).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["indicator_code", "date"],
            set_={
                "available_at": stmt.excluded.available_at,
                "provider_id": stmt.excluded.provider_id,
                "value": stmt.excluded.value,
                "source_quality": stmt.excluded.source_quality,
            },
        )
        self.session.execute(stmt)
        self.session.commit()
        return len(rows)


class IMFMacroConnector(BaseConnector):
    definition = ConnectorDefinition(
        provider_id="imf_macro",
        name="IMF Macro",
        category="macro",
        enabled_by_default=False,
        priority=70,
        rate_limit_per_minute=20,
        capabilities=("global_macro", "balance_of_payments", "ifs"),
    )

    _INDICATORS = ["NGDP_RPCH", "PCPIPCH", "LUR", "BCA_NGDPD", "GGXWDG_NGDP"]

    def is_configured(self) -> bool:
        return True

    def run(self, *, start: str = "2010-01-01", as_of_date: date | None = None, **_: Any) -> ConnectorRunResult:
        countries = settings.imf_default_countries
        total = 0
        errors: list[str] = []

        for indicator in self._INDICATORS:
            for country in countries:
                try:
                    n = self._ingest(indicator, country)
                    total += n
                except Exception as exc:
                    msg = f"{indicator}/{country}: {exc}"
                    logger.warning("IMF failed %s", msg)
                    errors.append(msg)
                time.sleep(0.5)

        status = "failed" if (total == 0 and errors) else ("partial" if errors else "ok")
        return ConnectorRunResult(self.provider_id, status, total, details={"errors": errors})

    def _ingest(self, indicator: str, country: str) -> int:
        url = f"https://www.imf.org/external/datamapper/api/v1/{indicator}/{country}"

        def _get():
            r = requests.get(url, timeout=settings.connector_request_timeout)
            r.raise_for_status()
            return r.json()

        data = with_retry(_get, RetryPolicy(max_attempts=3))

        values_map = {}
        try:
            values_map = data.get("values", {}).get(indicator, {}).get(country, {})
        except (AttributeError, TypeError):
            return 0

        if not values_map:
            return 0

        rows: list[dict] = []
        for year_str, value in values_map.items():
            if value is None:
                continue
            try:
                year = int(year_str)
            except (ValueError, TypeError):
                continue
            obs_date = date(year, 1, 1)
            available_at = datetime(year + 1, 1, 1)
            rows.append({
                "indicator_code": f"IMF_{indicator}_{country}",
                "date": obs_date,
                "available_at": available_at,
                "provider_id": self.provider_id,
                "value": float(value),
                "source_quality": 0.85,
            })

        if not rows:
            return 0

        stmt = pg_insert(MacroIndicator).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["indicator_code", "date"],
            set_={
                "available_at": stmt.excluded.available_at,
                "provider_id": stmt.excluded.provider_id,
                "value": stmt.excluded.value,
                "source_quality": stmt.excluded.source_quality,
            },
        )
        self.session.execute(stmt)
        self.session.commit()
        return len(rows)


class KrakenCryptoConnector(BaseConnector):
    definition = ConnectorDefinition(
        provider_id="kraken_crypto",
        name="Kraken Crypto",
        category="crypto",
        enabled_by_default=False,
        requires_api_key=False,
        priority=80,
        rate_limit_per_minute=60,
        capabilities=("crypto_prices", "order_book"),
    )

    def is_configured(self) -> bool:
        return True

    def run(self, *, as_of_date: date | None = None, **_: Any) -> ConnectorRunResult:
        from app.models.crypto import CryptoPriceDaily

        pairs = settings.kraken_pairs
        total = 0
        errors: list[str] = []

        for pair in pairs:
            try:
                n = self._ingest_pair(pair, CryptoPriceDaily)
                total += n
            except Exception as exc:
                msg = f"{pair}: {exc}"
                logger.warning("Kraken failed %s", msg)
                errors.append(msg)
            time.sleep(1.0)

        status = "failed" if (total == 0 and errors) else ("partial" if errors else "ok")
        return ConnectorRunResult(self.provider_id, status, total, details={"errors": errors})

    def _ingest_pair(self, pair: str, CryptoPriceDaily) -> int:
        url = "https://api.kraken.com/0/public/OHLC"
        params = {"pair": pair, "interval": 1440}

        def _get():
            r = requests.get(url, params=params, timeout=settings.connector_request_timeout)
            r.raise_for_status()
            return r.json()

        data = with_retry(_get, RetryPolicy(max_attempts=3))
        errors_in_response = data.get("error", [])
        if errors_in_response:
            raise RuntimeError(f"Kraken API error: {errors_in_response}")

        result_data = data.get("result", {})
        ohlc_list = None
        for key, val in result_data.items():
            if key != "last" and isinstance(val, list):
                ohlc_list = val
                break

        if not ohlc_list:
            return 0

        rows: list[dict] = []
        for bar in ohlc_list:
            if len(bar) < 7:
                continue
            ts, open_, high, low, close, vwap, volume = bar[0], bar[1], bar[2], bar[3], bar[4], bar[5], bar[6]
            bar_date = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
            available_at = datetime.combine(bar_date + timedelta(days=1), datetime.min.time())
            rows.append({
                "pair": pair,
                "date": bar_date,
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume),
                "vwap": float(vwap) if vwap else None,
                "provider_id": self.provider_id,
                "available_at": available_at,
                "source_quality": 0.9,
                "raw_payload": {"ts": ts, "pair": pair},
            })

        if not rows:
            return 0

        stmt = pg_insert(CryptoPriceDaily).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["pair", "date"])
        self.session.execute(stmt)
        self.session.commit()
        return len(rows)


class AkShareConnector(BaseConnector):
    definition = ConnectorDefinition(
        provider_id="akshare_data",
        name="AkShare Data",
        category="alternative",
        enabled_by_default=False,
        priority=80,
        rate_limit_per_minute=20,
        capabilities=("china_market", "macro", "equities"),
    )

    def is_configured(self) -> bool:
        if not settings.akshare_enabled:
            return False
        return importlib.util.find_spec("akshare") is not None

    def run(self, *, start: str = "2010-01-01", as_of_date: date | None = None, **_: Any) -> ConnectorRunResult:
        if not settings.akshare_enabled:
            return self.skipped("akshare_disabled")
        if importlib.util.find_spec("akshare") is None:
            return self.skipped("akshare_missing")

        try:
            import akshare as ak
        except ImportError:
            return self.skipped("akshare_missing")

        _SERIES = [
            ("macro_china_cpi_yearly", "AK_CHINA_CPI_YOY"),
            ("macro_china_gdp_yearly", "AK_CHINA_GDP_YOY"),
        ]

        total = 0
        errors: list[str] = []
        for method_name, indicator_code in _SERIES:
            try:
                method = getattr(ak, method_name, None)
                if method is None:
                    continue
                df = method()
                if df is None or df.empty:
                    continue
                rows: list[dict] = []
                for _, row in df.iterrows():
                    date_col = row.get("date") or row.get("统计时间") or row.index
                    value_col = row.iloc[-1] if len(row) > 1 else None
                    if date_col is None or value_col is None:
                        continue
                    try:
                        import pandas as pd
                        obs_date = pd.Timestamp(date_col).date()
                        value = float(value_col)
                    except Exception:
                        continue
                    available_at = datetime.combine(obs_date, datetime.min.time())
                    rows.append({
                        "indicator_code": indicator_code,
                        "date": obs_date,
                        "available_at": available_at,
                        "provider_id": self.provider_id,
                        "value": value,
                        "source_quality": 0.7,
                    })
                if rows:
                    stmt = pg_insert(MacroIndicator).values(rows)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["indicator_code", "date"],
                        set_={"value": stmt.excluded.value, "provider_id": stmt.excluded.provider_id},
                    )
                    self.session.execute(stmt)
                    self.session.commit()
                    total += len(rows)
            except Exception as exc:
                errors.append(f"{method_name}: {exc}")

        status = "failed" if (total == 0 and errors) else ("partial" if errors else "ok")
        return ConnectorRunResult(self.provider_id, status, total, details={"errors": errors})


class AdanosSentimentConnector(BaseConnector):
    definition = ConnectorDefinition(
        provider_id="adanos_sentiment",
        name="Adanos Market Sentiment",
        category="sentiment",
        enabled_by_default=False,
        requires_api_key=True,
        priority=30,
        rate_limit_per_minute=30,
        capabilities=("alternative_data", "equity_sentiment"),
    )

    def is_configured(self) -> bool:
        return bool(settings.adanos_api_key and settings.adanos_base_url)

    def run(self, *, tickers: list[str], start: str = "2010-01-01", as_of_date: date | None = None, lookback_days: int = 7, **_: Any) -> ConnectorRunResult:
        if not self.is_configured():
            return self.skipped("adanos_not_configured")

        from sqlalchemy import select
        from app.models.stock import Stock
        from app.models.news import SocialSentiment

        end = (as_of_date or datetime.now(timezone.utc).date()).isoformat()
        start_dt = (as_of_date or datetime.now(timezone.utc).date()) - timedelta(days=lookback_days)
        start_str = start_dt.isoformat()

        headers = {"Authorization": f"Bearer {settings.adanos_api_key}"}
        total = 0
        errors: dict[str, str] = {}

        for ticker in tickers:
            try:
                url = f"{settings.adanos_base_url}/sentiment"
                params = {"ticker": ticker, "start": start_str, "end": end}

                def _get():
                    r = requests.get(url, params=params, headers=headers, timeout=settings.connector_request_timeout)
                    r.raise_for_status()
                    return r.json()

                data = with_retry(_get, RetryPolicy(max_attempts=3))
                items = data if isinstance(data, list) else data.get("data", [])

                stock = self.session.execute(select(Stock).where(Stock.ticker == ticker)).scalar_one_or_none()
                if not stock:
                    continue

                for item in items:
                    week_ending = item.get("week_ending") or item.get("date") or end
                    available_ts = item.get("timestamp") or item.get("available_at")
                    available_at = None
                    if available_ts:
                        try:
                            available_at = datetime.fromisoformat(str(available_ts).replace("Z", "+00:00"))
                        except ValueError:
                            pass

                    existing = self.session.execute(
                        select(SocialSentiment).where(
                            SocialSentiment.stock_id == stock.id,
                            SocialSentiment.week_ending == week_ending,
                            SocialSentiment.source == "adanos",
                        )
                    ).scalar_one_or_none()

                    if existing is None:
                        row = SocialSentiment(
                            stock_id=stock.id,
                            week_ending=week_ending,
                            sentiment_polarity=item.get("sentiment"),
                            mention_count=item.get("mention_count"),
                            source="adanos",
                            available_at=available_at,
                            provider_id=self.provider_id,
                            source_quality=0.8,
                            raw_payload=item,
                        )
                        self.session.add(row)
                        total += 1

                self.session.commit()
            except Exception as exc:
                logger.warning("Adanos sentiment failed %s: %s", ticker, exc)
                errors[ticker] = str(exc)

        status = "partial" if errors else "ok"
        return ConnectorRunResult(self.provider_id, status, total, details={"errors": errors})


class USASpendingConnector(BaseConnector):
    definition = ConnectorDefinition(
        provider_id="usaspending_contracts",
        name="USASpending Government Contracts",
        category="government",
        enabled_by_default=False,
        priority=60,
        rate_limit_per_minute=60,
        capabilities=("government_contracts", "award_data"),
    )

    def is_configured(self) -> bool:
        return True

    def run(self, *, tickers: list[str], start: str = "2010-01-01", as_of_date: date | None = None, lookback_days: int = 90, **_: Any) -> ConnectorRunResult:
        from sqlalchemy import select
        from app.models.stock import Stock
        from app.models.smallcap_signals import GovernmentContract

        end = as_of_date or datetime.now(timezone.utc).date()
        start_date = end - timedelta(days=lookback_days)

        total = 0
        errors: dict[str, str] = {}

        for ticker in tickers:
            try:
                stock = self.session.execute(select(Stock).where(Stock.ticker == ticker)).scalar_one_or_none()
                if not stock:
                    continue
                n = self._ingest_ticker(ticker, stock.id, start_date, end, GovernmentContract)
                total += n
            except Exception as exc:
                logger.warning("USASpending failed %s: %s", ticker, exc)
                errors[ticker] = str(exc)
            time.sleep(0.5)

        status = "partial" if errors else "ok"
        return ConnectorRunResult(self.provider_id, status, total, details={"errors": errors})

    def _ingest_ticker(self, ticker: str, stock_id: int, start_date: date, end_date: date, GovernmentContract) -> int:
        url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
        body = {
            "filters": {
                "recipient_search_text": [ticker],
                "award_type_codes": ["A", "B", "C", "D"],
                "time_period": [{"start_date": start_date.isoformat(), "end_date": end_date.isoformat()}],
            },
            "fields": ["Award ID", "Recipient Name", "Awarding Agency", "Award Amount", "Description", "Contract Award Type", "Period of Performance Current End Date", "Action Date"],
            "limit": 100,
        }

        def _post():
            r = requests.post(url, json=body, timeout=settings.connector_request_timeout)
            r.raise_for_status()
            return r.json()

        try:
            data = with_retry(_post, RetryPolicy(max_attempts=3))
        except Exception as exc:
            logger.warning("USASpending API failed for %s: %s", ticker, exc)
            return 0

        results = data.get("results", []) if isinstance(data, dict) else []
        inserted = 0

        for award in results:
            amount = award.get("Award Amount") or 0
            if float(amount) < 1_000_000:
                continue

            award_id = award.get("Award ID") or ""
            if not award_id:
                continue

            award_date_str = award.get("Action Date") or ""
            award_date = None
            if award_date_str:
                try:
                    award_date = date.fromisoformat(award_date_str)
                except ValueError:
                    pass

            if not award_date:
                continue

            perf_end_str = award.get("Period of Performance Current End Date")
            perf_end = None
            if perf_end_str:
                try:
                    perf_end = date.fromisoformat(perf_end_str)
                except ValueError:
                    pass

            from sqlalchemy import select as sa_select
            existing = self.session.execute(
                sa_select(GovernmentContract).where(
                    GovernmentContract.stock_id == stock_id,
                    GovernmentContract.award_id == award_id,
                )
            ).scalar_one_or_none()

            if existing is None:
                row = GovernmentContract(
                    stock_id=stock_id,
                    award_id=award_id,
                    award_date=award_date,
                    awarding_agency=award.get("Awarding Agency"),
                    recipient_name=award.get("Recipient Name"),
                    award_amount=float(amount),
                    description=(award.get("Description") or "")[:500],
                    contract_type=award.get("Contract Award Type"),
                    performance_end_date=perf_end,
                    created_at=datetime.now(timezone.utc),
                )
                self.session.add(row)
                inserted += 1

        self.session.commit()
        return inserted


OPTIONAL_CONNECTORS = (
    PolygonNewsConnector,
    PolygonPricesConnector,
    WorldBankMacroConnector,
    IMFMacroConnector,
    KrakenCryptoConnector,
    AkShareConnector,
    AdanosSentimentConnector,
    USASpendingConnector,
)
