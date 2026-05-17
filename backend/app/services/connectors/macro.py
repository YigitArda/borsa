from __future__ import annotations

import importlib.util
from typing import Any

from app.config import settings
from app.services.connectors.base import BaseConnector, ConnectorDefinition, ConnectorRunResult
from app.services.dbnomics_data import DBnomicsDataService
from app.services.fred_data import FREDDataService


class FREDMacroConnector(BaseConnector):
    definition = ConnectorDefinition(
        provider_id="fred_macro",
        name="Federal Reserve Economic Data",
        category="macro",
        enabled_by_default=True,
        requires_api_key=True,
        priority=10,
        rate_limit_per_minute=120,
        capabilities=("us_macro", "rates", "inflation", "credit"),
    )

    def is_configured(self) -> bool:
        return bool(settings.fred_api_key)

    def run(self, *, start: str = "2010-01-01", **_: Any) -> ConnectorRunResult:
        if not self.is_configured():
            return self.skipped("fred_api_key_missing")
        try:
            results = FREDDataService(self.session).ingest_all(start=start)
        except ImportError:
            return self.skipped("fredapi_missing")
        return ConnectorRunResult(self.provider_id, "ok", sum(results.values()), details={"series": results})


class DBnomicsMacroConnector(BaseConnector):
    definition = ConnectorDefinition(
        provider_id="dbnomics_macro",
        name="DBnomics Macro",
        category="macro",
        enabled_by_default=True,
        priority=20,
        rate_limit_per_minute=60,
        capabilities=("global_macro", "oecd", "bis", "ecb"),
    )

    def is_configured(self) -> bool:
        return importlib.util.find_spec("dbnomics") is not None

    def run(self, *, start: str = "2010-01-01", **_: Any) -> ConnectorRunResult:
        if not self.is_configured():
            return self.skipped("dbnomics_missing")
        results = DBnomicsDataService(self.session).ingest_all(start=start)
        return ConnectorRunResult(self.provider_id, "ok", sum(results.values()), details={"series": results})


MACRO_CONNECTORS = (
    FREDMacroConnector,
    DBnomicsMacroConnector,
)
