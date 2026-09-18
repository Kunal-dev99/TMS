"""Admin — user + role + tenant management.

The persona this endpoint set serves is the security/procurement lens:
"who can sign in, what can they do, and who's currently holding a
session". Every mutation writes an audit_event.

ADMIN-gated. The seed user r.sethi is granted ADMIN in bootstrap so
the demo has someone to sign in with.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.api.deps import Caller, Ctx, require_role
from app.errors import ErrorCode, TreasuryError
from app.ids import new_id, now
from app.models import AppUser, LegalEntity, Membership, Tenant, UserEntityScope
from app.security import hash_password
from app.services import access_change_service, activation_service, audit_service, scope_service
from app.services.permissions import (
    PERMISSION_LABEL,
    ROLE_PERMISSIONS,
    Permission,
    permissions_for_role,
    permissions_for_roles,
    summarise_permissions,
)

router = APIRouter(tags=["Admin"], prefix="/admin")

# One canonical list — the CheckConstraint on Membership enforces this
# server-side; keeping it here means the admin UI shows the same set.
ROLES: list[dict[str, str]] = [
    {"role": "ADMIN", "label": "Administrator", "description": "Manages users, roles, tenant settings."},
    {"role": "COMPLIANCE_OFFICER", "label": "Compliance officer", "description": "Reads the audit trail, override register, policy history."},
    {"role": "CFO", "label": "Chief Financial Officer", "description": "Signs above the second approval threshold."},
    {"role": "HEAD_OF_TREASURY", "label": "Head of Treasury", "description": "Signs up to the second threshold."},
    {"role": "ANALYST", "label": "Analyst", "description": "Proposes deals; signs up to the analyst threshold."},
    {"role": "OPERATOR", "label": "Operator", "description": "Runs the day-to-day; no sign-off authority."},
    {"role": "AUDITOR", "label": "External auditor", "description": "Read-only access to evidence."},
]

VALID_ROLES = {r["role"] for r in ROLES}


# ------------------------------------------------------------- schemas


class EffectiveAccess(BaseModel):
    """Plain-English summary of a user's or role's permissions."""

    held: list[str]
    can: list[str]
    cannot: list[str]


class ScopeView(BaseModel):
    group_wide: bool
    entity_ids: list[str]
    summary: str


class UserRow(BaseModel):
    id: str
    email: str
    display_name: str
    status: str
    roles: list[str]
    created_at: str
    last_signed_in_at: str | None
    invited_by_display: str | None
    invited_at: str | None
    effective_access: EffectiveAccess
    scope: ScopeView
    pending_activation: bool
    #: Sensitive role grants for this user that are awaiting a second
    #: admin's approval (ADR-0015). Empty on the happy path.
    pending_role_grants: list[str]


class LegalEntityView(BaseModel):
    id: str
    code: str
    name: str
    base_currency: str
    country: str | None
    status: str


class ScopePatch(BaseModel):
    """Set the user's scope to exactly these entities.

    Either `group_wide=true` (grant group-wide, revoke everything else),
    or `group_wide=false` with `entity_ids` naming the exact live set.
    """

    group_wide: bool = False
    entity_ids: list[str] = Field(default_factory=list)


class RoleRow(BaseModel):
    role: str
    label: str
    description: str
    permissions: list[str]  # sorted permission values
    can: list[str]  # plain-English list of what this role can do


class InviteRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(..., min_length=1, max_length=120)
    roles: list[str] = Field(default_factory=list)


class InviteResponse(BaseModel):
    user: UserRow
    activation_url: str
    expires_at: str
    note: str = (
        "Share this activation link with the invitee. It expires in 24 "
        "hours and is single-use. Neither you nor Treasury Register "
        "sees their chosen password."
    )


class ResetPasswordResponse(BaseModel):
    user_id: str
    activation_url: str
    expires_at: str


class UpdateUserRequest(BaseModel):
    display_name: str | None = None
    status: str | None = None  # "ACTIVE" or "DISABLED"
    roles: list[str] | None = None  # replaces the set


class TenantView(BaseModel):
    id: str
    name: str
    base_currency: str
    as_of_date: str


# ------------------------------------------------------------- helpers


def _live_roles(session, user_id: str) -> list[str]:
    return sorted(
        session.scalars(
            select(Membership.role)
            .where(Membership.user_id == user_id)
            .where(Membership.revoked_at.is_(None))
        ).all()
    )


def _display_name(session, user_id: str | None) -> str | None:
    if not user_id:
        return None
    user = session.get(AppUser, user_id)
    return user.display_name if user else None


def _row(session, user: AppUser) -> UserRow:
    roles = _live_roles(session, user.id)
    scope = scope_service.scope_for_user(session, user.id)
    entities_by_id = {e.id: e for e in scope_service.list_entities(session, user.tenant_id)}
    return UserRow(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        status=user.status,
        roles=roles,
        created_at=user.created_at,
        last_signed_in_at=user.last_signed_in_at,
        invited_by_display=_display_name(session, user.invited_by_user_id),
        invited_at=user.invited_at,
        effective_access=EffectiveAccess(**summarise_permissions(roles)),
        scope=ScopeView(
            group_wide=scope.group_wide,
            entity_ids=scope.entity_ids,
            summary=scope.summary(entities_by_id),
        ),
        pending_activation=activation_service.has_pending_activation(session, user.id),
        pending_role_grants=sorted(
            __import__("json").loads(req.payload_json).get("role", "")
            for req in access_change_service.pending_for_subject(session, user.id)
            if req.change_type == "role.grant"
        ),
    )


def _generate_temp_password() -> str:
    return secrets.token_urlsafe(9)


def _validate_roles(roles: list[str]) -> None:
    unknown = [r for r in roles if r not in VALID_ROLES]
    if unknown:
        raise TreasuryError(
            ErrorCode.ROLE_NOT_HELD,
            f"Unknown role(s): {', '.join(unknown)}.",
            field="roles",
        )


def _sync_roles(
    session,
    user_id: str,
    target_roles: list[str],
    granter,
) -> list[str]:
    """Set membership rows to exactly `target_roles`, with four-eye
    control on sensitive grants.

    Revocations of any role apply immediately (per ADR-0015 and the
    research). Grants of non-sensitive roles apply immediately.
    Grants of ADMIN / CFO / COMPLIANCE_OFFICER instead create a
    pending AccessChangeRequest that a different admin must approve.

    Returns the list of sensitive role names that were queued, so the
    caller can tell the UI 'this change is pending review'.

    `granter` is the caller Principal (needed to name the requester on
    a pending row); it may also be passed as a plain string for the
    seed loader / immediate paths.
    """
    _validate_roles(target_roles)
    current = _live_roles(session, user_id)
    to_add = [r for r in target_roles if r not in current]
    to_revoke = [r for r in current if r not in target_roles]
    tenant_id = session.scalars(
        select(AppUser.tenant_id).where(AppUser.id == user_id)
    ).one()

    # Revocations always apply immediately.
    for role in to_revoke:
        row = session.scalars(
            select(Membership)
            .where(Membership.user_id == user_id)
            .where(Membership.role == role)
            .where(Membership.revoked_at.is_(None))
        ).one_or_none()
        if row is not None:
            row.revoked_at = now()

    queued: list[str] = []
    granter_display = (
        granter.display_name if hasattr(granter, "display_name") else str(granter)
    )
    for role in to_add:
        if access_change_service.is_sensitive(role) and hasattr(granter, "user_id"):
            access_change_service.create_role_grant_request(
                session,
                tenant_id=tenant_id,
                subject_user_id=user_id,
                role=role,
                requester=granter,
            )
            queued.append(role)
            continue
        # Non-sensitive grant (or seed path where granter is a string).
        session.add(
            Membership(
                id=new_id("mem"),
                tenant_id=tenant_id,
                user_id=user_id,
                role=role,
                granted_by=granter_display,
                granted_at=now(),
            )
        )
    session.flush()
    return queued


# ---------------------------------------------------------- endpoints


AdminGuard = Annotated[object, Depends(require_role("ADMIN"))]


@router.get("/users", response_model=list[UserRow])
def list_users(ctx: Ctx, _: AdminGuard) -> list[UserRow]:
    users = ctx.session.scalars(
        select(AppUser).where(AppUser.tenant_id == ctx.tenant_id).order_by(AppUser.email)
    ).all()
    return [_row(ctx.session, u) for u in users]


@router.post("/users", response_model=InviteResponse, status_code=201)
def invite_user(
    body: InviteRequest, ctx: Ctx, caller: Caller, _: AdminGuard
) -> InviteResponse:
    _validate_roles(body.roles)
    # Enforce uniqueness (also enforced by DB).
    existing = ctx.session.scalars(
        select(AppUser)
        .where(AppUser.tenant_id == ctx.tenant_id)
        .where(AppUser.email == str(body.email).lower())
    ).one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="A user with that email already exists in this tenant.",
        )
    # Sentinel password_hash — the user can hold roles + scope but
    # cannot sign in until they consume the activation token below.
    user = AppUser(
        id=new_id("usr"),
        tenant_id=ctx.tenant_id,
        email=str(body.email).lower(),
        display_name=body.display_name.strip(),
        password_hash=activation_service.UNUSABLE_PASSWORD_HASH,
        status="ACTIVE",
        created_at=now(),
        invited_by_user_id=caller.user_id,
        invited_at=now(),
    )
    ctx.session.add(user)
    ctx.session.flush()
    # Non-sensitive roles apply immediately; sensitive ones queue for
    # a second admin (ADR-0015). The invitee activates as a low-
    # privilege user; once the second admin approves, they gain the
    # sensitive roles on their next sign-in.
    queued = _sync_roles(ctx.session, user.id, body.roles, caller)
    token = activation_service.issue_token(
        ctx.session,
        tenant_id=ctx.tenant_id,
        user_id=user.id,
        purpose="INVITE",
        created_by=str(caller),
    )
    audit_service.record(
        ctx.session,
        tenant_id=ctx.tenant_id,
        actor_user_id=caller.user_id,
        actor_display=caller.display_name,
        action="user.invited",
        subject_type="user",
        subject_id=user.id,
        outcome="PENDING_ACTIVATION",
        payload={"email": user.email, "roles": body.roles, "expires_at": token.expires_at},
    )
    ctx.session.commit()
    print(f"[admin] invited {user.email} — activation link: {token.activation_url}")
    return InviteResponse(
        user=_row(ctx.session, user),
        activation_url=token.activation_url,
        expires_at=token.expires_at,
    )


@router.patch("/users/{user_id}", response_model=UserRow)
def update_user(
    user_id: str, body: UpdateUserRequest, ctx: Ctx, caller: Caller, _: AdminGuard
) -> UserRow:
    user = ctx.session.get(AppUser, user_id)
    if user is None or user.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="User not found.")

    changed: dict[str, object] = {}
    if body.display_name is not None and body.display_name.strip() != user.display_name:
        changed["display_name"] = body.display_name.strip()
        user.display_name = body.display_name.strip()
    if body.status is not None and body.status != user.status:
        if body.status not in ("ACTIVE", "DISABLED"):
            raise HTTPException(status_code=400, detail="status must be ACTIVE or DISABLED.")
        changed["status"] = body.status
        user.status = body.status
        user.disabled_at = now() if body.status == "DISABLED" else None
    ctx.session.flush()
    queued: list[str] = []
    if body.roles is not None:
        queued = _sync_roles(ctx.session, user.id, body.roles, caller)
        # Note the queued (sensitive) grants separately so the audit
        # trail is honest — 'we asked to grant CFO but it's pending review'.
        applied = [r for r in body.roles if r not in queued]
        changed["roles_applied"] = sorted(applied)
        if queued:
            changed["roles_pending_review"] = sorted(queued)

    if changed:
        audit_service.record(
            ctx.session,
            tenant_id=ctx.tenant_id,
            actor_user_id=caller.user_id,
            actor_display=caller.display_name,
            action="user.updated",
            subject_type="user",
            subject_id=user.id,
            outcome=user.status,
            payload=changed,
        )
    ctx.session.commit()
    return _row(ctx.session, user)


@router.post("/users/{user_id}/reset-password", response_model=ResetPasswordResponse)
def reset_password(
    user_id: str, ctx: Ctx, caller: Caller, _: AdminGuard
) -> ResetPasswordResponse:
    user = ctx.session.get(AppUser, user_id)
    if user is None or user.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="User not found.")
    # Break the existing password immediately so the previous credentials
    # stop working the second the admin clicks Reset. The user must
    # consume the activation link to sign in again.
    user.password_hash = activation_service.UNUSABLE_PASSWORD_HASH
    token = activation_service.issue_token(
        ctx.session,
        tenant_id=ctx.tenant_id,
        user_id=user.id,
        purpose="RESET",
        created_by=str(caller),
    )
    audit_service.record(
        ctx.session,
        tenant_id=ctx.tenant_id,
        actor_user_id=caller.user_id,
        actor_display=caller.display_name,
        action="user.password.reset",
        subject_type="user",
        subject_id=user.id,
        payload={"expires_at": token.expires_at},
    )
    ctx.session.commit()
    print(f"[admin] reset password for {user.email} — activation link: {token.activation_url}")
    return ResetPasswordResponse(
        user_id=user.id,
        activation_url=token.activation_url,
        expires_at=token.expires_at,
    )


@router.get("/roles", response_model=list[RoleRow])
def list_roles(ctx: Ctx, _: AdminGuard) -> list[RoleRow]:
    rows: list[RoleRow] = []
    for meta in ROLES:
        perms = permissions_for_role(meta["role"])
        rows.append(
            RoleRow(
                role=meta["role"],
                label=meta["label"],
                description=meta["description"],
                permissions=sorted(p.value for p in perms),
                can=sorted(PERMISSION_LABEL[p] for p in perms),
            )
        )
    return rows


@router.get("/legal-entities", response_model=list[LegalEntityView])
def list_legal_entities(ctx: Ctx, _: AdminGuard) -> list[LegalEntityView]:
    """The customer's own corporate subsidiaries (not counterparties)."""
    return [
        LegalEntityView(
            id=e.id,
            code=e.code,
            name=e.name,
            base_currency=e.base_currency,
            country=e.country,
            status=e.status,
        )
        for e in scope_service.list_entities(ctx.session, ctx.tenant_id)
    ]


