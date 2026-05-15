"""Macro data ingestion and feature helpers.

Uses FRED and DBnomics when available, with yfinance as a fallback for market
and sector reference series.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models.macro import MacroIndicator

logger = logging.getLogger(__name__)

FRED_FALLBACK_SERIES: dict[str, str] = {
    "VIX": "^VIX",
    "TNX_10Y": "^TNX",
}

YFINANCE_REFERENCE_SERIES: dict[str, str] = {
    "SP500": "^GSPC",
    "NASDAQ": "^IXIC",
    "FED_RATE_PROXY": "^IRX",
    "CPI_PROXY": "TIP",
}

SECTOR_ETF_MAP: dict[str, str] = {
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

# Map yfinance sector strings to ETF code used in features.
SECTOR_TO_ETF_CODE: dict[str, str] = {
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

    @staticmethod
    def _extract_value_column(df: pd.DataFrame) -> str | None:
        for candidate in ("Close", "Adj Close", "close", "adj_close", "value", "Value"):
            if candidate in df.columns:
                return candidate
        return None

    def _upsert_rows(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0

        stmt = pg_insert(MacroIndicator).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["indicator_code", "date"],
            set_={"value": stmt.excluded.value},
        )
        self.session.execute(stmt)
        return len(rows)

    def _ingest_yfinance_series(self, indicator_code: str, symbol: str, start: str) -> int:
        try:
            df = yf.download(symbol, start=start, auto_adjust=True, progress=False)
        except Exception as exc:
            logger.error("yfinance download failed for %s: %s", symbol, exc)
            return 0

        if df.empty:
            logger.warning("No yfinance data for %s", symbol)
            return 0

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        value_col = self._extract_value_column(df)
        if value_col is None:
            logger.warning("No value column found for %s", symbol)
            return 0

        df = df.reset_index()
        date_col = "Date" if "Date" in df.columns else "date"

        rows: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            raw_date = row[date_col]
            value = row.get(value_col)
            if pd.notna(value):
                rows.append(
                    {
                        "indicator_code": indicator_code,
                        "date": raw_date.date() if hasattr(raw_date, "date") else raw_date,
                        "value": float(value),
                    }
                )

        return self._upsert_rows(rows)

    def _ingest_yfinance_map(self, series_map: dict[str, str], start: str) -> int:
        total = 0
        for indicator_code, symbol in series_map.items():
            try:
                total += self._ingest_yfinance_series(indicator_code, symbol, start)
            except Exception as exc:
                logger.error("yfinance ingest failed for %s (%s): %s", indicator_code, symbol, exc)
        return total

    def _ingest_fred(self, start: str) -> int:
        from app.services.fred_data import FREDDataService

        fred_svc = FREDDataService(self.session)
        fred_results = fred_svc.ingest_all(start=start)
        return sum(fred_results.values())

    def _ingest_dbnomics(self, start: str) -> int:
        from app.services.dbnomics_data import DBnomicsDataService

        dbn_svc = DBnomicsDataService(self.session)
        dbn_results = dbn_svc.ingest_all(start=start)
        return sum(dbn_results.values())

    def _has_indicator(self, indicator_code: str) -> bool:
        return (
            self.session.execute(
                select(MacroIndicator.id)
                .where(MacroIndicator.indicator_code == indicator_code)
                .limit(1)
            )
            .first()
            is not None
        )

    def ingest_macro(self, start: str = "2010-01-01", include_external_sources: bool = True) -> int:
        total = 0

        if include_external_sources and settings.fred_api_key:
            try:
                fred_total = self._ingest_fred(start=start)
                total += fred_total
                logger.info("FRED ingest loaded %d rows", fred_total)
            except Exception as exc:
                logger.warning("FRED ingest failed; falling back to yfinance proxies: %s", exc)
        elif include_external_sources:
            logger.warning(
                "FRED_API_KEY is not configured. Falling back to yfinance proxy series "
                "for VIX/TNX_10Y."
            )

        if include_external_sources:
            try:
                dbn_total = self._ingest_dbnomics(start=start)
                total += dbn_total
                logger.info("DBnomics ingest loaded %d rows", dbn_total)
            except ImportError as exc:
                logger.warning("DBnomics dependency missing; skipping external ingest: %s", exc)
            except Exception as exc:
                logger.warning("DBnomics ingest failed: %s", exc)

        fallback_series = {
            code: symbol
            for code, symbol in FRED_FALLBACK_SERIES.items()
            if not self._has_indicator(code)
        }
        if fallback_series:
            total += self._ingest_yfinance_map(fallback_series, start)

        total += self._ingest_yfinance_map(YFINANCE_REFERENCE_SERIES, start)
        total += self._ingest_yfinance_map(SECTOR_ETF_MAP, start)

        self._compute_derived_weekly()
        self.session.commit()
        logger.info("Ingested %d macro rows", total)
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
            lambda v: 1.0 if pd.notna(v) and v < 15 else 0.5 if pd.notna(v) and v < 25 else 0.0 if pd.notna(v) else None
        )

        derived_rows = []
        for idx, row in weekly.iterrows():
            d = idx.date()
            for code, val in [
                ("VIX_WEEKLY", row["vix"]),
                ("VIX_CHANGE_W", row["vix_change"]),
                ("RISK_ON_SCORE", row["risk_on_score"]),
            ]:
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

        seen: dict[str, float] = {}
        for r in rows:
            if r.indicator_code not in seen:
                seen[r.indicator_code] = r.value
        return seen

    @staticmethod
    def _first_available_series(wide: pd.DataFrame, codes: list[str]) -> pd.Series | None:
        for code in codes:
            if code in wide.columns:
                return wide[code]
        return None

    def compute_macro_features_weekly(self) -> dict[date, dict[str, float]]:
        """Return {week_ending_date: {feature_name: value}} for all weeks."""
        rows = self.session.execute(select(MacroIndicator).order_by(MacroIndicator.date)).scalars().all()
        if not rows:
            return {}

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

        yield_curve = self._first_available_series(weekly, ["YIELD_CURVE"])
        if yield_curve is not None:
            weekly["yield_curve_value"] = yield_curve
            weekly["yield_curve_inverted"] = yield_curve.apply(
                lambda v: 1.0 if pd.notna(v) and v < 0 else 0.0 if pd.notna(v) else None
            )

        credit_spread = self._first_available_series(weekly, ["CREDIT_SPREAD_BBB"])
        if credit_spread is not None:
            weekly["credit_spread"] = credit_spread
            rolling_mean = credit_spread.rolling(52, min_periods=8).mean()
            rolling_std = credit_spread.rolling(52, min_periods=8).std()
            weekly["credit_spread_zscore"] = (credit_spread - rolling_mean) / rolling_std.where(rolling_std > 0)

        fed_rate = self._first_available_series(weekly, ["FED_RATE", "FED_RATE_PROXY"])
        if fed_rate is not None:
            weekly["fed_rate"] = fed_rate
            weekly["fed_rate_change"] = fed_rate.diff(4)

        oecd_cli = self._first_available_series(weekly, ["OECD_CLI_USA"])
        if oecd_cli is not None:
            weekly["oecd_cli"] = oecd_cli
            weekly["oecd_cli_momentum"] = oecd_cli.pct_change(4)

        # Sector ETF 20-week trends
        for code in SECTOR_ETF_MAP:
            if code in weekly.columns:
                weekly[f"{code.lower()}_trend20w"] = weekly[code].pct_change(20)

        result: dict[date, dict[str, float]] = {}
        for idx, row in weekly.iterrows():
            d = idx.date()
            result[d] = {k: float(v) for k, v in row.items() if pd.notna(v)}

        return result
