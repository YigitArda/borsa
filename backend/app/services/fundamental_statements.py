"""
Balance sheet, income statement, cash flow ingestion via yfinance.

Stores as financial_metrics rows with metric_name prefixes:
  bs_  = balance sheet
  is_  = income statement
  cf_  = cash flow

as_of_date is set to the actual SEC EDGAR filing date so backtest feature
queries (as_of_date <= decision_date) never see data before it was public.
Falls back to fiscal_period_end + 45 days when SEC lookup fails.
"""
import logging
from datetime import date

import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.financial import FinancialMetric
from app.services.sec_edgar import get_filing_dates, get_as_of_date

logger = logging.getLogger(__name__)

# Key line items to extract
INCOME_ITEMS = [
    "TotalRevenue", "GrossProfit", "OperatingIncome", "NetIncome",
    "EBITDA", "BasicEPS", "DilutedEPS",
]
BALANCE_ITEMS = [
    "TotalAssets", "TotalLiabilitiesNetMinorityInterest", "TotalEquityGrossMinorityInterest",
    "CashAndCashEquivalents", "LongTermDebt", "CurrentDebt", "Inventory",
    "AccountsReceivable", "TotalDebt",
]
CASHFLOW_ITEMS = [
    "OperatingCashFlow", "FreeCashFlow", "CapitalExpenditure",
    "RepurchaseOfCapitalStock", "CashDividendsPaid",
]


class FundamentalStatementsService:
    def __init__(self, session: Session):
        self.session = session

    def ingest_statements(self, ticker: str) -> int:
        stock = self.session.execute(select(Stock).where(Stock.ticker == ticker)).scalar_one_or_none()
        if not stock:
            return 0

        try:
            t = yf.Ticker(ticker)
            income = t.income_stmt
            balance = t.balance_sheet
            cashflow = t.cashflow
        except Exception as e:
            logger.error(f"Statements fetch failed {ticker}: {e}")
            return 0

        # Fetch real SEC filing dates once per ticker (falls back to heuristic)
        filing_dates = get_filing_dates(ticker)

        rows = []
        rows += self._extract(stock.id, income, INCOME_ITEMS, prefix="is_", filing_dates=filing_dates)
        rows += self._extract(stock.id, balance, BALANCE_ITEMS, prefix="bs_", filing_dates=filing_dates)
        rows += self._extract(stock.id, cashflow, CASHFLOW_ITEMS, prefix="cf_", filing_dates=filing_dates)

        # Compute net income growth (YoY) from income statement
        if income is not None and not income.empty and "NetIncome" in income.index:
            ni = income.loc["NetIncome"].dropna().sort_index(ascending=False)
            if len(ni) >= 2:
                cols = ni.index.tolist()
                for i in range(len(cols) - 1):
                    cur = ni.iloc[i]
                    prev = ni.iloc[i + 1]
                    if prev and prev != 0:
                        growth = (cur - prev) / abs(prev)
                        period_end = cols[i].date() if hasattr(cols[i], "date") else cols[i]
                        as_of = get_as_of_date(ticker, period_end, filing_dates, is_annual=False)
                        rows.append({
                            "stock_id": stock.id,
                            "fiscal_period_end": period_end,
                            "as_of_date": as_of,
                            "metric_name": "net_income_growth",
                            "value": float(growth),
                            "is_ttm": False,
                        })

        if not rows:
            return 0

        stmt = pg_insert(FinancialMetric).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_id", "fiscal_period_end", "metric_name"],
            set_={"value": stmt.excluded.value},
        )
        self.session.execute(stmt)
        self.session.commit()
        logger.info(f"Statements: {ticker} — {len(rows)} rows")
        return len(rows)

    def _extract(
        self,
        stock_id: int,
        df,
        items: list[str],
        prefix: str,
        filing_dates: dict | None = None,
    ) -> list[dict]:
        rows = []
        if df is None or df.empty:
            return rows
        for item in items:
            if item not in df.index:
                continue
            series = df.loc[item].dropna()
            for period, val in series.items():
                try:
                    period_date = period.date() if hasattr(period, "date") else period
                    # Use actual SEC filing date; fall back to heuristic (+45 days)
                    as_of = get_as_of_date(
                        "",  # ticker not needed — filing_dates dict already resolved
                        period_date,
                        filing_dates=filing_dates,
                        is_annual=False,
                    )
                    rows.append({
                        "stock_id": stock_id,
                        "fiscal_period_end": period_date,
                        "as_of_date": as_of,
                        "metric_name": f"{prefix}{item.lower()}",
                        "value": float(val),
                        "is_ttm": False,
                    })
                except Exception as e:
                    logger.warning("Statement row parse failed [%s/%s]: %s", prefix, item, e)
        return rows

    def run_all(self, tickers: list[str]) -> dict:
        results = {}
        for ticker in tickers:
            try:
                results[ticker] = self.ingest_statements(ticker)
            except Exception as e:
                logger.error(f"Statements failed {ticker}: {e}")
                results[ticker] = 0
        return results
