"""In-process sliding-window store.

One deque per key, trimmed on each hit. Fine for a single-process
FastAPI on one VM; share-nothing across instances. Swap for Redis
when horizontal scaling actually happens.
"""
from __future__ import annotations

import threading
import time
from collections import deque


class MemoryRateLimitStore:
    name = "memory"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, deque[float]] = {}

    def hit(
        self,
        key: str,
        max_requests: int,
        window_seconds: float,
    ) -> tuple[bool, float]:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= max_requests:
                retry_after = max(0.0, window_seconds - (now - bucket[0]))
                return False, retry_after
            bucket.append(now)
            return True, 0.0

    def clear(self) -> None:
        with self._lock:
            self._buckets.clear()