@router.patch("/users/{user_id}/scope", response_model=UserRow)
def update_user_scope(
    user_id: str, body: ScopePatch, ctx: Ctx, caller: Caller, _: AdminGuard
) -> UserRow:
    """Replace the user's live scope. Revokes anything not in the target
    (rows kept with revoked_at set — evidence trail is preserved).
    """
    user = ctx.session.get(AppUser, user_id)
    if user is None or user.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="User not found.")
    if body.group_wide and body.entity_ids:
        raise HTTPException(
            status_code=400,
            detail="Group-wide scope cannot be combined with explicit entity_ids.",
        )
    # Validate every named entity belongs to this tenant.
    if body.entity_ids:
        entities = {e.id for e in scope_service.list_entities(ctx.session, ctx.tenant_id)}
        unknown = [e for e in body.entity_ids if e not in entities]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown legal_entity_id(s): {', '.join(unknown)}",
            )
    target = scope_service.UserScope(
        group_wide=body.group_wide, entity_ids=sorted(set(body.entity_ids))
    )
    result = scope_service.replace_scope(
        ctx.session, ctx.tenant_id, user.id, target, str(caller)
    )
    audit_service.record(
        ctx.session,
        tenant_id=ctx.tenant_id,
        actor_user_id=caller.user_id,
        actor_display=caller.display_name,
        action="user.scope.updated",
        subject_type="user",
        subject_id=user.id,
        payload={
            "group_wide": result.group_wide,
            "entity_ids": result.entity_ids,
        },
    )
    ctx.session.commit()
    return _row(ctx.session, user)


