"""Rate limiter tests (P0-04).

Flips TREASURY_RATE_LIMITS back on (conftest turns it off for every
other test) and pushes each protected endpoint past its bucket.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def rate_limits_on(monkeypatch):
    from app.services import rate_limit

    monkeypatch.setenv("TREASURY_RATE_LIMITS", "on")
    rate_limit.reset()
    yield
    rate_limit.reset()


def test_sign_in_rate_limit_per_ip(anonymous):
    from app.services import rate_limit

    # SIGN_IN policy is 10/min per IP. Eleventh call must fail with
    # RATE_LIMITED even though the credentials are wrong (auth error
    # order doesn't matter — the limiter runs BEFORE the endpoint body).
    body = {"email": "wrong@example.com", "password": "nope"}
    responses = [anonymous.post("/api/v1/auth/token", json=body) for _ in range(11)]
    # First N are 401 (bad creds) — but the 11th must be 429.
    assert responses[-1].status_code == 429, responses[-1].text
    assert responses[-1].json()["error"]["code"] == "RATE_LIMITED"


def test_deals_check_rate_limit_per_user(client):
    from app.services import rate_limit as rl

    # Tighten the policy for the test so we don't have to fire 60
    # requests. Restore in the finally.
    original_max = rl.DEAL_CHECK.max_requests
    rl.DEAL_CHECK.max_requests = 3
    rl.reset()
    try:
        body = {
            "counterparty_id": "cp_meridian",
            "instrument": "DEPOSIT",
            "principal_pence": 500_000_00,
            "tenor_months": 6,
            "rate_bp": 425,
        }
        # 3 succeed, 4th trips.
        for _ in range(3):
            r = client.post("/api/v1/deals/check", json=body)
            assert r.status_code == 200, r.text
        r = client.post("/api/v1/deals/check", json=body)
        assert r.status_code == 429, r.text
        assert r.json()["error"]["code"] == "RATE_LIMITED"
    finally:
        rl.DEAL_CHECK.max_requests = original_max


def test_disabled_flag_bypasses_the_limit(anonymous, monkeypatch):
    # Belt-and-braces: with the env off, even a very tight policy
    # never fires. Same env knob the whole test suite relies on.
    from app.services import rate_limit as rl

    monkeypatch.setenv("TREASURY_RATE_LIMITS", "off")
    rl.reset()
    original_max = rl.SIGN_IN.max_requests
    rl.SIGN_IN.max_requests = 1
    try:
        body = {"email": "wrong@example.com", "password": "nope"}
        # 20 attempts, none should hit 429.
        for _ in range(20):
            r = anonymous.post("/api/v1/auth/token", json=body)
            assert r.status_code != 429, r.text
    finally:
        rl.SIGN_IN.max_requests = original_max
