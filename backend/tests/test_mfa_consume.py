"""Phase 3 — MFA consumption + JWT mfa_passed claim (BE-3.1..3.5).

Covers:
- issue_token/read_token round-trip with mfa_passed + mfa_required_at claims
- Backward compatibility: a token with no 'mfa' claim reads as mfa=False
- /auth/mfa/consume with TOTP code
- /auth/mfa/consume with recovery code
- /auth/mfa/consume with a bad code
- require_mfa dependency refuses pre-consume, allows post-consume
"""
from __future__ import annotations

import time

import pyotp
import pytest
from cryptography.fernet import Fernet
from fastapi import Depends

from app import seed_data as s
from app.api.deps import Caller, require_mfa
from app.connector import registry
from app.main import app
from app.security import issue_token, read_token
from app.services import mfa_service


# --- fixtures (duplicated from test_mfa.py so this file is self-contained) ---


@pytest.fixture
def mfa_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("mfa_master_key", key)
    registry.reset()
    yield key
    registry.reset()


@pytest.fixture
def whitfield_id(session):
    from app.repo import users as users_repo
    user = users_repo.by_email(session, s.TENANT_ID, "a.whitfield@northgate.example")
    assert user is not None
    return user.id


# --- BE-3.1 token claim round-trip ------------------------------------------


def test_default_token_has_mfa_false():
    tok = issue_token("u_1", "ten_demo")
    payload = read_token(tok)
    assert payload is not None
    assert payload.get("mfa") is False


def test_mfa_passed_true_round_trips():
    tok = issue_token("u_1", "ten_demo", mfa_passed=True)
    payload = read_token(tok)
    assert payload.get("mfa") is True


def test_mfa_required_at_round_trips():
    deadline = int(time.time()) + 7 * 86400
    tok = issue_token("u_1", "ten_demo", mfa_required_at=deadline)
    payload = read_token(tok)
    assert payload.get("mfa_req_at") == deadline


def test_mfa_required_at_omitted_by_default():
    tok = issue_token("u_1", "ten_demo")
    payload = read_token(tok)
    assert "mfa_req_at" not in payload


# --- /auth/mfa/consume ------------------------------------------------------


def test_consume_with_totp_reissues_mfa_token(mfa_key, client, whitfield_id):
    # Enroll + verify first-code so we have a secret to consume with.
    body = client.post("/api/v1/auth/mfa/enroll").json()
    first = pyotp.TOTP(body["secret"]).now()
    client.post("/api/v1/auth/mfa/verify", json={"code": first})

    # Now consume a fresh TOTP code — reissues the bearer.
    code = pyotp.TOTP(body["secret"]).now()
    r = client.post("/api/v1/auth/mfa/consume", json={"code": code})
    assert r.status_code == 200, r.text
    body2 = r.json()
    assert body2["mfa_passed"] is True
    assert body2["token"]
    # The new token's payload has mfa=True.
    payload = read_token(body2["token"])
    assert payload.get("mfa") is True


def test_consume_with_recovery_code_reissues_mfa_token(mfa_key, client, whitfield_id):
    body = client.post("/api/v1/auth/mfa/enroll").json()
    first = pyotp.TOTP(body["secret"]).now()
    verified = client.post("/api/v1/auth/mfa/verify", json={"code": first}).json()
    recovery = verified["recovery_codes"][0]

    r = client.post("/api/v1/auth/mfa/consume", json={"code": recovery})
    assert r.status_code == 200, r.text
    assert r.json()["mfa_passed"] is True

    # Same recovery code can't be reused.
    r2 = client.post("/api/v1/auth/mfa/consume", json={"code": recovery})
    assert r2.status_code == 400


def test_consume_wrong_totp_returns_400(mfa_key, client, whitfield_id):
    body = client.post("/api/v1/auth/mfa/enroll").json()
    first = pyotp.TOTP(body["secret"]).now()
    client.post("/api/v1/auth/mfa/verify", json={"code": first})

    r = client.post("/api/v1/auth/mfa/consume", json={"code": "000000"})
    assert r.status_code == 400


def test_consume_requires_enrollment(mfa_key, client, whitfield_id):
    r = client.post("/api/v1/auth/mfa/consume", json={"code": "123456"})
    assert r.status_code == 400


def test_consume_requires_code(mfa_key, client, whitfield_id):
    r = client.post("/api/v1/auth/mfa/consume", json={})
    assert r.status_code == 400