class AccessChangeView(BaseModel):
    id: str
    subject_type: str
    subject_id: str
    subject_display: str
    change_type: str
    payload: dict
    status: str
    requested_by_display: str
    requested_at: str
    reviewed_by_display: str | None
    reviewed_at: str | None
    review_reason: str | None


class ReviewRequest(BaseModel):
    reason: str | None = None


@router.get("/access-changes", response_model=list[AccessChangeView])
def list_access_changes(ctx: Ctx, _: AdminGuard) -> list[AccessChangeView]:
    """Pending sensitive-access requests awaiting a second admin.

    Approvals of your own requests are refused server-side (requester
    != reviewer). The UI hides the buttons on your own rows too.
    """
    rows = access_change_service.list_pending(ctx.session, ctx.tenant_id)
    return [
        AccessChangeView(**access_change_service.summarise(ctx.session, r).__dict__)
        for r in rows
    ]


@router.post("/access-changes/{request_id}/approve", response_model=UserRow)
def approve_access_change(
    request_id: str, body: ReviewRequest, ctx: Ctx, caller: Caller, _: AdminGuard
) -> UserRow:
    req = access_change_service.approve(
        ctx.session,
        tenant_id=ctx.tenant_id,
        request_id=request_id,
        reviewer=caller,
        reason=body.reason,
    )
    audit_service.record(
        ctx.session,
        tenant_id=ctx.tenant_id,
        actor_user_id=caller.user_id,
        actor_display=caller.display_name,
        action="access_change.approved",
        subject_type=req.subject_type,
        subject_id=req.subject_id,
        outcome="APPROVED",
        payload={
            "change_type": req.change_type,
            "payload": __import__("json").loads(req.payload_json),
            "requested_by": req.requested_by_display,
        },
    )
    ctx.session.commit()
    subject = ctx.session.get(AppUser, req.subject_id)
    return _row(ctx.session, subject)


