from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_source_health import DataConnector
from app.services.connectors.base import BaseConnector, ConnectorDefinition
from app.services.connectors.macro import MACRO_CONNECTORS
from app.services.connectors.news import NEWS_CONNECTORS
from app.services.connectors.optional import OPTIONAL_CONNECTORS
from app.services.connectors.price import PRICE_CONNECTORS


class ConnectorRegistry:
    connector_classes: tuple[type[BaseConnector], ...] = (
        *NEWS_CONNECTORS,
        *MACRO_CONNECTORS,
        *PRICE_CONNECTORS,
        *OPTIONAL_CONNECTORS,
    )

    @classmethod
    def definitions(cls) -> list[ConnectorDefinition]:
        return [connector.definition for connector in cls.connector_classes]

    @classmethod
    def class_map(cls) -> dict[str, type[BaseConnector]]:
        return {connector.definition.provider_id: connector for connector in cls.connector_classes}

    @classmethod
    def get_definition(cls, provider_id: str) -> ConnectorDefinition | None:
        return next((definition for definition in cls.definitions() if definition.provider_id == provider_id), None)

    @classmethod
    def get_class(cls, provider_id: str) -> type[BaseConnector] | None:
        return cls.class_map().get(provider_id)

    @classmethod
    def instantiate(cls, provider_id: str, session: Session) -> BaseConnector | None:
        connector_cls = cls.get_class(provider_id)
        return connector_cls(session) if connector_cls else None

    @classmethod
    def by_category(cls, category: str) -> list[ConnectorDefinition]:
        return sorted(
            [definition for definition in cls.definitions() if definition.category == category],
            key=lambda definition: definition.priority,
        )

    @classmethod
    def enabled_provider_ids(cls, session: Session, categories: list[str] | None = None) -> list[str]:
        stmt = select(DataConnector).where(DataConnector.enabled.is_(True), DataConnector.configured.is_(True))
        if categories:
            stmt = stmt.where(DataConnector.category.in_(categories))
        rows = session.execute(stmt.order_by(DataConnector.priority.asc())).scalars().all()
        return [row.provider_id for row in rows]
