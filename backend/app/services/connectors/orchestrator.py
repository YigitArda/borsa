from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.services.connectors.base import ConnectorRunResult
from app.services.connectors.registry import ConnectorRegistry
from app.services.data_source_health import DataConnectorHealthService


class ConnectorOrchestrator:
    def __init__(self, session: Session):
        self.session = session
        self.health = DataConnectorHealthService(session)

    def sync_registry(self) -> list[dict[str, Any]]:
        rows = self.health.sync_registry()
        return [self._serialize_connector(row) for row in rows]

    def run(
        self,
        *,
        categories: list[str] | None = None,
        provider_ids: list[str] | None = None,
        tickers: list[str] | None = None,
        start: str = "2010-01-01",
        as_of_date: date | None = None,
        lookback_days: int | None = None,
    ) -> dict[str, Any]:
        self.health.sync_registry()
        providers = provider_ids or ConnectorRegistry.enabled_provider_ids(self.session, categories)
        results: list[ConnectorRunResult] = []

        for provider_id in providers:
            connector = ConnectorRegistry.instantiate(provider_id, self.session)
            if connector is None:
                result = ConnectorRunResult(provider_id, "skipped", message="unknown_provider")
            elif not connector.is_configured():
                result = connector.skipped("connector_not_configured")
            else:
                try:
                    result = connector.run(
                        tickers=tickers or [],
                        start=start,
                        as_of_date=as_of_date,
                        lookback_days=lookback_days or self._default_lookback(provider_id),
                    )
                except Exception as exc:
                    import logging as _logging
                    _logging.getLogger(__name__).error(
                        "Connector %s run failed: %s", provider_id, exc, exc_info=True
                    )
                    result = ConnectorRunResult(provider_id, "failed", message=str(exc))

            self.health.record(
                provider_id=result.provider_id,
                status=result.status,
                rows=result.rows,
                message=result.message,
                details=result.details,
            )
            results.append(result)

        return {
            "status": "ok",
            "providers": [self._serialize_result(result) for result in results],
            "total_rows": sum(result.rows for result in results),
        }

    def status(self, category: str | None = None) -> list[dict[str, Any]]:
        return [self._serialize_connector(row) for row in self.health.list_status(category)]

    def _default_lookback(self, provider_id: str) -> int:
        if provider_id == "sec_edgar_news":
            return 30
        return 7

    def _serialize_result(self, result: ConnectorRunResult) -> dict[str, Any]:
        return {
            "provider_id": result.provider_id,
            "status": result.status,
            "rows": result.rows,
            "message": result.message,
            "details": result.details,
        }

    def _serialize_connector(self, row) -> dict[str, Any]:
        return {
            "provider_id": row.provider_id,
            "name": row.name,
            "category": row.category,
            "enabled": row.enabled,
            "requires_api_key": row.requires_api_key,
            "configured": row.configured,
            "priority": row.priority,
            "rate_limit_per_minute": row.rate_limit_per_minute,
            "capabilities": row.capabilities or [],
            "last_status": row.last_status,
            "last_success_at": row.last_success_at.isoformat() if row.last_success_at else None,
            "last_failure_at": row.last_failure_at.isoformat() if row.last_failure_at else None,
            "last_message": row.last_message,
            "coverage_score": row.coverage_score,
            "freshness_score": row.freshness_score,
            "quality_score": row.quality_score,
        }
