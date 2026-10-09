"""Phase 1 — SSO port shape (BE-1.1 .. BE-1.4).

Covers:
- IdentityAssertion has the mfa_passed field (BE-1.1)
- StubOIDCIdentity full round-trip (BE-1.2)
- Factory binds oidc_stub when env var is set; local_password by default
- role_mapper returns empty set when no mappings exist; the right roles
  when they do; is case-sensitive; is per-tenant
"""
from __future__ import annotations

import pytest

from app import seed_data as s
from app.connector import ports, registry
from app.connector.adapters.identity.oidc_stub import StubOIDCIdentity
from app.models import SsoGroupMap
from app.services import role_mapper


# --- BE-1.1 IdentityAssertion shape -----------------------------------------


def test_identity_assertion_carries_mfa_passed_default_false():
    a = ports.IdentityAssertion(
        subject="u1", email="u@x", display_name="U",
    )
    assert a.mfa_passed is False


def test_identity_assertion_mfa_passed_true_round_trips():
    a = ports.IdentityAssertion(
        subject="u1", email="u@x", display_name="U", mfa_passed=True,
    )
    assert a.mfa_passed is True


# --- BE-1.2 StubOIDCIdentity ------------------------------------------------


def test_stub_oidc_round_trip():
    stub = StubOIDCIdentity()

    start = stub.start_login(redirect_uri="https://app.local/auth/callback")
    assert start.state
    assert "redirect_uri=https://app.local/auth/callback" in start.authorize_url
    assert "state=" in start.authorize_url

    code = stub.issue_code(
        subject="sub-123",
        email="alice@example.com",
        display_name="Alice Example",
        groups=("Treasury.HeadOfTreasury",),
        mfa_passed=True,
    )
    assertion = stub.complete_login(code=code, state=start.state)
    assert assertion.subject == "sub-123"
    assert assertion.email == "alice@example.com"
    assert assertion.display_name == "Alice Example"
    assert assertion.groups == ("Treasury.HeadOfTreasury",)
    assert assertion.mfa_passed is True


def test_stub_oidc_refuses_unknown_state():
    stub = StubOIDCIdentity()
    code = stub.issue_code(subject="u", email="u@x", display_name="U")
    with pytest.raises(ValueError, match="unknown state"):
        stub.complete_login(code=code, state="never-issued")


def test_stub_oidc_refuses_code_reuse():
    stub = StubOIDCIdentity()
    start = stub.start_login(redirect_uri="https://app.local/cb")
    code = stub.issue_code(subject="u", email="u@x", display_name="U")
    stub.complete_login(code=code, state=start.state)

    start2 = stub.start_login(redirect_uri="https://app.local/cb")
    with pytest.raises(ValueError, match="unknown or already-consumed"):
        stub.complete_login(code=code, state=start2.state)


def test_stub_oidc_refuses_state_reuse():
    stub = StubOIDCIdentity()
    start = stub.start_login(redirect_uri="https://app.local/cb")
    code1 = stub.issue_code(subject="u", email="u@x", display_name="U")
    stub.complete_login(code=code1, state=start.state)

    code2 = stub.issue_code(subject="u", email="u@x", display_name="U")
    with pytest.raises(ValueError, match="unknown state"):
        stub.complete_login(code=code2, state=start.state)


def test_stub_satisfies_identity_port():
    assert isinstance(StubOIDCIdentity(), ports.IdentityPort)


# --- registry binding -------------------------------------------------------


def test_registry_default_is_local_password(monkeypatch):
    monkeypatch.delenv("IDENTITY_PROVIDER", raising=False)
    registry.reset()
    bound = registry.get(ports.IdentityPort)
    assert bound.name == "local_password"
    registry.reset()


def test_registry_binds_oidc_stub_when_env_set(monkeypatch):
    monkeypatch.setenv("IDENTITY_PROVIDER", "oidc_stub")
    registry.reset()
    try:
        bound = registry.get(ports.IdentityPort)
        assert bound.name == "oidc_stub"
    finally:
        registry.reset()


def test_registry_refuses_unknown_identity_provider(monkeypatch):
    monkeypatch.setenv("IDENTITY_PROVIDER", "nope")
    registry.reset()
    try:
        with pytest.raises(ValueError, match="Unknown IDENTITY_PROVIDER"):
            registry.get(ports.IdentityPort)
    finally:
        registry.reset()


# --- BE-1.3 role_mapper -----------------------------------------------------


def test_role_mapper_empty_when_no_mappings(session):
    roles = role_mapper.roles_for_groups(
        session, s.TENANT_ID, ["any", "groups"]
    )
    assert roles == set()


def test_role_mapper_returns_mapped_role(session):
    session.add(SsoGroupMap(
        id="sgm_1",
        tenant_id=s.TENANT_ID,
        group_claim="Treasury.HeadOfTreasury",
        role="HEAD_OF_TREASURY",
        created_at="2026-10-09T00:00:00Z",
    ))
    session.commit()

    roles = role_mapper.roles_for_groups(
        session, s.TENANT_ID,
        ["Treasury.HeadOfTreasury", "Unmapped.Group"],
    )
    assert roles == {"HEAD_OF_TREASURY"}


def test_role_mapper_is_case_sensitive(session):
    session.add(SsoGroupMap(
        id="sgm_2",
        tenant_id=s.TENANT_ID,
        group_claim="Treasury.CFO",
        role="CFO",
        created_at="2026-10-09T00:00:00Z",
    ))
    session.commit()

    hit = role_mapper.roles_for_groups(session, s.TENANT_ID, ["Treasury.CFO"])
    miss = role_mapper.roles_for_groups(session, s.TENANT_ID, ["treasury.cfo"])
    assert hit == {"CFO"}
    assert miss == set()


def test_role_mapper_is_per_tenant(session):
    from app.models import Tenant
    session.add(Tenant(
        id="ten_other", name="Other", created_at="2026-10-09T00:00:00Z",
    ))
    session.flush()
    session.add(SsoGroupMap(
        id="sgm_3",
        tenant_id="ten_other",
        group_claim="Treasury.Analyst",
        role="ANALYST",
        created_at="2026-10-09T00:00:00Z",
    ))
    session.commit()

    # Demo tenant has no such row.
    seeded = role_mapper.roles_for_groups(
        session, s.TENANT_ID, ["Treasury.Analyst"]
    )
    other = role_mapper.roles_for_groups(
        session, "ten_other", ["Treasury.Analyst"]
    )
    assert seeded == set()
    assert other == {"ANALYST"}


def test_role_mapper_handles_empty_input(session):
    assert role_mapper.roles_for_groups(session, s.TENANT_ID, []) == set()
    assert role_mapper.roles_for_groups(session, s.TENANT_ID, ["", ""]) == set()
