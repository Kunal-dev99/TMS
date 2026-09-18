"""CORS is on and the allow-list is enforced (P0-03).

The Starlette CORSMiddleware always answers 200 to a preflight; the
allow-list only reflects into the Access-Control-Allow-Origin header
when the origin is in the list. So the assertion is on the header,
not the status code.
"""

from __future__ import annotations


def _preflight(client, origin: str):
    return client.options(
        "/api/v1/state",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )


def test_cors_allows_a_default_dev_origin(anonymous):
    r = _preflight(anonymous, "http://localhost:3000")
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert r.headers.get("access-control-allow-credentials") == "true"


def test_cors_allows_the_vm_origin(anonymous):
    r = _preflight(anonymous, "https://treasury-management-system.fusionpractices.com")
    assert (
        r.headers.get("access-control-allow-origin")
        == "https://treasury-management-system.fusionpractices.com"
    )


def test_cors_refuses_an_unlisted_origin(anonymous):
    r = _preflight(anonymous, "https://evil.example.com")
    # Preflight comes back 400 with no allow-origin reflection.
    assert r.headers.get("access-control-allow-origin") is None


def test_cors_exposes_row_count_headers_used_by_the_frontend(anonymous):
    # expose-headers rides on the actual response, not on the preflight.
    r = anonymous.get(
        "/health", headers={"Origin": "http://localhost:3000"}
    )
    exposed = r.headers.get("access-control-expose-headers", "")
    # Both audit + breach CSV write these; the compliance page reads them.
    assert "X-Rows-Matching" in exposed
    assert "X-Rows-Exported" in exposed
