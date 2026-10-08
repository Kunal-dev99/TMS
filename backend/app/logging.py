"""JSON structured logging with per-request context (S9).

stdlib ``logging`` + ``contextvars`` — no third-party dep. Every log
record gets a stable JSON shape and automatically picks up whatever
request context the middleware has bound (request_id, tenant_id,
user_id, path, method).

Usage from any module:
    from app.logging import get_logger
    log = get_logger(__name__)
    log.info("deal.recorded", extra={"deal_id": deal.id})

The 'extra' dict is merged into the JSON record alongside the context
vars. If you need to add a per-call field without squeezing it into
``extra``, use ``log.info("thing", extra={"key": value})``.

structlog is a drop-in upgrade later if we want processor pipelines,
but today's needs are: (1) correlate every log line in a request,
(2) always know which tenant, (3) grep JSON. All three are satisfied.
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

# Keys the formatter will pull out of context on every record.
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_tenant_id: ContextVar[str | None] = ContextVar("tenant_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)
_path: ContextVar[str | None] = ContextVar("path", default=None)
_method: ContextVar[str | None] = ContextVar("method", default=None)


_RESERVED_LOGRECORD = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
}


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per record. Stable key order for grep."""

    def format(self, record: logging.LogRecord) -> str:
        # Base record.
        body: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Context vars — present only when non-null.
        for key, var in (
            ("request_id", _request_id),
            ("tenant_id", _tenant_id),
            ("user_id", _user_id),
            ("path", _path),
            ("method", _method),
        ):
            value = var.get()
            if value is not None:
                body[key] = value
        # Any 'extra={...}' fields the caller passed.
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOGRECORD or key.startswith("_"):
                continue
            if key in body:
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            body[key] = value
        if record.exc_info:
            body["exc"] = self.formatException(record.exc_info)
        return json.dumps(body, separators=(",", ":"))


def configure(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger.

    Called once from main.py at startup. Safe to call again; the
    handler is replaced rather than stacked.
    """
    root = logging.getLogger()
    # Drop any pre-existing handlers (uvicorn's defaults, pytest's capture).
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Quiet the noisier libraries unless the operator asked for debug.
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine"):
        logging.getLogger(noisy).setLevel("WARNING")


def get_logger(name: str) -> logging.Logger:
    """Preferred import for callers; stays stable if we swap in structlog."""
    return logging.getLogger(name)


# --- context bind/clear surface --------------------------------------------


def bind_request_context(
    *,
    request_id: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
    path: str | None = None,
    method: str | None = None,
) -> None:
    """Called by the request-context middleware once per request."""
    if request_id is not None:
        _request_id.set(request_id)
    if tenant_id is not None:
        _tenant_id.set(tenant_id)
    if user_id is not None:
        _user_id.set(user_id)
    if path is not None:
        _path.set(path)
    if method is not None:
        _method.set(method)


def clear_request_context() -> None:
    _request_id.set(None)
    _tenant_id.set(None)
    _user_id.set(None)
    _path.set(None)
    _method.set(None)


def current_context() -> dict[str, str | None]:
    """Snapshot of what the formatter would include. For tests + debugging."""
    return {
        "request_id": _request_id.get(),
        "tenant_id": _tenant_id.get(),
        "user_id": _user_id.get(),
        "path": _path.get(),
        "method": _method.get(),
    }
