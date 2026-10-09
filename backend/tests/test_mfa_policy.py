"""Phase 4 — per-tenant MFA policy + grace window + enforcement.

Covers:
- mfa_policy_service: read/write/default, mode transitions stamp
  activated_at correctly, is_mfa_required by mode + role + grace,
  required_by() returns the right ISO deadline.
- /deals/{deal_id}/approve: refused with 403 MFA_REQUIRED when policy
  enforces + grace elapsed; allowed when policy off (today's default);
  allowed when inside grace; allowed after /auth/mfa/consume.
- /auth/me: mfa.policy_mode + mfa.required_by + mfa.passed_this_session
  surfaces reflect reality.
- Demo tenant default-off invariant: without any policy write, every
  behaviour matches pre-Phase-4.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from cryptography.fernet import Fernet

from app import seed_data as s
from app.connector import registry
from app.services import mfa_policy_service, mfa_service


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def mfa_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("mfa_master_key", key)
    registry.reset()
    yield key
    registry.reset()


# --- service: defaults + read/write ----------------------------------------


def test_default_policy_is_off(session):
    p = mfa_policy_service.get_policy(session, s.TENANT_ID)
    assert p["mode"] == "off"
    assert p["activated_at"] is None
    assert p["grace_days"] == 7


def test_set_policy_from_off_stamps_activated_at(session):
    p = mfa_policy_service.set_policy(
        session, s.TENANT_ID, mode="required_for_all"
    )
    session.commit()
    assert p["mode"] == "required_for_all"
    assert p["activated_at"] is not None


def test_set_policy_off_clears_activated_at(session):
    mfa_policy_service.set_policy(session, s.TENANT_ID, mode="required_for_all")
    mfa_policy_service.set_policy(session, s.TENANT_ID, mode="off")
    session.commit()
    p = mfa_policy_service.get_policy(session, s.TENANT_ID)
    assert p["mode"] == "off"
    assert p["activated_at"] is None


def test_set_policy_tightening_preserves_activated_at(session):
    first = mfa_policy_service.set_policy(
        session, s.TENANT_ID, mode="required_for_sensitive_roles"
    )
    second = mfa_policy_service.set_policy(
        session, s.TENANT_ID, mode="required_for_all"
    )
    session.commit()
    assert first["activated_at"] == second["activated_at"], (
        "Tightening (sensitive → all) must NOT reset grace."
    )


def test_set_policy_refuses_unknown_mode(session):
    with pytest.raises(ValueError, match="Unknown MFA mode"):
        mfa_policy_service.set_policy(session, s.TENANT_ID, mode="paranoid")


# --- service: is_mfa_required ----------------------------------------------


def test_is_mfa_required_off(session):
    assert not mfa_policy_service.is_mfa_required(session, s.TENANT_ID, ["CFO"])


def test_is_mfa_required_optional(session):
    mfa_policy_service.set_policy(session, s.TENANT_ID, mode="optional")
    session.commit()
    assert not mfa_policy_service.is_mfa_required(session, s.TENANT_ID, ["CFO"])


def test_is_mfa_required_inside_grace(session):
    # Just activated → inside the 7-day grace → not yet enforcing.
    mfa_policy_service.set_policy(session, s.TENANT_ID, mode="required_for_all")
    session.commit()
    assert not mfa_policy_service.is_mfa_required(session, s.TENANT_ID, ["CFO"])


def test_is_mfa_required_after_grace_required_for_all(session):
    mfa_policy_service.set_policy(session, s.TENANT_ID, mode="required_for_all")
    session.commit()
    past_grace = datetime.now(timezone.utc) + timedelta(days=8)
    assert mfa_policy_service.is_mfa_required(
        session, s.TENANT_ID, ["ANALYST"], now=past_grace
    )
    assert mfa_policy_service.is_mfa_required(
        session, s.TENANT_ID, ["CFO"], now=past_grace
    )


def test_is_mfa_required_sensitive_roles_only(session):
    mfa_policy_service.set_policy(
        session, s.TENANT_ID, mode="required_for_sensitive_roles"
    )
    session.commit()
    past_grace = datetime.now(timezone.utc) + timedelta(days=8)
    assert mfa_policy_service.is_mfa_required(
        session, s.TENANT_ID, ["CFO"], now=past_grace
    )
    assert not mfa_policy_service.is_mfa_required(
        session, s.TENANT_ID, ["ANALYST"], now=past_grace
    )
    assert mfa_policy_service.is_mfa_required(
        session, s.TENANT_ID, ["ANALYST", "ADMIN"], now=past_grace
    )


# --- service: required_by (nag banner deadline) ----------------------------


def test_required_by_none_when_off(session):
    assert mfa_policy_service.required_by(session, s.TENANT_ID, ["CFO"]) is None


def test_required_by_set_when_enforcing(session):
    mfa_policy_service.set_policy(session, s.TENANT_ID, mode="required_for_all")
    session.commit()
    dl = mfa_policy_service.required_by(session, s.TENANT_ID, ["CFO"])
    assert dl is not None
    assert dl.endswith("Z")


def test_required_by_none_for_exempt_role(session):
    mfa_policy_service.set_policy(
        session, s.TENANT_ID, mode="required_for_sensitive_roles"
    )
    session.commit()
    assert mfa_policy_service.required_by(session, s.TENANT_ID, ["ANALYST"]) is None


# --- enforcement at the HTTP layer ------------------------------------------


P = 100  # pence per pound, matches test_identity.py convention


def _approve_deal_body():
    return {"role": "ANALYST"}


def _propose_deal_as(client) -> str:
    """Propose a small deal via the API and return its id."""
    r = client.post(
        "/api/v1/deals",
        json={
            "counterparty_id": "cp_meridian",
            "instrument": "DEPOSIT",
            "principal_pence": 500_000 * P,
            "tenor_months": 6,
            "rate_bp": 425,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["deal"]["id"]


def test_approve_deal_default_off_unchanged(client, signer):
    """Demo tenant default policy is off → /deals/{id}/approve behaves
    exactly as pre-Phase 4 (no MFA refusal)."""
    deal_id = _propose_deal_as(client)
    r = signer.post(f"/api/v1/deals/{deal_id}/approve", json=_approve_deal_body())
    # Not asserting 200 — the business logic may still refuse (role,
    # scope, etc.). We only assert it was NOT refused with MFA_REQUIRED.
    assert "MFA_REQUIRED" not in r.text


def test_approve_deal_refuses_without_mfa_when_policy_on(session, client, signer):
    mfa_policy_service.set_policy(session, s.TENANT_ID, mode="required_for_all")
    # Collapse grace artificially by rewinding activated_at.
    long_ago = datetime.now(timezone.utc) - timedelta(days=30)
    p = mfa_policy_service.get_policy(session, s.TENANT_ID)
    from app.repo import tenant_settings as settings_repo
    settings_repo.upsert(
        session, s.TENANT_ID, "mfa_policy",
        {**p, "activated_at": long_ago.isoformat(timespec="seconds").replace("+00:00", "Z")},
    )
    session.commit()

    deal_id = _propose_deal_as(client)

    r = signer.post(f"/api/v1/deals/{deal_id}/approve", json=_approve_deal_body())
    assert r.status_code == 403
    assert "MFA_REQUIRED" in r.text

    # Flip back to off; same request now goes through to business logic.
    mfa_policy_service.set_policy(session, s.TENANT_ID, mode="off")
    session.commit()
    r2 = signer.post(f"/api/v1/deals/{deal_id}/approve", json=_approve_deal_body())
    assert "MFA_REQUIRED" not in r2.text


def test_approve_deal_allowed_after_mfa_consume(session, mfa_key, client, signer):
    # Enroll + verify + consume as the signer, then flip policy on.
    enroll = signer.post("/api/v1/auth/mfa/enroll").json()
    first = pyotp.TOTP(enroll["secret"]).now()
    signer.post("/api/v1/auth/mfa/verify", json={"code": first})
    code = pyotp.TOTP(enroll["secret"]).now()
    new_bearer = signer.post(
        "/api/v1/auth/mfa/consume", json={"code": code}
    ).json()["token"]

    # Force policy on + collapse grace.
    mfa_policy_service.set_policy(session, s.TENANT_ID, mode="required_for_all")
    long_ago = datetime.now(timezone.utc) - timedelta(days=30)
    p = mfa_policy_service.get_policy(session, s.TENANT_ID)
    from app.repo import tenant_settings as settings_repo
    settings_repo.upsert(
        session, s.TENANT_ID, "mfa_policy",
        {**p, "activated_at": long_ago.isoformat(timespec="seconds").replace("+00:00", "Z")},
    )
    session.commit()

    deal_id = _propose_deal_as(client)

    # Use the MFA-passed bearer.
    r = signer.post(
        f"/api/v1/deals/{deal_id}/approve",
        json=_approve_deal_body(),
        headers={"Authorization": f"Bearer {new_bearer}"},
    )
    assert "MFA_REQUIRED" not in r.text


# --- /auth/me surface -------------------------------------------------------


def test_auth_me_mfa_block_default(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    mfa = r.json().get("mfa")
    assert mfa is not None
    assert mfa["policy_mode"] == "off"
    assert mfa["required_by"] is None
    assert mfa["enrolled"] is False
    assert mfa["passed_this_session"] is False


def test_auth_me_shows_required_by_when_policy_on(session, client):
    mfa_policy_service.set_policy(session, s.TENANT_ID, mode="required_for_all")
    session.commit()
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    mfa = r.json()["mfa"]
    assert mfa["policy_mode"] == "required_for_all"
    assert mfa["required_by"] is not None


def test_auth_me_shows_passed_this_session_after_consume(mfa_key, client, session):
    enroll = client.post("/api/v1/auth/mfa/enroll").json()
    first = pyotp.TOTP(enroll["secret"]).now()
    client.post("/api/v1/auth/mfa/verify", json={"code": first})
    code = pyotp.TOTP(enroll["secret"]).now()
    new_bearer = client.post(
        "/api/v1/auth/mfa/consume", json={"code": code}
    ).json()["token"]

    r = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {new_bearer}"},
    )
    assert r.status_code == 200
    assert r.json()["mfa"]["passed_this_session"] is True
    assert r.json()["mfa"]["enrolled"] is True