@router.post("/access-changes/{request_id}/reject", response_model=AccessChangeView)
def reject_access_change(
    request_id: str, body: ReviewRequest, ctx: Ctx, caller: Caller, _: AdminGuard
) -> AccessChangeView:
    req = access_change_service.reject(
        ctx.session,
        tenant_id=ctx.tenant_id,
        request_id=request_id,
        reviewer=caller,
        reason=body.reason or "",
    )
    audit_service.record(
        ctx.session,
        tenant_id=ctx.tenant_id,
        actor_user_id=caller.user_id,
        actor_display=caller.display_name,
        action="access_change.rejected",
        subject_type=req.subject_type,
        subject_id=req.subject_id,
        outcome="REJECTED",
        payload={
            "change_type": req.change_type,
            "payload": __import__("json").loads(req.payload_json),
            "requested_by": req.requested_by_display,
            "review_reason": req.review_reason,
        },
    )
    ctx.session.commit()
    return AccessChangeView(**access_change_service.summarise(ctx.session, req).__dict__)


@router.get("/tenant", response_model=TenantView)
def get_tenant(ctx: Ctx, _: AdminGuard) -> TenantView:
    tenant = ctx.session.get(Tenant, ctx.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant missing.")
    # base_currency isn't a column today; hardcoded until the tenant model
    # grows one. Present it here so the admin UI can render a row.
    return TenantView(
        id=tenant.id,
        name=tenant.name,
        base_currency="GBP",
        as_of_date=ctx.as_of_date,
    )
