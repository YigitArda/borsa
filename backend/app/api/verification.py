"""FastAPI router for smoke test / verification endpoints."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.services.verification import SmokeTestRunner, SmokeTestReport, SmokeCheckResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/verification", tags=["verification"])


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------

class CheckResultSchema(BaseModel):
    name: str
    status: str
    message: str
    duration_ms: float
    details: dict[str, Any]


class SmokeReportSchema(BaseModel):
    overall: str
    started_at: datetime
    finished_at: datetime
    checks: list[CheckResultSchema]
    summary: dict[str, int]


class HealthSchema(BaseModel):
    status: str
    timestamp: datetime


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _report_to_schema(report: SmokeTestReport) -> SmokeReportSchema:
    return SmokeReportSchema(
        overall=report.overall,
        started_at=report.started_at,
        finished_at=report.finished_at,
        checks=[
            CheckResultSchema(
                name=c.name,
                status=c.status,
                message=c.message,
                duration_ms=c.duration_ms,
                details=c.details,
            )
            for c in report.checks
        ],
        summary=report.summary,
    )


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@router.get(
    "",
    response_model=SmokeReportSchema,
    status_code=status.HTTP_200_OK,
    summary="Run full smoke test",
    description="Runs the complete end-to-end smoke test suite and returns a detailed report.",
)
async def run_verification() -> SmokeReportSchema:
    runner = SmokeTestRunner()
    report = await runner.run_full_smoke_test()
    return _report_to_schema(report)


@router.get(
    "/status",
    response_model=HealthSchema,
    status_code=status.HTTP_200_OK,
    summary="Quick health check",
    description="Lightweight endpoint that returns the current verification subsystem health.",
)
async def verification_status() -> HealthSchema:
    return HealthSchema(status="ok", timestamp=datetime.utcnow())
