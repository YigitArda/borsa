"""
FRED (Federal Reserve Economic Data) ingestion service.

Uses the free FRED API to replace proxy macro series with point-in-time
macro data whenever a FRED key is available.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models.macro import MacroIndicator

logger = logging.getLogger(__name__)

FRED_SERIES_MAP: dict[str, str] = {
    "VIXCLS": "VIX",
    "DGS10": "TNX_10Y",
    "DGS2": "TNX_2Y",
    "FEDFUNDS": "FED_RATE",
    "T10Y2Y": "YIELD_CURVE",
    "CPIAUCSL": "CPI_YOY",
    "T10YIE": "INFLATION_EXPECT_10Y",
    "UNRATE": "UNEMPLOYMENT",
    "INDPRO": "INDUSTRIAL_PRODUCTION",
    "BAA10Y": "CREDIT_SPREAD_BBB",
    "TEDRATE": "TED_SPREAD",
    "DCOILWTICO": "OIL_WTI",
    "DTWEXBGS": "DXY_PROXY",
    "GDP": "GDP_YOY",
}


class FREDDataService:
    """Fetches FRED macro series and writes them to ``macro_indicators``."""

    def __init__(self, session: Session):
        self.session = session
        self._fred: Any | None = None

    def _get_fred(self):
        if self._fred is not None:
            return self._fred

        try:
            from fredapi import Fred
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "fredapi is not installed. Install fredapi==0.5.1 to enable FRED ingestion."
            ) from exc

        if not settings.fred_api_key:
            raise ValueError(
                "FRED_API_KEY is not configured. Set it in .env to enable real macro ingestion."
            )

        self._fred = Fred(api_key=settings.fred_api_key)
        return self._fred

    def ingest_series(self, fred_code: str, indicator_code: str, start: str = "2010-01-01") -> int:
        fred = self._get_fred()
        try:
            series = fred.get_series(fred_code, observation_start=start)
        except Exception as exc:
            logger.error("FRED series fetch failed for %s: %s", fred_code, exc)
            return 0

        if series is None or series.empty:
            logger.warning("FRED series empty: %s", fred_code)
            return 0

        if fred_code == "CPIAUCSL":
            series = series.pct_change(12) * 100.0
        elif fred_code == "GDP":
            series = series.pct_change(4) * 100.0

        rows: list[dict[str, Any]] = []
        for dt, value in series.items():
            if pd.isna(value):
                continue
            obs_date = dt.date() if hasattr(dt, "date") else dt
            rows.append(
                {
                    "indicator_code": indicator_code,
                    "date": obs_date,
                    "available_at": datetime.combine(obs_date, datetime.min.time()),
                    "provider_id": "fred_macro",
                    "value": float(value),
                    "source_quality": 0.95,
                }
            )

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
        logger.info("FRED %s -> %s: %d rows", fred_code, indicator_code, len(rows))
        return len(rows)

    def ingest_all(self, start: str = "2010-01-01") -> dict[str, int]:
        results: dict[str, int] = {}
        for fred_code, indicator_code in FRED_SERIES_MAP.items():
            results[fred_code] = self.ingest_series(fred_code, indicator_code, start=start)
        return results

    def get_yield_curve_signal(self, as_of: date) -> dict[str, Any]:
        row = (
            self.session.execute(
                select(MacroIndicator)
                .where(
                    MacroIndicator.indicator_code == "YIELD_CURVE",
                    MacroIndicator.date <= as_of,
                )
                .order_by(MacroIndicator.date.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if row is None:
            return {"yield_curve": None, "inverted": False, "signal": "unknown"}

        value = row.value
        if value is None:
            return {"yield_curve": None, "inverted": False, "signal": "unknown"}

        return {
            "yield_curve": value,
            "inverted": value < 0,
            "signal": "risk_off" if value < 0 else "neutral" if value < 0.5 else "risk_on",
        }

    def get_credit_stress(self, as_of: date) -> dict[str, Any]:
        rows = (
            self.session.execute(
                select(MacroIndicator)
                .where(
                    MacroIndicator.indicator_code == "CREDIT_SPREAD_BBB",
                    MacroIndicator.date <= as_of,
                )
                .order_by(MacroIndicator.date.desc())
                .limit(10)
            )
            .scalars()
            .all()
        )
        valid_values = [r.value for r in rows if r.value is not None]
        if not valid_values:
            return {"credit_spread": None, "stress": False, "signal": "unknown"}

        current = valid_values[0]
        avg = sum(valid_values) / len(valid_values)
        return {
            "credit_spread": current,
            "stress": current > avg * 1.3 if current is not None else False,
            "signal": "stress" if current is not None and current > avg * 1.3 else "normal",
        }
