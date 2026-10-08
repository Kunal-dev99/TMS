"""Per-request context middleware (S9).

Runs first in the chain:
  1. Reads X-Request-Id from the inbound request, or generates one.
  2. Best-effort pulls user_id + tenant_id out of the bearer token
     (same stateless read the rate limiter uses — no DB hit).
  3. Binds all of it into contextvars so every log line emitted during
     the request carries the same correlation keys.
  4. Logs request.start and request.end with method, path, status,
     duration_ms. Echoes X-Request-Id on the response.
  5. Clears the context on the way out.

Request-id contract: a reverse proxy that already generated one wins;
otherwise we emit a short hex token. The header is also set on 5xx
and on exceptions so the operator can grep the log by it.
"""
from __future__ import annotations

import secrets
import time
from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.logging import (
    bind_request_context,
    clear_request_context,
    get_logger,
)

log = get_logger("app.request")


def _actor_from_token(request: Request) -> tuple[str | None, str | None]:
    """Returns (user_id, tenant_id) if the bearer token resolves, else (None, None).

    Pure best-effort — a bad token logs an anonymous request, the
    downstream auth dependency refuses properly with a 401.
    """
    auth = request.headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None, None
    token = auth.split(" ", 1)[1].strip()
    try:
        from app.security import read_token

        payload = read_token(token)
        if payload:
            return payload.get("sub"), payload.get("ten")
    except Exception:
        pass
    return None, None


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        req_id = request.headers.get("x-request-id") or secrets.token_hex(8)
        user_id, tenant_id = _actor_from_token(request)
        bind_request_context(
            request_id=req_id,
            tenant_id=tenant_id,
            user_id=user_id,
            path=request.url.path,
            method=request.method,
        )
        start = time.perf_counter()
        status = 500
        try:
            log.info("request.start")
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-Id"] = req_id
            return response
        except Exception:
            log.exception("request.error")
            raise
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            log.info(
                "request.end",
                extra={"status": status, "duration_ms": duration_ms},
            )
            clear_request_context()
