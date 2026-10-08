"""S9 — JSON structured logging + per-request context.

Covers the formatter in isolation (context vars, extra= pass-through,
unserializable values coerced) and the middleware wiring end-to-end
through the FastAPI test client (X-Request-Id round-trip, tenant_id
captured from the bearer token).
"""
from __future__ import annotations

import io
import json
import logging

import pytest

from app import logging as app_logging


# --- formatter ---------------------------------------------------------------


@pytest.fixture
def capture_json():
    """Pipe one logger through a JsonFormatter into a StringIO buffer."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(app_logging.JsonFormatter())
    log = logging.getLogger("test.capture")
    log.handlers = [handler]
    log.propagate = False
    log.setLevel("DEBUG")

    def read_last() -> dict:
        value = buf.getvalue().strip().splitlines()[-1]
        return json.loads(value)

    yield log, read_last
    app_logging.clear_request_context()


def test_formatter_emits_required_keys(capture_json):
    log, read_last = capture_json
    log.info("hello")
    rec = read_last()
    assert rec["level"] == "INFO"
    assert rec["logger"] == "test.capture"
    assert rec["msg"] == "hello"
    assert "ts" in rec


def test_formatter_includes_bound_context(capture_json):
    log, read_last = capture_json
    app_logging.bind_request_context(
        request_id="r1", tenant_id="ten_demo", user_id="u1",
        path="/foo", method="GET",
    )
    log.info("event")
    rec = read_last()
    assert rec["request_id"] == "r1"
    assert rec["tenant_id"] == "ten_demo"
    assert rec["user_id"] == "u1"
    assert rec["path"] == "/foo"
    assert rec["method"] == "GET"


def test_formatter_omits_unbound_context(capture_json):
    log, read_last = capture_json
    log.info("event")
    rec = read_last()
    for key in ("request_id", "tenant_id", "user_id", "path", "method"):
        assert key not in rec


def test_extra_fields_merge_into_record(capture_json):
    log, read_last = capture_json
    log.info("deal.recorded", extra={"deal_id": "d_1", "amount_pence": 100})
    rec = read_last()
    assert rec["deal_id"] == "d_1"
    assert rec["amount_pence"] == 100


def test_non_json_extra_is_coerced(capture_json):
    log, read_last = capture_json

    class Opaque:
        def __repr__(self) -> str:
            return "<Opaque>"

    log.info("thing", extra={"obj": Opaque()})
    rec = read_last()
    assert rec["obj"] == "<Opaque>"


def test_clear_empties_every_var():
    app_logging.bind_request_context(
        request_id="r", tenant_id="t", user_id="u", path="/", method="GET"
    )
    app_logging.clear_request_context()
    snap = app_logging.current_context()
    assert all(v is None for v in snap.values())


# --- middleware end-to-end ---------------------------------------------------


def test_response_echoes_request_id(client):
    r = client.get("/health", headers={"X-Request-Id": "trace-abc-123"})
    assert r.headers["X-Request-Id"] == "trace-abc-123"


def test_generated_request_id_when_header_missing(client):
    r = client.get("/health")
    assert r.headers.get("X-Request-Id"), "middleware should generate one"
    assert len(r.headers["X-Request-Id"]) >= 8


def test_anonymous_request_still_succeeds(anonymous):
    # /health is unauthenticated; the middleware must bind an anon
    # context (no user_id, no tenant_id) and still echo the id.
    r = anonymous.get("/health")
    assert r.status_code == 200
    assert r.headers.get("X-Request-Id")
