from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ConnectorDefinition:
    provider_id: str
    name: str
    category: str
    enabled_by_default: bool
    requires_api_key: bool = False
    priority: int = 100
    rate_limit_per_minute: int | None = None
    capabilities: tuple[str, ...] = ()
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectorRunResult:
    provider_id: str
    status: str
    rows: int = 0
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedNewsItem:
    ticker: str
    headline: str
    url: str
    published_at: datetime | None
    available_at: datetime | None
    source: str
    provider_id: str
    body_excerpt: str | None = None
    source_quality: float | None = None
    fallback_used: bool = False
    raw_payload: dict[str, Any] | None = None


class BaseConnector:
    definition: ConnectorDefinition

    def __init__(self, session: Session):
        self.session = session

    @property
    def provider_id(self) -> str:
        return self.definition.provider_id

    @property
    def category(self) -> str:
        return self.definition.category

    def is_configured(self) -> bool:
        return True

    def run(self, *args, **kwargs) -> ConnectorRunResult:
        raise NotImplementedError

    def skipped(self, message: str, details: dict[str, Any] | None = None) -> ConnectorRunResult:
        return ConnectorRunResult(
            provider_id=self.provider_id,
            status="skipped",
            rows=0,
            message=message,
            details=details or {},
        )


def sum_rows(results: Iterable[ConnectorRunResult]) -> int:
    return sum(result.rows for result in results if result.status == "ok")
