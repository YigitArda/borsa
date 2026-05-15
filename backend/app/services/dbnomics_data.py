"""
DBnomics ingestion service.

DBnomics exposes many international macro series without requiring an API key.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.macro import MacroIndicator

logger = logging.getLogger(__name__)

DBNOMICS_SERIES: list[tuple[str, str, str, str]] = [
    ("OECD", "MEI_CLI", "USA.LI...AA", "OECD_CLI_USA"),
    ("BIS", "total_credit", "Q:US:P:A:M:770:USD:O", "BIS_CREDIT_GDP_USA"),
    ("ECB", "IRS", "M.U2.L.L40.CI.0.EUR.N.Z", "ECB_RATE"),
    ("OECD", "MEI_FIN", "USA.IR3TBB01.ST.M", "OECD_3M_RATE_USA"),
]


class DBnomicsDataService:
    """Fetches DBnomics macro series and writes them to ``macro_indicators``."""

    def __init__(self, session: Session):
        self.session = session

    def ingest_series(
        self,
        provider: str,
        dataset: str,
        series_code: str,
        indicator_code: str,
        start: str = "2010-01-01",
    ) -> int:
        try:
            import dbnomics
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "dbnomics is not installed. Install dbnomics==1.2.7 to enable DBnomics ingestion."
            ) from exc

        try:
            df = dbnomics.fetch_series(
                provider_code=provider,
                dataset_code=dataset,
                series_code=series_code,
            )
        except Exception as exc:
            logger.error("DBnomics fetch failed for %s/%s/%s: %s", provider, dataset, series_code, exc)
            return 0

        if df is None or df.empty:
            logger.warning("DBnomics series empty: %s/%s/%s", provider, dataset, series_code)
            return 0

        if "period" in df.columns:
            df["date"] = pd.to_datetime(df["period"])
        elif "original_period" in df.columns:
            df["date"] = pd.to_datetime(df["original_period"])
        else:
            logger.warning("DBnomics series missing a period column: %s/%s/%s", provider, dataset, series_code)
            return 0

        df = df[df["date"] >= pd.Timestamp(start)]
        value_col = "value" if "value" in df.columns else df.columns[-1]
        df = df.dropna(subset=[value_col])

        rows: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            rows.append(
                {
                    "indicator_code": indicator_code,
                    "date": row["date"].date(),
                    "value": float(row[value_col]),
                }
            )

        if not rows:
            return 0

        stmt = pg_insert(MacroIndicator).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["indicator_code", "date"],
            set_={"value": stmt.excluded.value},
        )
        self.session.execute(stmt)
        self.session.commit()
        logger.info("DBnomics %s/%s -> %s: %d rows", provider, dataset, indicator_code, len(rows))
        return len(rows)

    def ingest_all(self, start: str = "2010-01-01") -> dict[str, int]:
        results: dict[str, int] = {}
        for provider, dataset, series_code, indicator_code in DBNOMICS_SERIES:
            key = f"{provider}/{dataset}"
            results[key] = self.ingest_series(provider, dataset, series_code, indicator_code, start=start)
        return results
