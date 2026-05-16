from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.data_source_health import DataSourceHealth


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
