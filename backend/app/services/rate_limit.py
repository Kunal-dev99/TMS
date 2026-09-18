"""In-process rate limiter (P0-04).

Sliding-window token buckets keyed by (bucket_name, actor_key). The
actor key is the caller's user_id if the request is authenticated,
otherwise the client IP. Buckets live in a module-level dict — fine
for a single-process FastAPI on one VM; when we go multi-instance
we'll swap the store for Redis and keep this API.

Every limited endpoint takes a FastAPI Depends(rate_limit(...))
factory that raises TreasuryError(RATE_LIMITED) on refusal, so the
error body reaches the client through the same handler as every
other domain error.

Disable in tests with TREASURY_RATE_LIMITS=off. The env var is
consulted per-request so a conftest monkeypatch flips it on and off
without a module reload.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from fastapi import Request

from app.errors import ErrorCode, TreasuryError


_lock = threading.Lock()
_buckets: dict[tuple[str, str], deque[float]] = {}


def _now() -> float:
    return time.monotonic()


def _enabled() -> bool:
    """Off in the test suite; on everywhere else."""
    return os.environ.get("TREASURY_RATE_LIMITS", "on").lower() != "off"


def reset() -> None:
    """Wipe the in-memory buckets. Used by tests between cases."""
    with _lock:
        _buckets.clear()


@dataclass
class LimitPolicy:
    """One numeric rule: N requests per `window_seconds`."""

    name: str
    max_requests: int
    window_seconds: float


def _client_ip(request: Request) -> str:
    # Prefer the trusted proxy hint if the deployment sets it; fall
    # back to the socket. Caddy on the VM strips X-Forwarded-* from
    # the outside and sets it to the real client — see deployment
    # story. We don't allow the client to spoof it directly.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return f"ip:{fwd.split(',')[0].strip()}"
    if request.client is None:
        return "ip:unknown"
    return f"ip:{request.client.host}"


def _consume(policy: LimitPolicy, actor_key: str) -> None:
    """Record a hit; raise if the bucket is full."""
    if not _enabled():
        return
    now = _now()
    cutoff = now - policy.window_seconds
    key = (policy.name, actor_key)
    with _lock:
        bucket = _buckets.setdefault(key, deque())
        # Trim expired hits.
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= policy.max_requests:
            retry_after = max(0.0, policy.window_seconds - (now - bucket[0]))
            raise TreasuryError(
                ErrorCode.RATE_LIMITED,
                (
                    f"Rate limit on '{policy.name}' — "
                    f"{policy.max_requests} per {int(policy.window_seconds)}s. "
                    f"Retry in {retry_after:.0f}s."
                ),
            )
        bucket.append(now)


def limit_by_ip(policy: LimitPolicy) -> Callable[..., None]:
    """Dependency factory that keys the bucket by the caller's IP.

    Use on anonymous or pre-auth endpoints — /auth/token, /activate.
    """

    def _dep(request: Request) -> None:
        _consume(policy, _client_ip(request))

    return _dep


def limit_by_user(policy: LimitPolicy) -> Callable[..., None]:
    """Dependency factory that keys the bucket by the authenticated user.

    Must be paired with an endpoint that already resolves `Caller`
    (via Depends). FastAPI resolves both, and we read the caller
    from `request.state` set by our own dep on the same request.

    Simplest wiring: read the bearer token, resolve identity via a
    tiny helper here. Any resolution failure falls back to IP so the
    limit still protects the endpoint.
    """

    def _dep(request: Request) -> None:
        actor = _actor_from_request(request)
        _consume(policy, actor)

    return _dep


def _actor_from_request(request: Request) -> str:
    """Best-effort user id from the bearer token; fall back to IP."""
    auth = request.headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return _client_ip(request)
    token = auth.split(" ", 1)[1].strip()
    # Signed tokens are stateless — read the payload without a DB hit.
    # A malformed/expired token still gets a per-IP bucket; the auth
    # dependency further along will refuse the request on its own.
    try:
        from app.security import read_token

        payload = read_token(token)
        if payload and payload.get("sub"):
            return f"user:{payload['sub']}"
    except Exception:
        pass
    return _client_ip(request)


# --- policies (single source of truth) --------------------------------------

SIGN_IN = LimitPolicy(name="auth.sign_in", max_requests=10, window_seconds=60)
ACTIVATION_RESOLVE = LimitPolicy(
    name="activation.resolve", max_requests=30, window_seconds=60
)
ACTIVATION_CONSUME = LimitPolicy(
    name="activation.consume", max_requests=10, window_seconds=60
)
DEAL_CHECK = LimitPolicy(name="deals.check", max_requests=60, window_seconds=60)
PLANNER_DEPLOY = LimitPolicy(
    name="planner.deploy_cash", max_requests=30, window_seconds=60
)
ADVISORY_RUN = LimitPolicy(name="advisory.run", max_requests=30, window_seconds=60)
