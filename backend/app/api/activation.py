"""Public endpoints for the activation page.

Two endpoints, both unauthenticated (they authenticate via the token
itself). ADR-0014 covers the shape.

  GET  /activate/{token}   — non-consuming lookup; returns whose account
                             this belongs to and the purpose ('INVITE'
                             or 'RESET'). Used by the /activate page to
                             show "Welcome, Jane Doe — set your password".

  POST /activate           — consume the token: set the user's password
                             and mark it used. Returns a bearer token so
                             the browser can sign in immediately.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import Ctx
from app.security import issue_token
from app.services import activation_service
from app.services import rate_limit as rl

router = APIRouter(tags=["Activation"], prefix="/activate")


class ResolveResponse(BaseModel):
    email: str
    display_name: str
    purpose: str
    expires_at: str


class ConsumeRequest(BaseModel):
    token: str
    password: str = Field(..., min_length=8, max_length=200)


class ConsumeResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    user: dict


@router.get(
    "/{raw_token}",
    response_model=ResolveResponse,
    dependencies=[Depends(rl.limit_by_ip(rl.ACTIVATION_RESOLVE))],
)
def resolve(raw_token: str, ctx: Ctx) -> ResolveResponse:
    resolved = activation_service.resolve_token(ctx.session, raw_token)
    return ResolveResponse(
        email=resolved.email,
        display_name=resolved.display_name,
        purpose=resolved.purpose,
        expires_at=resolved.expires_at,
    )


@router.post(
    "",
    response_model=ConsumeResponse,
    dependencies=[Depends(rl.limit_by_ip(rl.ACTIVATION_CONSUME))],
)
def consume(body: ConsumeRequest, ctx: Ctx) -> ConsumeResponse:
    from app.services.permissions import permissions_for_roles
    from app.repo import users as user_repo

    user = activation_service.consume_token(ctx.session, body.token, body.password)
    ctx.session.commit()
    # Issue a bearer token so the invitee is signed in the moment they
    # set their password — no extra sign-in step.
    roles = user_repo.roles(ctx.session, user.id)
    bearer = issue_token(user.id, user.tenant_id)
    return ConsumeResponse(
        token=bearer,
        user={
            "id": user.id,
            "display_name": user.display_name,
            "email": user.email,
            "roles": roles,
            "permissions": sorted(p.value for p in permissions_for_roles(roles)),
        },
    )
