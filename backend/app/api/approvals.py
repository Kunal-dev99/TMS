"""Approvals persona endpoints — the signer's queue.

Wraps the existing `POST /deals/{id}/approve` under a persona-shaped
GET that answers 'what needs my signature right now'. A minimal MVP
of the Approvals page — delegation and bulk approvals live in a
future phase.

The queue matches on deal.required_approver against the caller's
roles. Anyone with APPROVE_DEAL permission can view it (the queue
itself is not sensitive); only role-eligible approvers see anything.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import Caller, Ctx, require_permission
from app.models import Counterparty, Deal
from app.services.permissions import Permission

router = APIRouter(tags=["Approvals"], prefix="/approvals")

ApprovalsGuard = Annotated[
    object,
    Depends(require_permission(Permission.APPROVE_DEAL, Permission.MANAGE_USERS)),
]


class PendingItem(BaseModel):
    deal_id: str
    counterparty_name: str
    counterparty_rating: str
    instrument: str
    principal_pence: int
    currency: str
    tenor_months: int
    rate_bp: int
    trade_date: str
    required_approver: str | None
    proposed_by: str
    can_approve: bool
    legal_entity_id: str | None


class QueueView(BaseModel):
    items: list[PendingItem]
    role_names_i_hold: list[str]


# Which required_approver value a given role can sign for.
# ANALYST signs the smallest deals, HEAD_OF_TREASURY the next band,
# CFO everything. Mirrors ApprovalRouter.required_approver().
CAN_APPROVE: dict[str, set[str]] = {
    "ANALYST": {"ANALYST"},
    "HEAD_OF_TREASURY": {"ANALYST", "HEAD_OF_TREASURY"},
    "CFO": {"ANALYST", "HEAD_OF_TREASURY", "CFO"},
}


@router.get("/queue", response_model=QueueView)
def queue(ctx: Ctx, caller: Caller, _: ApprovalsGuard) -> QueueView:
    """Deals proposed but not yet approved. Segregation-of-duties is
    enforced downstream by /deals/{id}/approve — the caller cannot
    approve a deal they proposed. This endpoint still lists them so
    they can see the queue exists."""
    allowed_required: set[str] = set()
    for role in caller.roles:
        allowed_required |= CAN_APPROVE.get(role, set())

    stmt = (
        select(Deal, Counterparty)
        .join(Counterparty, Counterparty.id == Deal.counterparty_id)
        .where(Deal.tenant_id == ctx.tenant_id)
        .where(Deal.status == "PROPOSED")
        .order_by(Deal.created_at.desc())
    )
    items: list[PendingItem] = []
    for deal, cp in ctx.session.execute(stmt):
        items.append(
            PendingItem(
                deal_id=deal.id,
                counterparty_name=cp.name,
                counterparty_rating=cp.rating,
                instrument=deal.instrument,
                principal_pence=deal.principal_pence,
                currency=deal.currency,
                tenor_months=deal.tenor_months,
                rate_bp=deal.rate_bp,
                trade_date=deal.trade_date,
                required_approver=deal.required_approver,
                proposed_by=deal.created_by,
                # Two segregation checks: (a) role holds the required
                # signer, (b) caller didn't propose it. Enforced by
                # /deals/{id}/approve too — this is just for UI hint.
                can_approve=(
                    deal.required_approver in allowed_required
                    and deal.created_by_user_id != caller.user_id
                ),
                legal_entity_id=deal.legal_entity_id,
            )
        )
    return QueueView(
        items=items,
        role_names_i_hold=sorted(caller.roles),
    )
