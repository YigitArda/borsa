from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_source_health import DataConnector, DataSourceHealth
from app.services.connectors.registry import ConnectorRegistry


def record_source_health(
    session: Session,
    *,
    source_name: str,
    source_used: str | None,
    status: str,
    target_ticker: str | None = None,
    week_ending: date | None = None,
    message: str | None = None,
    details: dict | None = None,
) -> DataSourceHealth:
    """Persist an external data-source health event."""
    row = DataSourceHealth(
        source_name=source_name,
        source_used=source_used,
        status=status,
        target_ticker=target_ticker,
        week_ending=week_ending,
        message=message,
        details=details or {},
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


class DataConnectorHealthService:
    def __init__(self, session: Session):
        self.session = session

    def sync_registry(self) -> list[DataConnector]:
        synced: list[DataConnector] = []
        for definition in ConnectorRegistry.definitions():
            connector = ConnectorRegistry.instantiate(definition.provider_id, self.session)
            configured = connector.is_configured() if connector else False
            row = self.session.execute(
                select(DataConnector).where(DataConnector.provider_id == definition.provider_id)
            ).scalar_one_or_none()

            if row is None:
                row = DataConnector(
                    provider_id=definition.provider_id,
                    name=definition.name,
                    category=definition.category,
                    enabled=definition.enabled_by_default,
                    requires_api_key=definition.requires_api_key,
                    configured=configured,
                    priority=definition.priority,
                    rate_limit_per_minute=definition.rate_limit_per_minute,
                    config=definition.config,
                    capabilities=list(definition.capabilities),
                    last_status="unknown",
                )
                self.session.add(row)
            else:
                row.name = definition.name
                row.category = definition.category
                row.requires_api_key = definition.requires_api_key
                row.configured = configured
                row.priority = definition.priority
                row.rate_limit_per_minute = definition.rate_limit_per_minute
                row.config = definition.config
                row.capabilities = list(definition.capabilities)
                row.updated_at = datetime.now(timezone.utc)

            synced.append(row)

        self.session.commit()
        return synced

    def record(
        self,
        *,
        provider_id: str,
        status: str,
        rows: int = 0,
        message: str | None = None,
        details: dict | None = None,
        target_ticker: str | None = None,
        week_ending: date | None = None,
    ) -> DataSourceHealth:
        now = datetime.now(timezone.utc)
        definition = ConnectorRegistry.get_definition(provider_id)
        source_name = definition.name if definition else provider_id
        row = DataSourceHealth(
            source_name=source_name,
            source_used=provider_id,
            status=status,
            target_ticker=target_ticker,
            week_ending=week_ending,
            message=message,
            details={**(details or {}), "rows": rows},
        )
        self.session.add(row)

        connector_row = self.session.execute(
            select(DataConnector).where(DataConnector.provider_id == provider_id)
        ).scalar_one_or_none()
        if connector_row is not None:
            connector_row.last_status = status
            connector_row.last_message = message
            connector_row.updated_at = now
            if status == "ok":
                connector_row.last_success_at = now
                connector_row.freshness_score = 1.0
            elif status in {"failed", "partial"}:
                connector_row.last_failure_at = now
                connector_row.freshness_score = 0.5 if status == "partial" else 0.0
            elif status == "skipped":
                connector_row.freshness_score = 0.0
            connector_row.coverage_score = self._coverage_score(status, rows)
            connector_row.quality_score = self._quality_score(provider_id, status)

        self.session.commit()
        self.session.refresh(row)
        return row

    def list_status(self, category: str | None = None) -> list[DataConnector]:
        self.sync_registry()
        stmt = select(DataConnector)
        if category:
            stmt = stmt.where(DataConnector.category == category)
        return self.session.execute(stmt.order_by(DataConnector.category, DataConnector.priority)).scalars().all()

    def _coverage_score(self, status: str, rows: int) -> float:
        if status == "ok" and rows > 0:
            return 1.0
        if status == "ok":
            return 0.6
        if status == "partial":
            return 0.4
        return 0.0

    def _quality_score(self, provider_id: str, status: str) -> float:
        if status not in {"ok", "partial"}:
            return 0.0
        if provider_id.startswith("sec"):
            return 0.95
        if provider_id.startswith("fred"):
            return 0.95
        if provider_id.startswith("gdelt"):
            return 0.8
        if provider_id.startswith("dbnomics"):
            return 0.8
        if provider_id.startswith("yfinance"):
            return 0.55
        return 0.5
