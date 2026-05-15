"""Structured JSON logging configuration for the Borsa backend.

Provides:
- JSON-formatted log lines (one per record)
- Correlation-ID propagation per request
- Request/response timing
- Performance metrics helpers
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

import structlog

# ------------------------------------------------------------------
# Context-local correlation ID
# ------------------------------------------------------------------

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Return the current request's correlation ID (or empty string)."""
    return _correlation_id.get()


def set_correlation_id(cid: str | None = None) -> str:
    """Set (or generate) the correlation ID for the current async context."""
    value = cid or str(uuid.uuid4())
    _correlation_id.set(value)
    return value


def clear_correlation_id() -> None:
    """Remove the correlation ID from the current context."""
    _correlation_id.set("")


# ------------------------------------------------------------------
# Structlog processors shared by stdlib + structlog APIs
# ------------------------------------------------------------------

def _add_correlation_id(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    cid = _correlation_id.get()
    if cid:
        event_dict["correlation_id"] = cid
    return event_dict


def _add_timestamp(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    event_dict["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime()) + f"{time.time() % 1:.03f}"[2:]
    return event_dict


SHARED_PROCESSORS: list[Any] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.stdlib.ExtraAdder(),
    _add_timestamp,
    _add_correlation_id,
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
    structlog.processors.UnicodeDecoder(),
]


def configure_logging(log_level: str = "INFO", json: bool = True) -> None:
    """Configure both stdlib ``logging`` and ``structlog``.

    Parameters
    ----------
    log_level:
        Minimum level emitted (DEBUG, INFO, WARNING, ERROR).
    json:
        When ``True`` output compact JSON; otherwise pretty console logs.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    if json:
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=SHARED_PROCESSORS,
        )
    else:
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(colors=True),
            foreign_pre_chain=SHARED_PROCESSORS,
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    # Reduce noise from third-party libs
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    structlog.configure(
        processors=SHARED_PROCESSORS + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


# ------------------------------------------------------------------
# Performance metrics helper
# ------------------------------------------------------------------

class Timer:
    """Simple context manager / decorator for timing blocks of code.

    Usage::

        with Timer("feature_engineering") as t:
            ...
        logger.info("feature_engineering_done", duration_ms=t.elapsed_ms)
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._start: float | None = None
        self.elapsed_ms: float = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._start is not None:
            self.elapsed_ms = (time.perf_counter() - self._start) * 1000

    def log(self, logger: structlog.stdlib.BoundLogger | None = None, **extra: Any) -> None:
        """Emit a structured log line with the timer result."""
        log = logger or structlog.get_logger()
        log.info(
            f"{self.name}_done",
            duration_ms=round(self.elapsed_ms, 3),
            **extra,
        )
