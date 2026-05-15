"""
Financial data ingestion via yfinance.

LIMITATION: yfinance fundamentals are NOT point-in-time — they return
today's restated values. We store them with as_of_date=None to mark
this approximation. For real PIT data, use Sharadar or similar.
"""
import logging
import hashlib
from datetime import date

import yfinance as yf
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.financial import FinancialMetric

logger = logging.getLogger(__name__)

FINANCIAL_METRICS = [
    # Valuation
    "pe_ratio", "forward_pe", "price_to_sales", "price_to_book",
    "ev_to_ebitda", "ev_to_revenue",
    # Profitability
    "gross_margin", "operating_margin", "net_margin",
    "roe", "roa", "roic",
    # Growth (TTM)
    "revenue_growth", "earnings_growth", "eps_ttm",
    "net_income_growth",
    # Balance sheet
    "debt_to_equity", "current_ratio", "quick_ratio",
    "free_cashflow", "operating_cashflow",
    "total_cash", "total_debt",
    # Per share
    "book_value_per_share", "revenue_per_share",
    # Market
    "market_cap", "beta", "52_week_high", "52_week_low",
    "shares_outstanding",
]

YFINANCE_MAP = {
    "pe_ratio": "trailingPE",
    "forward_pe": "forwardPE",
    "price_to_sales": "priceToSalesTrailing12Months",
    "price_to_book": "priceToBook",
    "ev_to_ebitda": "enterpriseToEbitda",
    "ev_to_revenue": "enterpriseToRevenue",
    "gross_margin": "grossMargins",
    "operating_margin": "operatingMargins",
    "net_margin": "profitMargins",
    "roe": "returnOnEquity",
    "roa": "returnOnAssets",
    "revenue_growth": "revenueGrowth",
    "earnings_growth": "earningsGrowth",
    "eps_ttm": "trailingEps",
    "debt_to_equity": "debtToEquity",
    "current_ratio": "currentRatio",
    "quick_ratio": "quickRatio",
    "free_cashflow": "freeCashflow",
    "operating_cashflow": "operatingCashflow",
    "total_cash": "totalCash",
    "total_debt": "totalDebt",
    "book_value_per_share": "bookValue",
    "revenue_per_share": "revenuePerShare",
    "market_cap": "marketCap",
    "beta": "beta",
    "52_week_high": "fiftyTwoWeekHigh",
    "52_week_low": "fiftyTwoWeekLow",
    "shares_outstanding": "sharesOutstanding",
}


class FinancialDataService:
    def __init__(self, session: Session):
        self.session = session

    def ingest_financials(self, ticker: str) -> int:
        stock = self.session.execute(select(Stock).where(Stock.ticker == ticker)).scalar_one_or_none()
        if not stock:
            logger.warning(f"Stock not found: {ticker}")
            return 0

        try:
            info = yf.Ticker(ticker).info
        except Exception as e:
            logger.error(f"yfinance info failed for {ticker}: {e}")
            return 0

        today = date.today()
        rows = []
        for metric_name, yf_key in YFINANCE_MAP.items():
            val = info.get(yf_key)
            if val is not None:
                try:
                    rows.append({
                        "stock_id": stock.id,
                        "fiscal_period_end": today,  # approximate — not true PIT
                        "as_of_date": today,
                        "metric_name": metric_name,
                        "value": float(val),
                        "is_ttm": True,
                        "data_source": "yfinance",
                    })
                except (TypeError, ValueError):
                    pass

        if not rows:
            return 0

        stmt = pg_insert(FinancialMetric).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_id", "fiscal_period_end", "metric_name", "as_of_date"],
            set_={"value": stmt.excluded.value, "is_ttm": stmt.excluded.is_ttm, "data_source": stmt.excluded.data_source},
        )
        self.session.execute(stmt)
        self.session.commit()
        logger.info(f"Ingested {len(rows)} financial metrics for {ticker}")
        return len(rows)

    def ingest_pit_csv(self, path: str, data_source: str = "pit_csv") -> int:
        """Import point-in-time financial metrics from a licensed/curated CSV.

        CSV columns:
          ticker,fiscal_period_end,as_of_date,metric_name,value[,is_ttm,data_source]
        """
        df = pd.read_csv(path)
        required = {"ticker", "fiscal_period_end", "as_of_date", "metric_name", "value"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"missing columns: {', '.join(sorted(missing))}")

        rows = []
        for _, row in df.iterrows():
            ticker = str(row["ticker"]).upper()
            stock = self.session.execute(select(Stock).where(Stock.ticker == ticker)).scalar_one_or_none()
            if not stock:
                stock = Stock(ticker=ticker)
                self.session.add(stock)
                self.session.flush()
            rows.append({
                "stock_id": stock.id,
                "fiscal_period_end": pd.to_datetime(row["fiscal_period_end"]).date(),
                "as_of_date": pd.to_datetime(row["as_of_date"]).date(),
                "metric_name": str(row["metric_name"]),
                "value": float(row["value"]) if pd.notna(row["value"]) else None,
                "is_ttm": bool(row.get("is_ttm", False)) if pd.notna(row.get("is_ttm", False)) else False,
                "data_source": row.get("data_source") if pd.notna(row.get("data_source")) else data_source,
            })

        if not rows:
            return 0

        stmt = pg_insert(FinancialMetric).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_id", "fiscal_period_end", "metric_name", "as_of_date"],
            set_={
                "value": stmt.excluded.value,
                "is_ttm": stmt.excluded.is_ttm,
                "data_source": stmt.excluded.data_source,
            },
        )
        self.session.execute(stmt)
        self.session.commit()
        return len(rows)

    def get_financial_features(self, stock_id: int, as_of: date) -> dict[str, float]:
        """Return latest financial metrics available on or before as_of date."""
        rows = self.session.execute(
            select(FinancialMetric)
            .where(
                FinancialMetric.stock_id == stock_id,
                FinancialMetric.as_of_date <= as_of,
            )
            .order_by(FinancialMetric.as_of_date.desc())
        ).scalars().all()

        # Take the most recent value for each metric
        seen = {}
        for r in rows:
            if r.metric_name not in seen:
                seen[r.metric_name] = r.value
        return seen

    def run_all(self, tickers: list[str]) -> dict:
        results = {}
        for ticker in tickers:
            logger.info(f"Financial ingest: {ticker}")
            try:
                results[ticker] = self.ingest_financials(ticker)
            except Exception as e:
                logger.error(f"Financial ingest failed {ticker}: {e}")
                results[ticker] = 0
        return results
