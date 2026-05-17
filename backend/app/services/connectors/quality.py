from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.data_source_health import DataConnector
from app.services.connectors.base import ConnectorRunResult


def compute_quality(run_result: ConnectorRunResult, session: Session) -> dict:
    rows_inserted = run_result.rows
    status = run_result.status
    details = run_result.details or {}

    errors = details.get("errors", {})
    tickers = details.get("tickers", {})
    error_rate = len(errors) / max(len(tickers), 1) if tickers else 0.0
    duplicate_rate = 0.0

    rows_updated = details.get("rows_updated", 0)
    rows_skipped = details.get("rows_skipped", 0)

    if status == "ok":
        coverage_score = 1.0 if rows_inserted > 0 else 0.6
        freshness_score = 1.0
    elif status == "partial":
        coverage_score = 0.4
        freshness_score = 0.5
    else:
        coverage_score = 0.0
        freshness_score = 0.0

    fallback_used = details.get("fallback_used", False)

    last_available_at: datetime | None = None
    if status in {"ok", "partial"} and rows_inserted > 0:
        last_available_at = datetime.now(timezone.utc)

    quality = {
        "coverage_score": coverage_score,
        "freshness_score": freshness_score,
        "duplicate_rate": duplicate_rate,
        "error_rate": error_rate,
        "fallback_used": fallback_used,
        "rows_inserted": rows_inserted,
        "rows_updated": rows_updated,
        "last_available_at": last_available_at.isoformat() if last_available_at else None,
    }

    connector_row = session.query(DataConnector).filter_by(provider_id=run_result.provider_id).one_or_none()
    if connector_row is not None:
        connector_row.coverage_score = coverage_score
        connector_row.freshness_score = freshness_score
        if status in {"ok", "partial"}:
            connector_row.last_success_at = last_available_at
        elif status == "failed":
            connector_row.last_failure_at = datetime.now(timezone.utc)
        connector_row.last_status = status
        connector_row.last_message = run_result.message
        session.add(connector_row)

    return quality
