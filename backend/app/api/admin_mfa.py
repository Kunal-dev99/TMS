"""Admin — MFA status + policy.

Three endpoints, MANAGE_USERS-gated:

- GET  /admin/mfa/status            — table of users + enrollment state
- GET  /admin/mfa/policy            — current per-tenant policy
- POST /admin/mfa/policy/request    — request a policy change (four-eye, ADR-0015)

The approve/reject half of the four-eye flow lives in
/admin/access-changes/{id}/approve (and /reject) — the same endpoints
that already handle role-grant approvals. See
access_change_service.approve() for the change_type dispatch; the
'mfa_policy.set' branch calls mfa_policy_service.set_policy().

Reads are gated with MANAGE_USERS only; the queue-the-change endpoint
is also MANAGE_USERS, with the four-eye rule enforcing requester !=
reviewer at approve time.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import Caller, Ctx, require_permission
from app.models import AppUser, UserMfaSecret
from app.services import access_change_service, audit_service
from app.services import mfa_policy_service, mfa_service
from app.services.permissions import Permission


router = APIRouter(prefix="/admin", tags=["Admin MFA"])

_READ_GUARD = Depends(require_permission(Permission.MANAGE_USERS))


# ----- GET /admin/mfa/status -----------------------------------------------


class MfaUserRow(BaseModel):
    user_id: str
    display_name: str
    email: str
    enrolled: bool
    verified_at: str | None = None
    last_used_at: str | None = None


@router.get("/mfa/status", response_model=list[MfaUserRow], dependencies=[_READ_GUARD])
def mfa_status(ctx: Ctx, caller: Caller) -> list[MfaUserRow]:
    """One row per active user in this tenant with their enrollment state."""
    users = ctx.session.scalars(
        select(AppUser)
        .where(AppUser.tenant_id == ctx.tenant_id)
        .where(AppUser.status == "ACTIVE")
        .order_by(AppUser.display_name.asc())
    ).all()

    # Pull every MFA secret row for the tenant in one query, index by user_id.
    user_ids = [u.id for u in users]
    secrets = {
        row.user_id: row
        for row in ctx.session.scalars(
            select(UserMfaSecret).where(UserMfaSecret.user_id.in_(user_ids))
        ).all()
    }

    rows: list[MfaUserRow] = []
    for u in users:
        sec = secrets.get(u.id)
        rows.append(
            MfaUserRow(
                user_id=u.id,
                display_name=u.display_name,
                email=u.email,
                enrolled=sec is not None and sec.verified_at is not None,
                verified_at=sec.verified_at if sec else None,
                last_used_at=sec.last_used_at if sec else None,
            )
        )
    return rows


# ----- GET /admin/mfa/policy -----------------------------------------------


class MfaPolicyView(BaseModel):
    mode: str
    grace_days: int
    activated_at: str | None = None


@router.get("/mfa/policy", response_model=MfaPolicyView, dependencies=[_READ_GUARD])
def get_policy(ctx: Ctx, caller: Caller) -> MfaPolicyView:
    policy = mfa_policy_service.get_policy(ctx.session, ctx.tenant_id)
    return MfaPolicyView(**policy)


# ----- POST /admin/mfa/policy/request --------------------------------------


class MfaPolicyChangeRequest(BaseModel):
    mode: str = Field(
        ..., description="off | optional | required_for_sensitive_roles | required_for_all"
    )
    grace_days: int = Field(7, ge=0, le=90)
    reason: str = Field(
        ..., min_length=10,
        description="Why this change — recorded on the audit event.",
    )


class MfaPolicyChangeQueued(BaseModel):
    request_id: str
    status: str
    requested_by_display: str
    change: MfaPolicyChangeRequest


@router.post(
    "/mfa/policy/request",
    response_model=MfaPolicyChangeQueued,
    dependencies=[Depends(require_permission(Permission.MANAGE_USERS))],
)
def request_policy_change(
    body: MfaPolicyChangeRequest, ctx: Ctx, caller: Caller
) -> MfaPolicyChangeQueued:
    """Queue a policy change for a different admin to approve."""
    try:
        req = access_change_service.create_mfa_policy_change_request(
            ctx.session,
            tenant_id=ctx.tenant_id,
            mode=body.mode,
            grace_days=body.grace_days,
            requester=caller,
            reason=body.reason,
        )
    except ValueError as e:
        # Validation at queue-time, not at approve-time.
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))

    audit_service.record(
        ctx.session,
        tenant_id=ctx.tenant_id,
        actor_user_id=caller.user_id,
        actor_display=caller.display_name,
        action="mfa_policy.change_requested",
        subject_type="mfa_policy",
        subject_id=ctx.tenant_id,
        outcome="PENDING",
        payload={
            "mode": body.mode,
            "grace_days": body.grace_days,
            "reason": body.reason,
            "request_id": req.id,
        },
    )
    ctx.session.commit()
    return MfaPolicyChangeQueued(
        request_id=req.id,
        status=req.status,
        requested_by_display=req.requested_by_display,
        change=body,
    )
