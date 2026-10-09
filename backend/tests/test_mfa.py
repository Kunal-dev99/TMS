"""Phase 2 — TOTP MFA storage, enrollment, verification (BE-2.4..2.7).

Covers:
- mfa_service unit: generate/verify/recovery-codes, fail-closed on
  missing master key, enrollment supersession.
- /auth/mfa/enroll + /auth/mfa/verify + /auth/mfa/status + reissue
  endpoints via the API.
- Behaviour-neutrality: an existing /auth/token sign-in works
  identically; no new mandatory step.
"""
from __future__ import annotations

import pyotp
import pytest
from cryptography.fernet import Fernet

from app import seed_data as s
from app.connector import registry
from app.services import mfa_service


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def mfa_key(monkeypatch):
    """Prime the SecretsPort with a valid Fernet key for the test."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("mfa_master_key", key)
    registry.reset()  # force EnvVarSecrets to re-read on next get()
    yield key
    registry.reset()


@pytest.fixture
def whitfield_id(session):
    """user_id of a.whitfield@... — the user the 'client' fixture signs in as."""
    from app.repo import users as users_repo
    user = users_repo.by_email(session, s.TENANT_ID, "a.whitfield@northgate.example")
    assert user is not None
    return user.id


# --- service: fail-closed without key --------------------------------------


def test_generate_secret_raises_when_no_key(session, monkeypatch):
    monkeypatch.delenv("mfa_master_key", raising=False)
    registry.reset()
    try:
        with pytest.raises(mfa_service.MfaKeyUnavailable):
            mfa_service.generate_secret(session, "u_1", "u1@example.com")
    finally:
        registry.reset()


def test_generate_secret_raises_on_malformed_key(session, monkeypatch):
    monkeypatch.setenv("mfa_master_key", "not-a-valid-fernet-key")
    registry.reset()
    try:
        with pytest.raises(mfa_service.MfaKeyUnavailable, match="not a valid"):
            mfa_service.generate_secret(session, "u_1", "u1@example.com")
    finally:
        registry.reset()


# --- service: happy path ----------------------------------------------------


def test_enroll_round_trip(session, mfa_key, client, whitfield_id):
    # 'client' fixture signs us in as a.whitfield@... (ANALYST).
    _ = client.get("/health")
    user_id = whitfield_id

    result = mfa_service.generate_secret(session, user_id, "test@example.com")
    assert result.secret
    assert result.provisioning_uri.startswith("otpauth://totp/")
    assert "Treasury%20Register" in result.provisioning_uri or \
           "Treasury+Register" in result.provisioning_uri or \
           "Treasury Register" in result.provisioning_uri

    # First verify with a correct code completes enrollment.
    code = pyotp.TOTP(result.secret).now()
    v = mfa_service.verify_code(session, user_id, code)
    assert v.verified is True
    assert v.was_first_verification is True

    # Second verify with a correct code still works, but not 'first'.
    v2 = mfa_service.verify_code(session, user_id, pyotp.TOTP(result.secret).now())
    assert v2.verified is True
    assert v2.was_first_verification is False


def test_verify_wrong_code_returns_false(session, mfa_key, client, whitfield_id):
    _ = client.get("/health")
    user_id = whitfield_id
    mfa_service.generate_secret(session, user_id, "x@x")
    v = mfa_service.verify_code(session, user_id, "000000")
    assert v.verified is False
    assert v.was_first_verification is False


def test_verify_before_enroll_raises(session, mfa_key, client, whitfield_id):
    _ = client.get("/health")
    user_id = whitfield_id
    with pytest.raises(mfa_service.MfaNotEnrolled):
        mfa_service.verify_code(session, user_id, "123456")


def test_reenroll_before_verify_replaces(session, mfa_key, client, whitfield_id):
    _ = client.get("/health")
    user_id = whitfield_id
    first = mfa_service.generate_secret(session, user_id, "x@x")
    second = mfa_service.generate_secret(session, user_id, "x@x")
    assert first.secret != second.secret
    # Old code shouldn't verify against the new secret (overwhelming odds).
    old_code = pyotp.TOTP(first.secret).now()
    v = mfa_service.verify_code(session, user_id, old_code)
    assert v.verified is False


def test_reenroll_after_verify_raises(session, mfa_key, client, whitfield_id):
    _ = client.get("/health")
    user_id = whitfield_id
    result = mfa_service.generate_secret(session, user_id, "x@x")
    mfa_service.verify_code(session, user_id, pyotp.TOTP(result.secret).now())
    with pytest.raises(ValueError, match="already has a verified"):
        mfa_service.generate_secret(session, user_id, "x@x")


# --- recovery codes --------------------------------------------------------


def test_issue_recovery_codes_format(session, mfa_key, client, whitfield_id):
    _ = client.get("/health")
    user_id = whitfield_id
    codes = mfa_service.issue_recovery_codes(session, user_id)
    assert len(codes) == 10
    for c in codes:
        assert len(c) == 14  # XXXX-XXXX-XXXX
        assert c.count("-") == 2
        for part in c.split("-"):
            assert len(part) == 4


def test_consume_recovery_code_once(session, mfa_key, client, whitfield_id):
    _ = client.get("/health")
    user_id = whitfield_id
    codes = mfa_service.issue_recovery_codes(session, user_id)
    assert mfa_service.consume_recovery_code(session, user_id, codes[0]) is True
    assert mfa_service.consume_recovery_code(session, user_id, codes[0]) is False


def test_consume_unknown_recovery_code_returns_false(session, mfa_key, client, whitfield_id):
    _ = client.get("/health")
    user_id = whitfield_id
    mfa_service.issue_recovery_codes(session, user_id)
    assert mfa_service.consume_recovery_code(session, user_id, "ZZZZ-ZZZZ-ZZZZ") is False


def test_reissue_supersedes_old_codes(session, mfa_key, client, whitfield_id):
    _ = client.get("/health")
    user_id = whitfield_id
    old = mfa_service.issue_recovery_codes(session, user_id)
    new = mfa_service.issue_recovery_codes(session, user_id)
    # An old code can no longer be consumed.
    assert mfa_service.consume_recovery_code(session, user_id, old[0]) is False
    assert mfa_service.consume_recovery_code(session, user_id, new[0]) is True


# --- API endpoints ----------------------------------------------------------


def test_enroll_endpoint_requires_auth(session, mfa_key, anonymous):
    r = anonymous.post("/api/v1/auth/mfa/enroll")
    assert r.status_code in (401, 403)


def test_enroll_then_verify_endpoint_flow(session, mfa_key, client):
    r = client.post("/api/v1/auth/mfa/enroll")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["secret"]
    assert body["provisioning_uri"].startswith("otpauth://")
    # qr_data_url may be None if qrcode isn't installed; both OK.

    code = pyotp.TOTP(body["secret"]).now()
    v = client.post("/api/v1/auth/mfa/verify", json={"code": code})
    assert v.status_code == 200, v.text
    vbody = v.json()
    assert vbody["verified"] is True
    assert vbody["was_first_verification"] is True
    assert len(vbody["recovery_codes"]) == 10


def test_verify_wrong_code_returns_400(session, mfa_key, client):
    client.post("/api/v1/auth/mfa/enroll")
    r = client.post("/api/v1/auth/mfa/verify", json={"code": "000000"})
    assert r.status_code == 400
    assert "match" in r.text.lower()


def test_verify_without_enroll_returns_400(session, mfa_key, client):
    r = client.post("/api/v1/auth/mfa/verify", json={"code": "123456"})
    assert r.status_code == 400


def test_status_endpoint_pre_enroll(session, mfa_key, client):
    r = client.get("/api/v1/auth/mfa/status")
    assert r.status_code == 200
    body = r.json()
    assert body["enrolled"] is False
    assert body["verified_at"] is None


def test_status_endpoint_post_verify(session, mfa_key, client):
    body = client.post("/api/v1/auth/mfa/enroll").json()
    code = pyotp.TOTP(body["secret"]).now()
    client.post("/api/v1/auth/mfa/verify", json={"code": code})
    r = client.get("/api/v1/auth/mfa/status")
    assert r.status_code == 200
    body = r.json()
    assert body["enrolled"] is True
    assert body["verified_at"] is not None
    assert body["has_recovery_codes"] is True


def test_reissue_recovery_endpoint(session, mfa_key, client):
    body = client.post("/api/v1/auth/mfa/enroll").json()
    code = pyotp.TOTP(body["secret"]).now()
    first = client.post("/api/v1/auth/mfa/verify", json={"code": code}).json()
    r = client.post("/api/v1/auth/mfa/recovery/reissue")
    assert r.status_code == 200
    second = r.json()
    assert len(second["recovery_codes"]) == 10
    assert set(first["recovery_codes"]).isdisjoint(set(second["recovery_codes"]))


def test_enroll_without_key_returns_503(session, client, monkeypatch):
    monkeypatch.delenv("mfa_master_key", raising=False)
    registry.reset()
    try:
        r = client.post("/api/v1/auth/mfa/enroll")
        assert r.status_code == 503
    finally:
        registry.reset()


# --- behaviour-neutrality ---------------------------------------------------


def test_existing_sign_in_still_works_without_mfa(session, anonymous, mfa_key):
    r = anonymous.post(
        "/api/v1/auth/token",
        json={"email": "a.whitfield@northgate.example", "password": "treasury"},
    )
    assert r.status_code == 200
    assert "token" in r.json()
