"""Compliance persona endpoints — read-only view of the audit trail.

Compliance officers, CFOs and admins can look at every mutation
recorded by audit_service. All read; nothing writes. Filters cover
the questions a compliance review actually asks:

  * "What did user X do last month?"                    (actor + date range)
  * "Show me every override on a deal."                 (action filter)
  * "Show me everything that touched counterparty Y."   (subject filter)
  * "Was any admin-user change made outside working hours?" (date range)

CSV export is a peer endpoint so the officer can bring the feed into
their own workpapers without a screen scrape.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import Caller, Ctx, require_permission
from app.models import AuditEvent
from app.services.permissions import Permission

router = APIRouter(tags=["Compliance"], prefix="/compliance")

# ---------------------------------------------------------- gate

ComplianceGuard = Annotated[
    object,
    Depends(
        require_permission(
            Permission.VIEW_AUDIT,
            Permission.MANAGE_USERS,  # admins can also read
        )
    ),
]


# ---------------------------------------------------------- shapes


class ActivityRow(BaseModel):
    id: str
    occurred_at: str
    actor_display: str | None
    action: str
    subject_type: str
    subject_id: str | None
    outcome: str | None
    payload: dict | None


class ActivityView(BaseModel):
    items: list[ActivityRow]
    total: int
    actions_seen: list[str]
    subject_types_seen: list[str]


# ---------------------------------------------------------- helpers


def _parse_payload(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}


def _query(ctx: Ctx, *, actor: str | None, action: str | None,
           subject_type: str | None, subject_id: str | None,
           date_from: str | None, date_to: str | None):
    stmt = select(AuditEvent).where(AuditEvent.tenant_id == ctx.tenant_id)
    if actor:
        stmt = stmt.where(AuditEvent.actor_user_id == actor)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if subject_type:
        stmt = stmt.where(AuditEvent.subject_type == subject_type)
    if subject_id:
        stmt = stmt.where(AuditEvent.subject_id == subject_id)
    if date_from:
        stmt = stmt.where(AuditEvent.occurred_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditEvent.occurred_at <= date_to)
    return stmt.order_by(AuditEvent.occurred_at.desc())


# ---------------------------------------------------------- endpoints


@router.get("/activity", response_model=ActivityView)
def activity(
    ctx: Ctx,
    _: ComplianceGuard,
    actor: str | None = Query(None, description="Filter by actor_user_id"),
    action: str | None = Query(None, description="Filter by exact action string"),
    subject_type: str | None = Query(None),
    subject_id: str | None = Query(None),
    date_from: str | None = Query(None, description="ISO date/timestamp lower bound"),
    date_to: str | None = Query(None, description="ISO date/timestamp upper bound"),
    limit: int = Query(200, ge=1, le=2000),
) -> ActivityView:
    stmt = _query(
        ctx,
        actor=actor, action=action,
        subject_type=subject_type, subject_id=subject_id,
        date_from=date_from, date_to=date_to,
    )
    rows = list(ctx.session.scalars(stmt.limit(limit)))
    total = ctx.session.scalar(
        select(AuditEvent.id).where(AuditEvent.tenant_id == ctx.tenant_id).order_by(None)
    )
    # Cheap distinct-values queries so the filter selects have content.
    actions_seen = sorted(
        ctx.session.scalars(
            select(AuditEvent.action).where(AuditEvent.tenant_id == ctx.tenant_id).distinct()
        )
    )
    subject_types_seen = sorted(
        ctx.session.scalars(
            select(AuditEvent.subject_type).where(AuditEvent.tenant_id == ctx.tenant_id).distinct()
        )
    )
    return ActivityView(
        items=[
            ActivityRow(
                id=r.id,
                occurred_at=r.occurred_at,
                actor_display=r.actor_display,
                action=r.action,
                subject_type=r.subject_type,
                subject_id=r.subject_id,
                outcome=r.outcome,
                payload=_parse_payload(r.payload_json),
            )
            for r in rows
        ],
        total=len(rows),
        actions_seen=actions_seen,
        subject_types_seen=subject_types_seen,
    )


@router.get("/activity.csv")
def activity_csv(
    ctx: Ctx,
    _: ComplianceGuard,
    actor: str | None = None,
    action: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 10000,
):
    stmt = _query(
        ctx,
        actor=actor, action=action,
        subject_type=subject_type, subject_id=subject_id,
        date_from=date_from, date_to=date_to,
    ).limit(limit)
    rows = list(ctx.session.scalars(stmt))
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["occurred_at", "actor", "action", "subject_type", "subject_id", "outcome", "payload_json"]
    )
    for r in rows:
        writer.writerow(
            [r.occurred_at, r.actor_display or "", r.action, r.subject_type,
             r.subject_id or "", r.outcome or "", r.payload_json or ""]
        )
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit-activity.csv"},
    )
