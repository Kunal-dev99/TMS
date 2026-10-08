"""IdentityPort wrapper over today's password + bearer-token flow.

Delegates verification to ``app.security.read_token`` and role lookup
to ``app.repo.users``. Password sign-in stays on the existing
``IdentityService.sign_in`` — this adapter's ``start_login`` /
``complete_login`` raise, because a password flow doesn't have an
authorize URL.

When the OIDC adapter lands (Stage 4) the same shape is honoured, so
callers switch adapters without knowing which flow is bound.
"""

from __future__ import annotations

from app.connector.ports import IdentityAssertion, LoginStart


class LocalPasswordIdentity:
    name = "local_password"

    def start_login(self, redirect_uri: str) -> LoginStart:
        raise NotImplementedError(
            "local_password does not use an authorize redirect. "
            "Call POST /auth/token with credentials instead."
        )

    def complete_login(self, code: str, state: str) -> IdentityAssertion:
        raise NotImplementedError(
            "local_password does not use an OIDC callback."
        )

    def verify_bearer(self, token: str) -> IdentityAssertion | None:
        # Lazy import — keeps port module free of app dependencies.
        from app.security import read_token

        payload = read_token(token)
        if not payload:
            return None
        # Full profile (display_name, groups, etc.) lives in the DB;
        # the assertion just names the subject so callers can look up.
        return IdentityAssertion(
            subject=str(payload.get("sub", "")),
            email="",
            display_name="",
            groups=(),
            raw_claims={k: v for k, v in payload.items()},
        )
