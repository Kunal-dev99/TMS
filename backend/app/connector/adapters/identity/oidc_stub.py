"""Fake OIDC adapter for tests and local dev — no network, no IdP.

Binds via ``IDENTITY_PROVIDER=oidc_stub``. Default remains
``local_password``; this adapter is reachable only when the env var
is set explicitly.

The flow mirrors what a real OIDC adapter (Entra / Auth0 / Okta) will
do, so a test written against this stub stays valid when the real
adapter is swapped in later:

    start_login(redirect_uri)
        -> LoginStart(authorize_url, state)
       # In the real flow, the browser is redirected to authorize_url
       # on the IdP, the user signs in, the IdP redirects back to
       # redirect_uri with ?code=<x>&state=<state>. We fake that round
       # trip in-process.

    complete_login(code, state)
        -> IdentityAssertion(subject, email, groups, mfa_passed, ...)

Codes are issued by ``issue_code()`` for a given user profile and
consumed exactly once by ``complete_login()``. State is validated
by comparing the one returned from ``start_login`` with what the
caller passes back. Any mismatch raises.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from app.connector.ports import IdentityAssertion, LoginStart


@dataclass
class _StubProfile:
    subject: str
    email: str
    display_name: str
    groups: tuple[str, ...] = ()
    mfa_passed: bool = False
    raw_claims: dict = field(default_factory=dict)


class StubOIDCIdentity:
    name = "oidc_stub"

    def __init__(self) -> None:
        # Pending state -> redirect_uri (checked at callback)
        self._states: dict[str, str] = {}
        # Issued codes -> profile that completes them
        self._codes: dict[str, _StubProfile] = {}

    # --- test / dev harness ------------------------------------------------

    def issue_code(
        self,
        *,
        subject: str,
        email: str,
        display_name: str,
        groups: tuple[str, ...] = (),
        mfa_passed: bool = False,
        raw_claims: dict | None = None,
    ) -> str:
        """Prime the stub with a profile; return the one-shot code a test
        passes to ``complete_login``. Not part of the port — stub-only."""
        code = f"code_{secrets.token_hex(8)}"
        self._codes[code] = _StubProfile(
            subject=subject,
            email=email,
            display_name=display_name,
            groups=tuple(groups),
            mfa_passed=mfa_passed,
            raw_claims=dict(raw_claims or {}),
        )
        return code

    # --- port surface ------------------------------------------------------

    def start_login(self, redirect_uri: str) -> LoginStart:
        state = secrets.token_urlsafe(16)
        self._states[state] = redirect_uri
        # Fake authorize URL — a real adapter returns the IdP's.
        authorize_url = (
            f"https://stub-idp.local/authorize"
            f"?redirect_uri={redirect_uri}&state={state}"
        )
        return LoginStart(authorize_url=authorize_url, state=state)

    def complete_login(self, code: str, state: str) -> IdentityAssertion:
        if state not in self._states:
            raise ValueError("stub oidc: unknown state (did start_login run?)")
        profile = self._codes.pop(code, None)
        if profile is None:
            raise ValueError("stub oidc: unknown or already-consumed code")
        # One-shot state too — matches a real adapter's CSRF semantics.
        del self._states[state]
        return IdentityAssertion(
            subject=profile.subject,
            email=profile.email,
            display_name=profile.display_name,
            groups=profile.groups,
            mfa_passed=profile.mfa_passed,
            raw_claims=profile.raw_claims,
        )

    def verify_bearer(self, token: str) -> IdentityAssertion | None:
        # Bearer verification is still the local HMAC token today.
        # The real OIDC adapter will verify the IdP's JWT via JWKS;
        # swapping that in doesn't change the port shape.
        from app.security import read_token

        payload = read_token(token)
        if not payload:
            return None
        return IdentityAssertion(
            subject=str(payload.get("sub", "")),
            email="",
            display_name="",
            groups=(),
            mfa_passed=bool(payload.get("mfa", False)),
            raw_claims={k: v for k, v in payload.items()},
        )
