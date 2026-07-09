"""
services/rate_limiter.py — Thread-safe sliding-window rate limiter for RailRadar API.
"""

import os
import threading
import time


class RateLimiter:
    """Simple sliding-window limiter: max N requests per 60-second window."""

    def __init__(self, max_requests: int = 10, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    def acquire(self, block: bool = True, timeout: float | None = None) -> bool:
        deadline = time.time() + timeout if timeout is not None else None

        while True:
            with self._lock:
                now = time.time()
                cutoff = now - self.window_seconds
                self._timestamps = [t for t in self._timestamps if t > cutoff]

                if len(self._timestamps) < self.max_requests:
                    self._timestamps.append(now)
                    return True

                if not block:
                    return False

                wait = self._timestamps[0] + self.window_seconds - now

            if deadline is not None and time.time() + wait > deadline:
                return False

            time.sleep(max(wait, 0.01))


_rate_limit = int(os.getenv("RAILRADAR_RATE_LIMIT", "10"))
rate_limiter = RateLimiter(max_requests=_rate_limit)
