from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar

import requests

T = TypeVar("T")

RETRY_ON_STATUS = [429, 500, 502, 503]
NO_RETRY_ON_STATUS = [400, 401, 403, 404]


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    backoff_seconds: float = 2.0
    retry_on_status: list[int] = field(default_factory=lambda: list(RETRY_ON_STATUS))
    no_retry_on_status: list[int] = field(default_factory=lambda: list(NO_RETRY_ON_STATUS))


def with_retry(fn: Callable[[], T], policy: RetryPolicy) -> T:
    last_exc: Exception | None = None
    for attempt in range(policy.max_attempts):
        try:
            return fn()
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status in policy.no_retry_on_status:
                raise
            if status in policy.retry_on_status:
                last_exc = exc
                if attempt < policy.max_attempts - 1:
                    time.sleep(policy.backoff_seconds * (attempt + 1))
                continue
            raise
        except requests.exceptions.Timeout as exc:
            last_exc = exc
            if attempt < policy.max_attempts - 1:
                time.sleep(policy.backoff_seconds * (attempt + 1))
            continue
        except requests.exceptions.RequestException as exc:
            raise exc from exc
    raise last_exc  # type: ignore[misc]
