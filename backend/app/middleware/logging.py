"""FastAPI middleware for structured request/response logging.

Features:
- Request logging with method, path, query, client IP
- Response logging with status code and timing
- Error logging with stack traces
- Correlation-ID propagation via X-Correlation-Id header
"""

from __future__ import annotations

import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

import structlog

from app.logging_config import set_correlation_id, clear_correlation_id, get_correlation_id

logger = structlog.get_logger("http")


class LoggingMiddleware(BaseHTTPMiddleware):
    """Logs every request/response pair as structured JSON."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        # Extract or generate correlation ID
        cid = request.headers.get("x-correlation-id") or request.headers.get("x-request-id")
        set_correlation_id(cid)

        start = time.perf_counter()
        client = request.client.host if request.client else None

        logger.info(
            "request_started",
            method=request.method,
            path=request.url.path,
            query=str(request.query_params),
            client=client,
        )

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 3),
                error=str(exc),
            )
            raise
        finally:
            clear_correlation_id()

        duration_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 3),
        )

        # Echo correlation ID back to client
        response.headers["x-correlation-id"] = get_correlation_id() or ""
        return response
