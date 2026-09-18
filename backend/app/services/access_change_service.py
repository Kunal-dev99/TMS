"""Four-eye control on sensitive access grants.

Enterprise treasury tools (Treasury Systems' 'four-eye control',
Nomentia's approval workflow) require an independent approval when a
user gains sensitive authority. Removals still apply immediately —
that's the pattern the research cited. This module holds the queue.

Sensitive grants today: ADMIN, CFO, COMPLIANCE_OFFICER. Everything
else applies immediately.

The rule the reviewer must NOT be able to break: requester != reviewer.
Enforced here rather than in the endpoint so nothing bypasses it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ErrorCode, TreasuryError
from app.ids import new_id, now
from app.models import AccessChangeRequest, AppUser, Membership

SENSITIVE_ROLES = {"ADMIN", "CFO", "COMPLIANCE_OFFICER"}


@dataclass
class RequestSummary:
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


def is_sensitive(role: str) -> bool:
    return role in SENSITIVE_ROLES


def create_role_grant_request(
    session: Session,
    *,
    tenant_id: str,
    subject_user_id: str,
    role: str,
    requester,
    reason: str | None = None,
) -> AccessChangeRequest:
    """Queue a sensitive role grant for another admin to approve."""
    if role not in SENSITIVE_ROLES:
        raise ValueError(f"{role} is not a sensitive role — apply immediately.")
    req = AccessChangeRequest(
        id=new_id("acr"),
        tenant_id=tenant_id,
        subject_type="user",
        subject_id=subject_user_id,
        change_type="role.grant",
        payload_json=json.dumps({"role": role}),
        reason=reason,
        status="PENDING",
        requested_by_user_id=requester.user_id,
        requested_by_display=requester.display_name,
        requested_at=now(),
    )
    session.add(req)
    session.flush()
    return req


def pending_for_subject(session: Session, subject_user_id: str) -> list[AccessChangeRequest]:
    return list(
        session.scalars(
            select(AccessChangeRequest)
            .where(AccessChangeRequest.subject_id == subject_user_id)
            .where(AccessChangeRequest.status == "PENDING")
        )
    )


def list_pending(session: Session, tenant_id: str) -> list[AccessChangeRequest]:
    return list(
        session.scalars(
            select(AccessChangeRequest)
            .where(AccessChangeRequest.tenant_id == tenant_id)
            .where(AccessChangeRequest.status == "PENDING")
            .order_by(AccessChangeRequest.requested_at.desc())
        )
    )


def summarise(session: Session, req: AccessChangeRequest) -> RequestSummary:
    subject = session.get(AppUser, req.subject_id)
    subject_display = subject.email if subject else req.subject_id
    return RequestSummary(
        id=req.id,
        subject_type=req.subject_type,
        subject_id=req.subject_id,
        subject_display=subject_display,
        change_type=req.change_type,
        payload=json.loads(req.payload_json),
        status=req.status,
        requested_by_display=req.requested_by_display,
        requested_at=req.requested_at,
        reviewed_by_display=req.reviewed_by_display,
        reviewed_at=req.reviewed_at,
        review_reason=req.review_reason,
    )


def approve(
    session: Session,
    *,
    tenant_id: str,
    request_id: str,
    reviewer,
    reason: str | None = None,
) -> AccessChangeRequest:
    """Approve a pending request and apply the change.

    Enforces requester != reviewer. Applies the grant by inserting a
    Membership row. On approval, marks the request APPROVED and stamps
    the reviewer.
    """
    req = session.get(AccessChangeRequest, request_id)
    if req is None or req.tenant_id != tenant_id:
        raise TreasuryError(
            ErrorCode.QUEUE_ITEM_NOT_FOUND, "That access change request does not exist."
        )
    if req.status != "PENDING":
        raise TreasuryError(
            ErrorCode.QUEUE_ITEM_ALREADY_RESOLVED,
            f"That request has already been {req.status.lower()}.",
        )
    if req.requested_by_user_id == reviewer.user_id:
        raise TreasuryError(
            ErrorCode.SEGREGATION_OF_DUTIES,
            "You cannot approve an access change you requested. A different admin must review.",
        )

    # Apply the change. change_type is a discriminant — today only
    # role.grant is supported. New types can be added without touching
    # the endpoint layer.
    if req.change_type == "role.grant":
        payload = json.loads(req.payload_json)
        role = payload["role"]
        # Skip if the grant already applies (idempotent — someone else
        # may have granted the same role in parallel).
        live = session.scalars(
            select(Membership)
            .where(Membership.user_id == req.subject_id)
            .where(Membership.role == role)
            .where(Membership.revoked_at.is_(None))
        ).first()
        if live is None:
            session.add(
                Membership(
                    id=new_id("mem"),
                    tenant_id=tenant_id,
                    user_id=req.subject_id,
                    role=role,
                    granted_by=reviewer.display_name,
                    granted_at=now(),
                )
            )
    else:
        raise TreasuryError(
            ErrorCode.QUEUE_ITEM_NOT_FOUND,
            f"Unknown change_type: {req.change_type}",
        )

    req.status = "APPROVED"
    req.reviewed_by_user_id = reviewer.user_id
    req.reviewed_by_display = reviewer.display_name
    req.reviewed_at = now()
    req.review_reason = reason
    session.flush()
    return req


def reject(
    session: Session,
    *,
    tenant_id: str,
    request_id: str,
    reviewer,
    reason: str,
) -> AccessChangeRequest:
    """Reject a pending request. A reason is required."""
    if not reason or not reason.strip():
        raise TreasuryError(
            ErrorCode.REJECTION_REASON_REQUIRED,
            "A reason is required to reject an access change.",
            field="reason",
        )
    req = session.get(AccessChangeRequest, request_id)
    if req is None or req.tenant_id != tenant_id:
        raise TreasuryError(
            ErrorCode.QUEUE_ITEM_NOT_FOUND, "That access change request does not exist."
        )
    if req.status != "PENDING":
        raise TreasuryError(
            ErrorCode.QUEUE_ITEM_ALREADY_RESOLVED,
            f"That request has already been {req.status.lower()}.",
        )
    if req.requested_by_user_id == reviewer.user_id:
        raise TreasuryError(
            ErrorCode.SEGREGATION_OF_DUTIES,
            "You cannot reject an access change you requested. A different admin must review.",
        )
    req.status = "REJECTED"
    req.reviewed_by_user_id = reviewer.user_id
    req.reviewed_by_display = reviewer.display_name
    req.reviewed_at = now()
    req.review_reason = reason.strip()
    session.flush()
    return req
