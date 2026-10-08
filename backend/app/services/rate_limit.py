"""Rate limiter (P0-04, S1).

Sliding-window token buckets keyed by (bucket_name, actor_key). The
actor key is the caller's user_id if the request is authenticated,
otherwise the client IP.

The store is pluggable via RateLimitStorePort — ``memory`` (default,
one process) or ``redis`` (shared across instances). This module keeps
the FastAPI dependency surface and the policy constants; it does none
of the window arithmetic itself.

Disable in tests with TREASURY_RATE_LIMITS=off. The env var is
consulted per-request so a conftest monkeypatch flips it on and off
without a module reload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import Request

from app.connector import ports, registry
from app.errors import ErrorCode, TreasuryError


def _enabled() -> bool:
    """Off in the test suite; on everywhere else.

    Reads through SecretsPort so a Vault-bound deployment picks the
    same config knob up without an env var.
    """
    value = (
        registry.get(ports.SecretsPort).get("TREASURY_RATE_LIMITS", "on") or "on"
    )
    return value.lower() != "off"


def reset() -> None:
    """Wipe the backing store. Used by tests between cases."""
    registry.get(ports.RateLimitStorePort).clear()


@dataclass
class LimitPolicy:
    """One numeric rule: N requests per `window_seconds`."""

    name: str
    max_requests: int
    window_seconds: float


def _client_ip(request: Request) -> str:
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
    key = f"{policy.name}|{actor_key}"
    store = registry.get(ports.RateLimitStorePort)
    allowed, retry_after = store.hit(
        key, policy.max_requests, policy.window_seconds
    )
    if not allowed:
        raise TreasuryError(
            ErrorCode.RATE_LIMITED,
            (
                f"Rate limit on '{policy.name}' — "
                f"{policy.max_requests} per {int(policy.window_seconds)}s. "
                f"Retry in {retry_after:.0f}s."
            ),
        )


def limit_by_ip(policy: LimitPolicy) -> Callable[..., None]:
    """Dependency factory that keys the bucket by the caller's IP."""

    def _dep(request: Request) -> None:
        _consume(policy, _client_ip(request))

    return _dep


def limit_by_user(policy: LimitPolicy) -> Callable[..., None]:
    """Dependency factory that keys the bucket by the authenticated user.

    Falls back to IP when the bearer token is missing or unreadable —
    the auth dependency further along refuses the request on its own.
    """

    def _dep(request: Request) -> None:
        _consume(policy, _actor_from_request(request))

    return _dep


def _actor_from_request(request: Request) -> str:
    auth = request.headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return _client_ip(request)
    token = auth.split(" ", 1)[1].strip()
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
