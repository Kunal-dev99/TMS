"""Signing in. Phase 1.5.

Three endpoints, and they are the only ones that do not need a token.

Document 4 names Entra ID single sign on across all three systems as the
destination. This is what holds until then, and it is deliberately the
smallest thing that closes the gap rather than an identity system in its own
right.
"""

from fastapi import APIRouter

from app.api.deps import Caller, Ctx
from app.schemas import requests as rq
from app.services.identity_service import IdentityService

router = APIRouter(tags=["Identity"])


@router.post("/auth/token")
def sign_in(body: rq.SignInRequest, ctx: Ctx) -> dict:
    """Exchange an email address and a password for a bearer token."""
    from app.services.permissions import permissions_for_roles

    principal, token = IdentityService(ctx.session, ctx.tenant_id).sign_in(
        body.email, body.password
    )
    return {
        "token": token,
        "token_type": "bearer",
        "user": {
            "id": principal.user_id,
            "display_name": principal.display_name,
            "email": principal.email,
            "roles": principal.roles,
            "permissions": sorted(
                p.value for p in permissions_for_roles(principal.roles)
            ),
        },
    }


@router.get("/auth/me")
def whoami(caller: Caller) -> dict:
    """Who the token says the caller is, and what they may sign.

    The surface reads this on load so it can name the roles held rather than
    offering an action that will be refused. Also returns the effective
    permission set — a role is just a bag of permissions and the frontend
    prefers to hide/show controls based on capability, not role name.
    """
    from app.services.permissions import permissions_for_roles
    from app.services import scope_service

    perms = permissions_for_roles(caller.roles)
    scope = scope_service.scope_for_user(caller.session, caller.user_id) if hasattr(caller, 'session') else None
    # Session isn't on the Principal; fetch fresh via the request-scoped session.
    from app.db import SessionLocal

    with SessionLocal() as sess:
        scope = scope_service.scope_for_user(sess, caller.user_id)
        entities = scope_service.list_entities(sess, caller.tenant_id)
        if scope.group_wide:
            visible = [
                {"id": e.id, "code": e.code, "name": e.name, "base_currency": e.base_currency}
                for e in entities
            ]
        else:
            eset = set(scope.entity_ids)
            visible = [
                {"id": e.id, "code": e.code, "name": e.name, "base_currency": e.base_currency}
                for e in entities
                if e.id in eset
            ]
    return {
        "id": caller.user_id,
        "display_name": caller.display_name,
        "email": caller.email,
        "roles": caller.roles,
        "permissions": sorted(p.value for p in perms),
        "scope": {
            "group_wide": scope.group_wide,
            "entities": visible,
        },
    }


@router.post("/auth/logout")
def sign_out(caller: Caller) -> dict:
    """Discards the token on the client.

    The token is signed rather than stored, so nothing here can revoke it
    before it expires. That is stated rather than hidden, and it is one of
    the things single sign on fixes properly. Tokens last twelve hours.
    """
    return {
        "ok": True,
        "note": (
            "The token is discarded by the client. It stays valid until it "
            "expires, because nothing here stores sessions."
        ),
    }
