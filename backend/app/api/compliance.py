"""Compliance persona endpoints — read-only view of the audit trail.

Compliance officers, CFOs and admins can look at every mutation
recorded by audit_service. All read; nothing writes. Filters cover
the questions a compliance review actually asks:

  * "What did user X do last month?"                    (actor + date range)
  * "Show me every override on a deal."                 (action filter)
  * "Show me everything that touched counterparty Y."   (subject filter)
  * "Was any admin-user change made outside working hours?" (date range)

CSV export is a peer endpoint so the officer can bring the feed into
their own workpapers without a screen scrape. CSV rows are preceded
by a metadata header (filters, coverage, generated timestamp) so a
downloaded file can never be mistaken for a full audit record when
it was in fact a filtered slice.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import Ctx, require_permission
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
    action_label: str
    subject_type: str
    subject_id: str | None
    outcome: str | None
    payload: dict | None


class FiltersApplied(BaseModel):
    actor: str | None = None
    action: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    limit: int
    offset: int


class ActivityView(BaseModel):
    items: list[ActivityRow]
    page_size: int
    offset: int
    total_matching: int
    total_all: int
    actions_seen: list[str]
    subject_types_seen: list[str]
    filters: FiltersApplied
    generated_at: str


# ---------------------------------------------------------- labels

# Technical action codes come from audit_service; compliance users
# read the labels. Anything not in the map falls back to the raw
# code — a new code showing up unlabelled is a hint to update this
# table, not a bug for the reader.
ACTION_LABELS: dict[str, str] = {
    "user.signed_in": "User signed in",
    "user.invited": "User invited",
    "user.updated": "User details updated",
    "user.scope.updated": "User company scope changed",
    "user.password_reset": "User password reset",
    "user.activation_consumed": "User activated their account",
    "access_change.requested": "Access change requested",
    "access_change.approved": "Access change approved",
    "access_change.rejected": "Access change rejected",
    "deal.recorded": "Deal recorded",
    "deal.approved": "Deal approved",
    "deal.instructed": "Deal instructed to bank",
    "deal.settled": "Deal settled",
    "hedge.initiated": "Hedge initiated",
    "policy.updated": "Policy updated",
    "counterparty.updated": "Counterparty updated",
    "tenant.updated": "Tenant updated",
}


def _label(code: str) -> str:
    return ACTION_LABELS.get(code, code)


# ---------------------------------------------------------- helpers


def _parse_payload(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}


def _filtered_stmt(
    ctx: Ctx,
    *,
    actor: str | None,
    action: str | None,
    subject_type: str | None,
    subject_id: str | None,
    date_from: str | None,
    date_to: str | None,
):
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
    return stmt


# ---------------------------------------------------------- endpoints


@router.get("/activity", response_model=ActivityView)
def activity(
    ctx: Ctx,
    _: ComplianceGuard,
    actor: str | None = Query(None, description="Filter by actor_user_id"),
    action: str | None = Query(None, description="Filter by exact action code"),
    subject_type: str | None = Query(None),
    subject_id: str | None = Query(None),
    date_from: str | None = Query(None, description="ISO date/timestamp lower bound"),
    date_to: str | None = Query(None, description="ISO date/timestamp upper bound"),
    limit: int = Query(50, ge=1, le=500, description="Page size"),
    offset: int = Query(0, ge=0, description="Row offset for pagination"),
) -> ActivityView:
    base = _filtered_stmt(
        ctx,
        actor=actor,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        date_from=date_from,
        date_to=date_to,
    )
    # Real COUNT — the old code returned a single id, not a count.
    # A compliance officer needs to know "how many rows match" to know
    # whether the page they're looking at is the full picture.
    total_matching = int(
        ctx.session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        or 0
    )
    total_all = int(
        ctx.session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.tenant_id == ctx.tenant_id
            )
        )
        or 0
    )
    rows = list(
        ctx.session.scalars(
            base.order_by(AuditEvent.occurred_at.desc()).limit(limit).offset(offset)
        )
    )
    actions_seen = sorted(
        ctx.session.scalars(
            select(AuditEvent.action)
            .where(AuditEvent.tenant_id == ctx.tenant_id)
            .distinct()
        )
    )
    subject_types_seen = sorted(
        ctx.session.scalars(
            select(AuditEvent.subject_type)
            .where(AuditEvent.tenant_id == ctx.tenant_id)
            .distinct()
        )
    )
    return ActivityView(
        items=[
            ActivityRow(
                id=r.id,
                occurred_at=r.occurred_at,
                actor_display=r.actor_display,
                action=r.action,
                action_label=_label(r.action),
                subject_type=r.subject_type,
                subject_id=r.subject_id,
                outcome=r.outcome,
                payload=_parse_payload(r.payload_json),
            )
            for r in rows
        ],
        page_size=limit,
        offset=offset,
        total_matching=total_matching,
        total_all=total_all,
        actions_seen=actions_seen,
        subject_types_seen=subject_types_seen,
        filters=FiltersApplied(
            actor=actor,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        ),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
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
    limit: int = Query(10000, ge=1, le=100000),
):
    base = _filtered_stmt(
        ctx,
        actor=actor,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        date_from=date_from,
        date_to=date_to,
    )
    total_matching = int(
        ctx.session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        or 0
    )
    rows = list(
        ctx.session.scalars(
            base.order_by(AuditEvent.occurred_at.desc()).limit(limit)
        )
    )
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    truncated = total_matching > len(rows)

    buf = io.StringIO()
    writer = csv.writer(buf)
    # Metadata header — comment lines the officer's workpaper can
    # keep alongside the data so a filtered export is never mistaken
    # for a full audit dump.
    writer.writerow([f"# Treasury Register audit export"])
    writer.writerow([f"# generated_at={generated_at}"])
    writer.writerow([f"# tenant_id={ctx.tenant_id}"])
    writer.writerow(
        [
            f"# filters: actor={actor or '-'}; action={action or '-'}; "
            f"subject_type={subject_type or '-'}; subject_id={subject_id or '-'}; "
            f"date_from={date_from or '-'}; date_to={date_to or '-'}"
        ]
    )
    writer.writerow(
        [f"# rows_exported={len(rows)}; rows_matching_filters={total_matching}; "
         f"truncated={'yes' if truncated else 'no'}"]
    )
    writer.writerow([])
    writer.writerow(
        ["occurred_at", "actor", "action", "action_label",
         "subject_type", "subject_id", "outcome", "payload_json"]
    )
    for r in rows:
        writer.writerow(
            [
                r.occurred_at,
                r.actor_display or "",
                r.action,
                _label(r.action),
                r.subject_type,
                r.subject_id or "",
                r.outcome or "",
                r.payload_json or "",
            ]
        )
    stamp = generated_at.replace(":", "").replace("-", "")[:15]
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=audit-activity-{stamp}.csv",
            "X-Rows-Matching": str(total_matching),
            "X-Rows-Exported": str(len(rows)),
        },
    )
