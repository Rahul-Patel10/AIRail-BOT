"""
services/cache.py

Central in-memory cache used across the Railway Assistant.

Features
--------
✔ Thread-safe
✔ TTL support
✔ Automatic cleanup
✔ Cache statistics
✔ Manual invalidation
✔ Singleton cache
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Optional


# -----------------------------------------
# Cache Entry
# -----------------------------------------

@dataclass
class CacheItem:
    value: Any
    expires_at: float


# -----------------------------------------
# TTL Cache
# -----------------------------------------

class TTLCache:

    def __init__(self):

        self._cache = {}
        self._max_entries = 1000

        self._lock = threading.Lock()

        self.hits = 0
        self.misses = 0

        cleaner = threading.Thread(
            target=self._cleanup_loop,
            daemon=True
        )

        cleaner.start()

    # ---------------------------------

    def get(self, key: str):

        with self._lock:

            item = self._cache.get(key)

            if item is None:
                self.misses += 1
                return None

            if time.time() >= item.expires_at:

                del self._cache[key]
                self.misses += 1
                return None

            self.hits += 1
            return item.value

    # ---------------------------------

    def set(
        self,
        key: str,
        value: Any,
        ttl: int
    ):

        with self._lock:

            self._cache[key] = CacheItem(
                value=value,
                expires_at=time.time() + ttl
            )

            while len(self._cache) > self._max_entries:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]

    # ---------------------------------

    def delete(self, key: str):

        with self._lock:

            if key in self._cache:
                del self._cache[key]

    # ---------------------------------

    def clear(self):

        with self._lock:
            self._cache.clear()

    # ---------------------------------

    def has(self, key: str):

        return self.get(key) is not None

    # ---------------------------------

    def size(self):

        with self._lock:
            return len(self._cache)

    # ---------------------------------

    def stats(self):

        with self._lock:

            total = self.hits + self.misses

            return {

                "entries": len(self._cache),

                "hits": self.hits,

                "misses": self.misses,

                "hit_rate": round(
                    self.hits / total,
                    3
                ) if total else 0.0
            }

    # ---------------------------------

    def _cleanup_loop(self):

        while True:

            now = time.time()

            with self._lock:

                expired = [

                    key

                    for key, value in self._cache.items()

                    if value.expires_at <= now

                ]

                for key in expired:
                    del self._cache[key]

            time.sleep(60)


# ---------------------------------------------------
# Singleton Cache
# ---------------------------------------------------

cache = TTLCache()


# ---------------------------------------------------
# Suggested TTLs
# ---------------------------------------------------

TRAIN_SEARCH_TTL = 300        # 5 minutes

TRAIN_DETAILS_TTL = 86400     # 24 hours

LIVE_STATUS_TTL = 45          # 45 sec

STATION_BOARD_TTL = 60        # 1 minute

ROUTE_TTL = 86400             # 24 hours

LOOKUP_TTL = 604800           # 7 days