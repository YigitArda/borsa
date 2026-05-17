from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class RateLimitPolicy:
    requests_per_minute: int
    min_sleep_sec: float = 0.0


class RateLimiter:
    def __init__(self, policy: RateLimitPolicy):
        self._policy = policy
        self._interval = 60.0 / max(policy.requests_per_minute, 1)
        self._last = 0.0

    def wait(self) -> None:
        sleep_sec = max(self._policy.min_sleep_sec, self._interval)
        elapsed = time.monotonic() - self._last
        remaining = sleep_sec - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last = time.monotonic()
