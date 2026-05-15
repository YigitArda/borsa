"""
Macro indicator ingestion via yfinance.

Indicators:
  VIX       → ^VIX
  10Y yield → ^TNX
  S&P 500   → ^GSPC
  Nasdaq    → ^IXIC
  Fed rate  → approximated from 3-month T-bill ^IRX
  CPI proxy → TIP (iShares TIPS ETF — tracks inflation expectations)
  Sector ETFs → XLK, XLF, XLE, XLV, XLI, XLP, XLY, XLU, XLRE, XLB
"""
import logging
from datetime import date

import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.macro import MacroIndicator

logger = logging.getLogger(__name__)

MACRO_TICKERS = {
    "VIX": "^VIX",
    "TNX_10Y": "^TNX",
    "SP500": "^GSPC",
    "NASDAQ": "^IXIC",
    "FED_RATE_PROXY": "^IRX",
    "CPI_PROXY": "TIP",  # iShares TIPS ETF as inflation proxy
}

SECTOR_ETF_MAP = {
    "SECTOR_XLK": "XLK",   # Technology
    "SECTOR_XLF": "XLF",   # Financials
    "SECTOR_XLE": "XLE",   # Energy
    "SECTOR_XLV": "XLV",   # Health Care
    "SECTOR_XLI": "XLI",   # Industrials
    "SECTOR_XLP": "XLP",   # Consumer Staples
    "SECTOR_XLY": "XLY",   # Consumer Discretionary
    "SECTOR_XLU": "XLU",   # Utilities
    "SECTOR_XLRE": "XLRE", # Real Estate
    "SECTOR_XLB": "XLB",   # Materials
}

# Map yfinance sector strings → ETF code used in features
SECTOR_TO_ETF_CODE = {
    "Technology": "SECTOR_XLK",
    "Financial Services": "SECTOR_XLF",
    "Financials": "SECTOR_XLF",
    "Energy": "SECTOR_XLE",
    "Healthcare": "SECTOR_XLV",
    "Health Care": "SECTOR_XLV",
    "Industrials": "SECTOR_XLI",
    "Consumer Defensive": "SECTOR_XLP",
    "Consumer Staples": "SECTOR_XLP",
    "Consumer Cyclical": "SECTOR_XLY",
    "Consumer Discretionary": "SECTOR_XLY",
    "Utilities": "SECTOR_XLU",
    "Real Estate": "SECTOR_XLRE",
    "Basic Materials": "SECTOR_XLB",
    "Materials": "SECTOR_XLB",
    "Communication Services": "SECTOR_XLK",  # map to tech as closest proxy
}


class MacroDataService:
    def __init__(self, session: Session):
        self.session = session

    def ingest_macro(self, start: str = "2010-01-01") -> int:
        total = 0
        all_tickers = {**MACRO_TICKERS, **SECTOR_ETF_MAP}
        for code, symbol in all_tickers.items():
            try:
                df = yf.download(symbol, start=start, auto_adjust=True, progress=False)
                if df.empty:
                    logger.warning(f"No macro data for {symbol}")
                    continue

                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                df = df.reset_index()
                col = "Close" if "Close" in df.columns else "close"
                date_col = "Date" if "Date" in df.columns else "date"

                rows = []
                for _, row in df.iterrows():
                    d = row[date_col]
                    if hasattr(d, "date"):
                        d = d.date()
                    val = row.get(col)
                    if pd.notna(val):
                        rows.append({"indicator_code": code, "date": d, "value": float(val)})

                if rows:
                    stmt = pg_insert(MacroIndicator).values(rows)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["indicator_code", "date"],
                        set_={"value": stmt.excluded.value},
                    )
                    self.session.execute(stmt)
                    total += len(rows)
            except Exception as e:
                logger.error(f"Macro ingest failed {code}: {e}")

        # Derive weekly changes, risk-on score, and sector trends
        self._compute_derived_weekly()
        self.session.commit()
        logger.info(f"Ingested {total} macro rows")
        return total

    def _compute_derived_weekly(self):
        """Compute weekly VIX change, VIX level buckets, stored as additional indicator codes."""
        rows = self.session.execute(
            select(MacroIndicator).where(MacroIndicator.indicator_code == "VIX")
            .order_by(MacroIndicator.date)
        ).scalars().all()

        if not rows:
            return

        df = pd.DataFrame([{"date": r.date, "vix": r.value} for r in rows])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        weekly = df.resample("W-FRI").last()
        weekly["vix_change"] = weekly["vix"].pct_change()
        # Risk-on: VIX < 15 = 1, VIX 15-25 = 0.5, VIX > 25 = 0
        weekly["risk_on_score"] = weekly["vix"].apply(
            lambda v: 1.0 if v < 15 else (0.5 if v < 25 else 0.0) if pd.notna(v) else None
        )

        derived_rows = []
        for idx, row in weekly.iterrows():
            d = idx.date()
            for code, val in [("VIX_WEEKLY", row["vix"]), ("VIX_CHANGE_W", row["vix_change"]), ("RISK_ON_SCORE", row["risk_on_score"])]:
                if pd.notna(val):
                    derived_rows.append({"indicator_code": code, "date": d, "value": float(val)})

        if derived_rows:
            stmt = pg_insert(MacroIndicator).values(derived_rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["indicator_code", "date"],
                set_={"value": stmt.excluded.value},
            )
            self.session.execute(stmt)

    def get_macro_features(self, as_of: date) -> dict[str, float]:
        """Return most recent macro values available on or before as_of."""
        rows = self.session.execute(
            select(MacroIndicator)
            .where(MacroIndicator.date <= as_of)
            .order_by(MacroIndicator.date.desc())
        ).scalars().all()

        seen = {}
        for r in rows:
            if r.indicator_code not in seen:
                seen[r.indicator_code] = r.value
        return seen

    def compute_macro_features_weekly(self) -> dict[date, dict[str, float]]:
        """Return {week_ending_date: {feature_name: value}} for all weeks."""
        rows = self.session.execute(select(MacroIndicator).order_by(MacroIndicator.date)).scalars().all()
        if not rows:
            return {}

        # Pivot to wide
        df = pd.DataFrame([{"date": r.date, "code": r.indicator_code, "value": r.value} for r in rows])
        df["date"] = pd.to_datetime(df["date"])
        wide = df.pivot_table(index="date", columns="code", values="value").sort_index()
        weekly = wide.resample("W-FRI").last().ffill(limit=4)  # forward-fill up to 4 weeks

        # SP500 and Nasdaq 20-week trends
        for col, trend_name in [("SP500", "sp500_trend_20w"), ("NASDAQ", "nasdaq_trend_20w")]:
            if col in weekly.columns:
                weekly[trend_name] = weekly[col].pct_change(20)

        # CPI proxy trend (26-week = ~6-month change in TIP ETF)
        if "CPI_PROXY" in weekly.columns:
            weekly["cpi_proxy_trend_26w"] = weekly["CPI_PROXY"].pct_change(26)

        # Sector ETF 20-week trends
        for code in SECTOR_ETF_MAP:
            if code in weekly.columns:
                weekly[f"{code.lower()}_trend20w"] = weekly[code].pct_change(20)

        result = {}
        for idx, row in weekly.iterrows():
            d = idx.date()
            result[d] = {k: float(v) for k, v in row.items() if pd.notna(v)}

        return result