# --- require_mfa dependency -------------------------------------------------
#
# Mount a tiny probe endpoint on the app for this test so we can prove the
# dependency behaves correctly without wiring it to a real endpoint (that
# comes in Phase 4). Remove it on teardown.


@pytest.fixture
def mfa_gated_probe():
    @app.get("/__probe/mfa-gated", dependencies=[Depends(require_mfa())])
    def _probe(caller: Caller):
        return {"ok": True, "user_id": caller.user_id, "mfa_passed": caller.mfa_passed}

    yield "/__probe/mfa-gated"

    # Remove the route so it doesn't leak into other tests.
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/__probe/mfa-gated"]


def test_require_mfa_refuses_when_policy_enforces_and_claim_false(
    mfa_gated_probe, client, session
):
    # Phase 4: enforcement is policy-driven. Flip policy on + collapse
    # grace so the dep actually enforces.
    from datetime import datetime, timedelta, timezone
    from app.services import mfa_policy_service
    from app.repo import tenant_settings as settings_repo
    mfa_policy_service.set_policy(session, s.TENANT_ID, mode="required_for_all")
    long_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    p = mfa_policy_service.get_policy(session, s.TENANT_ID)
    settings_repo.upsert(
        session, s.TENANT_ID, "mfa_policy",
        {**p, "activated_at": long_ago},
    )
    session.commit()

    r = client.get(mfa_gated_probe)
    assert r.status_code == 403
    assert "MFA_REQUIRED" in r.text


def test_require_mfa_allows_when_policy_off(mfa_gated_probe, client):
    # Default policy is off → the dep is a no-op even without mfa_passed.
    r = client.get(mfa_gated_probe)
    assert r.status_code == 200
    assert r.json()["mfa_passed"] is False


def test_require_mfa_allows_when_claim_true(
    mfa_key, mfa_gated_probe, client, whitfield_id
):
    # Enroll + verify + consume → fresh bearer with mfa=True.
    body = client.post("/api/v1/auth/mfa/enroll").json()
    first = pyotp.TOTP(body["secret"]).now()
    client.post("/api/v1/auth/mfa/verify", json={"code": first})

    # Wait one second so the next TOTP code is distinct from the verify one
    # (same 30s window would otherwise give an identical code and that's
    # fine, but keeping them distinct makes the test's intent clearer).
    code = pyotp.TOTP(body["secret"]).now()
    consume_resp = client.post("/api/v1/auth/mfa/consume", json={"code": code}).json()
    new_token = consume_resp["token"]

    r = client.get(mfa_gated_probe, headers={"Authorization": f"Bearer {new_token}"})
    assert r.status_code == 200, r.text
    assert r.json()["mfa_passed"] is True


# --- behaviour-neutrality ---------------------------------------------------


def test_regular_signin_token_passes_require_mfa_when_policy_off(mfa_gated_probe, client):
    # Phase 4: default policy is off → the dep is a no-op. A fresh
    # /auth/token bearer (mfa=False) still reaches a gated endpoint.
    r = client.get(mfa_gated_probe)
    assert r.status_code == 200


def test_require_mfa_wired_to_exactly_the_expected_endpoints():
    """Phase 4 wires require_mfa into a specific allow-list of
    sensitive endpoints. Any change here (adding or removing one) is
    a Phase 4+ decision — never a drive-by. If this test fails,
    update this list consciously, don't just make it green.
    """
    expected = {
        ("POST", "/deals/{deal_id}/approve"),
        ("POST", "/admin/access-changes/{request_id}/approve"),
    }
    found: set[tuple[str, str]] = set()
    for route in app.router.routes:
        deps = getattr(route, "dependencies", []) or []
        for dep in deps:
            callable_ = getattr(dep, "dependency", None)
            if callable_ is None:
                continue
            qn = getattr(callable_, "__qualname__", "")
            if "require_mfa" in qn:
                methods = getattr(route, "methods", {"GET"}) or {"GET"}
                # Normalise path — strip the /api/v1 prefix the router mounts under.
                path = getattr(route, "path", "")
                if path.startswith("/api/v1"):
                    path = path[len("/api/v1"):]
                for m in methods:
                    found.add((m, path))

    assert found == expected, (
        f"require_mfa wiring drift. expected={expected}, found={found}. "
        "Update the expected list consciously if this is a deliberate Phase 4+ change."
    )
