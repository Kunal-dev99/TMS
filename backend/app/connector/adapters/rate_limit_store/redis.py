"""Redis-backed sliding-window store.

One sorted set per key, score = unix-time (ms). Each hit:
  1. ZREMRANGEBYSCORE: drop anything older than window.
  2. ZCARD: count what remains.
  3. If under cap: ZADD now; EXPIRE key window_seconds*2 (safety); return allowed.
  4. If at cap: ZRANGE 0 0 WITHSCORES to compute retry_after; return refused.

All four commands fit in one MULTI/EXEC pipeline, so N instances
share one bucket without a race.

Bound when ``RATE_LIMIT_STORE=redis``. ``REDIS_URL`` is read from
SecretsPort (so vault wiring is uniform with every other secret).

redis-py is an optional import; a deployment without it must leave
``RATE_LIMIT_STORE`` at the default ``memory``.
"""
from __future__ import annotations

import time
from typing import Any


class RedisRateLimitStore:
    name = "redis"

    def __init__(self, redis_client: Any, namespace: str = "rl") -> None:
        self._r = redis_client
        self._ns = namespace

    def _key(self, key: str) -> str:
        return f"{self._ns}:{key}"

    def hit(
        self,
        key: str,
        max_requests: int,
        window_seconds: float,
    ) -> tuple[bool, float]:
        now_ms = int(time.time() * 1000)
        window_ms = int(window_seconds * 1000)
        cutoff_ms = now_ms - window_ms
        rkey = self._key(key)

        pipe = self._r.pipeline()
        pipe.zremrangebyscore(rkey, 0, cutoff_ms)
        pipe.zcard(rkey)
        pipe.zrange(rkey, 0, 0, withscores=True)
        _, count, oldest = pipe.execute()

        if count >= max_requests:
            if oldest:
                oldest_ms = int(oldest[0][1])
                retry_after = max(0.0, (window_ms - (now_ms - oldest_ms)) / 1000.0)
            else:
                retry_after = window_seconds
            return False, retry_after

        pipe = self._r.pipeline()
        # Score + member use the same timestamp — unique enough for the
        # bucket, and prevents duplicate-score collisions across threads.
        pipe.zadd(rkey, {f"{now_ms}:{id(self)}": now_ms})
        # Safety expiry — if traffic stops the key cleans itself.
        pipe.expire(rkey, max(1, int(window_seconds * 2)))
        pipe.execute()
        return True, 0.0

    def clear(self) -> None:
        # Scan + delete every key under our namespace. Only called by
        # tests; a prod call would be a very bad idea.
        cursor = 0
        while True:
            cursor, keys = self._r.scan(cursor=cursor, match=f"{self._ns}:*", count=200)
            if keys:
                self._r.delete(*keys)
            if cursor == 0:
                break


def connect(url: str) -> Any:
    """Build a redis-py client. Isolated so a deployment without
    redis-py installed can still import the rest of the module."""
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(url, decode_responses=True)
