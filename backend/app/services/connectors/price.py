from __future__ import annotations

from typing import Any

from app.services.connectors.base import BaseConnector, ConnectorDefinition, ConnectorRunResult
from app.services.data_ingestion import DataIngestionService


class YFinancePricesConnector(BaseConnector):
    definition = ConnectorDefinition(
        provider_id="yfinance_prices",
        name="Yahoo Finance Prices",
        category="price",
        enabled_by_default=True,
        priority=90,
        rate_limit_per_minute=60,
        capabilities=("daily_ohlcv", "splits_dividends", "free_fallback"),
    )

    def run(self, *, tickers: list[str], start: str = "2010-01-01", **_: Any) -> ConnectorRunResult:
        svc = DataIngestionService(self.session)
        results: dict[str, int] = {}
        errors: dict[str, str] = {}
        for ticker in tickers:
            try:
                rows = svc.ingest_daily_prices_incremental(ticker, default_start=start)
                svc.resample_weekly(ticker)
                results[ticker] = rows
            except Exception as exc:
                errors[ticker] = str(exc)
                results[ticker] = 0
        status = "partial" if errors else "ok"
        return ConnectorRunResult(self.provider_id, status, sum(results.values()), details={"tickers": results, "errors": errors})


PRICE_CONNECTORS = (YFinancePricesConnector,)
