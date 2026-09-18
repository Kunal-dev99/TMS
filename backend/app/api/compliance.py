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

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import Ctx, require_permission
from app.models import (
    AuditEvent,
    CheckRun,
    Counterparty,
    CpLimit,
    Deal,
    ExceptionItem,
    PolicyVersion,
)
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
    action_prefix: str | None = None
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


def _apply_filters(
    stmt,
    ctx: Ctx,
    *,
    actor: str | None,
    action: str | None,
    action_prefix: str | None,
    subject_type: str | None,
    subject_id: str | None,
    date_from: str | None,
    date_to: str | None,
):
    """Apply the compliance filter set to any statement over AuditEvent.

    Kept generic so the SELECT and the COUNT queries share exactly
    the same WHERE clauses — a divergence between them is how you
    ship '4 rows shown, 0 matching' bugs.
    """
    stmt = stmt.where(AuditEvent.tenant_id == ctx.tenant_id)
    if actor:
        # Match either the exact user id or a substring of the display
        # name — a compliance officer usually types a name, not a uuid.
        like = f"%{actor}%"
        stmt = stmt.where(
            (AuditEvent.actor_user_id == actor)
            | (AuditEvent.actor_display.ilike(like))
        )
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if action_prefix:
        stmt = stmt.where(AuditEvent.action.like(f"{action_prefix}%"))
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
    actor: str | None = Query(None, description="Actor user id OR case-insensitive substring of display name"),
    action: str | None = Query(None, description="Filter by exact action code"),
    action_prefix: str | None = Query(None, description="Filter by action code prefix, e.g. 'deal.' or 'access_change.'"),
    subject_type: str | None = Query(None),
    subject_id: str | None = Query(None),
    date_from: str | None = Query(None, description="ISO date/timestamp lower bound"),
    date_to: str | None = Query(None, description="ISO date/timestamp upper bound"),
    limit: int = Query(50, ge=1, le=500, description="Page size"),
    offset: int = Query(0, ge=0, description="Row offset for pagination"),
) -> ActivityView:
    filter_args = dict(
        actor=actor,
        action=action,
        action_prefix=action_prefix,
        subject_type=subject_type,
        subject_id=subject_id,
        date_from=date_from,
        date_to=date_to,
    )
    # COUNT and SELECT share the same WHERE — same helper, same
    # arguments, no subquery. Guarantees the counts agree with the
    # rows the user sees.
    count_stmt = _apply_filters(select(func.count(AuditEvent.id)), ctx, **filter_args)
    total_matching = int(ctx.session.scalar(count_stmt) or 0)
    total_all = int(
        ctx.session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.tenant_id == ctx.tenant_id
            )
        )
        or 0
    )
    select_stmt = _apply_filters(select(AuditEvent), ctx, **filter_args)
    rows = list(
        ctx.session.scalars(
            select_stmt.order_by(AuditEvent.occurred_at.desc())
            .limit(limit)
            .offset(offset)
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
            action_prefix=action_prefix,
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
    action_prefix: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(10000, ge=1, le=100000),
):
    filter_args = dict(
        actor=actor,
        action=action,
        action_prefix=action_prefix,
        subject_type=subject_type,
        subject_id=subject_id,
        date_from=date_from,
        date_to=date_to,
    )
    count_stmt = _apply_filters(select(func.count(AuditEvent.id)), ctx, **filter_args)
    total_matching = int(ctx.session.scalar(count_stmt) or 0)
    select_stmt = _apply_filters(select(AuditEvent), ctx, **filter_args)
    rows = list(
        ctx.session.scalars(
            select_stmt.order_by(AuditEvent.occurred_at.desc()).limit(limit)
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
            f"action_prefix={action_prefix or '-'}; "
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


# ---------------------------------------------------------- deal evidence


class CheckLine(BaseModel):
    key: str
    passed: bool
    detail: str | None = None
    value: dict | None = None


class DealEvidence(BaseModel):
    # deal terms
    deal_id: str
    counterparty_id: str
    counterparty_name: str
    counterparty_rating: str | None
    instrument: str
    currency: str
    principal_pence: int
    rate_bp: int
    tenor_months: int
    trade_date: str
    value_date: str
    maturity_date: str | None
    legal_entity_id: str | None
    status: str
    # who
    proposer_display: str | None
    proposer_user_id: str | None
    approver_display: str | None
    approver_user_id: str | None
    required_approver: str | None
    override_reason: str | None
    # six-check evidence
    check_run_id: str | None
    booking_outcome: str | None
    six_checks: list[CheckLine]
    measured_pence: int | None
    measurement_basis: str | None
    # policy + limit versions in force at booking
    policy_version_id: str | None
    policy_version_effective_from: str | None
    policy_version_note: str
    limit_id: str | None
    limit_amount_pence: int | None
    # history
    events: list[ActivityRow]


@router.get("/deals/{deal_id}/evidence", response_model=DealEvidence)
def deal_evidence(deal_id: str, ctx: Ctx, _: ComplianceGuard) -> DealEvidence:
    """One deal, everything a compliance officer needs to defend the booking.

    Answers "why was this deal allowed?" without the officer having to
    join five tables in their head:
      * the deal terms,
      * proposer + approver identities,
      * the six-check run persisted at booking time,
      * the policy and counterparty-limit versions that engine used,
      * the full audit-event history for this deal.

    Read-only. Any action lives on the operational page.
    """
    deal = ctx.session.get(Deal, deal_id)
    if deal is None or deal.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="deal not found")

    cp = ctx.session.get(Counterparty, deal.counterparty_id)

    # Prefer the BOOKING run; fall back to the most recent one on the deal.
    booking_run = ctx.session.scalar(
        select(CheckRun)
        .where(CheckRun.deal_id == deal_id, CheckRun.purpose == "BOOKING")
        .order_by(CheckRun.created_at.desc())
        .limit(1)
    )
    if booking_run is None:
        booking_run = ctx.session.scalar(
            select(CheckRun)
            .where(CheckRun.deal_id == deal_id)
            .order_by(CheckRun.created_at.desc())
            .limit(1)
        )

    six_checks: list[CheckLine] = []
    if booking_run and booking_run.results_json:
        try:
            for r in json.loads(booking_run.results_json):
                # results_json is the list of CheckOutcome dicts written
                # by the engine. Field names vary slightly between
                # versions; be tolerant.
                six_checks.append(
                    CheckLine(
                        key=str(r.get("key") or r.get("name") or "check"),
                        passed=bool(r.get("passed", r.get("outcome") == "PASS")),
                        detail=r.get("detail") or r.get("message"),
                        value=r.get("value") if isinstance(r.get("value"), dict) else None,
                    )
                )
        except (json.JSONDecodeError, TypeError):
            pass

    # Policy + limit snapshots. If we have a run, use its recorded
    # policy_version_id (accurate 'at booking'); otherwise fall back to
    # the current policy with a note so the caller knows.
    policy_version_id = booking_run.policy_version_id if booking_run else None
    policy_version_effective_from = None
    policy_note = "policy version taken from check_run (in force at booking)"
    if policy_version_id:
        pv = ctx.session.get(PolicyVersion, policy_version_id)
        if pv:
            policy_version_effective_from = pv.effective_from
    else:
        current = ctx.session.scalar(
            select(PolicyVersion)
            .where(PolicyVersion.tenant_id == ctx.tenant_id)
            .order_by(PolicyVersion.effective_from.desc())
            .limit(1)
        )
        if current:
            policy_version_id = current.id
            policy_version_effective_from = current.effective_from
            policy_note = (
                "no check_run found on this deal — showing CURRENT policy, "
                "not the one in force at booking"
            )

    limit_amount_pence = None
    if booking_run and booking_run.limit_id:
        lim = ctx.session.get(CpLimit, booking_run.limit_id)
        if lim:
            limit_amount_pence = lim.amount_pence

    # Actor identities. Approver comes off the deal row; proposer from
    # the audit event we wrote at deal.recorded.
    proposer_evt = ctx.session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == ctx.tenant_id,
            AuditEvent.subject_type == "deal",
            AuditEvent.subject_id == deal_id,
            AuditEvent.action == "deal.recorded",
        )
        .order_by(AuditEvent.occurred_at.asc())
        .limit(1)
    )
    proposer_display = proposer_evt.actor_display if proposer_evt else None
    proposer_user_id = proposer_evt.actor_user_id if proposer_evt else None

    # Full timeline for this deal.
    event_rows = list(
        ctx.session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == ctx.tenant_id,
                AuditEvent.subject_type == "deal",
                AuditEvent.subject_id == deal_id,
            )
            .order_by(AuditEvent.occurred_at.asc())
        )
    )
    events = [
        ActivityRow(
            id=e.id,
            occurred_at=e.occurred_at,
            actor_display=e.actor_display,
            action=e.action,
            action_label=_label(e.action),
            subject_type=e.subject_type,
            subject_id=e.subject_id,
            outcome=e.outcome,
            payload=_parse_payload(e.payload_json),
        )
        for e in event_rows
    ]

    return DealEvidence(
        deal_id=deal.id,
        counterparty_id=deal.counterparty_id,
        counterparty_name=cp.name if cp else deal.counterparty_id,
        counterparty_rating=cp.rating if cp else None,
        instrument=deal.instrument,
        currency=deal.currency,
        principal_pence=deal.principal_pence,
        rate_bp=deal.rate_bp,
        tenor_months=deal.tenor_months,
        trade_date=deal.trade_date,
        value_date=deal.value_date,
        maturity_date=deal.maturity_date,
        legal_entity_id=getattr(deal, "legal_entity_id", None),
        status=deal.status,
        proposer_display=proposer_display,
        proposer_user_id=proposer_user_id,
        approver_display=deal.approved_by,
        approver_user_id=None,
        required_approver=deal.required_approver,
        override_reason=getattr(deal, "override_reason", None),
        check_run_id=booking_run.id if booking_run else None,
        booking_outcome=booking_run.outcome if booking_run else None,
        six_checks=six_checks,
        measured_pence=booking_run.measured_pence if booking_run else None,
        measurement_basis=booking_run.measurement_basis if booking_run else None,
        policy_version_id=policy_version_id,
        policy_version_effective_from=policy_version_effective_from,
        policy_version_note=policy_note,
        limit_id=booking_run.limit_id if booking_run else None,
        limit_amount_pence=limit_amount_pence,
        events=events,
    )


# ---------------------------------------------------------- breaches + overrides


class BreachRow(BaseModel):
    kind: str  # "breach" | "override"
    occurred_at: str
    deal_id: str | None
    counterparty_id: str | None
    counterparty_name: str | None
    rule: str
    reason: str | None
    actor_display: str | None
    authoriser_display: str | None
    status: str  # OPEN | RESOLVED | OVERRIDDEN | REJECTED
    resolution: str | None
    resolution_reason: str | None
    resolved_at: str | None


class BreachRegister(BaseModel):
    items: list[BreachRow]
    total_open: int
    total_overridden_ytd: int
    total_resolved_ytd: int
    generated_at: str


@router.get("/breaches-overrides", response_model=BreachRegister)
def breaches_overrides(
    ctx: Ctx,
    _: ComplianceGuard,
    status: str | None = Query(None, description="OPEN | RESOLVED | OVERRIDDEN | REJECTED"),
    limit: int = Query(200, ge=1, le=2000),
) -> BreachRegister:
    """Every breach and every override, one register.

    Two feeds joined:
      * exception_item — the six-check gate raised a failure.
      * audit_event with outcome=OVERRIDDEN — a signer forced the deal
        through with a written reason.

    Compliance can filter by status; a signer can then jump to the
    operational page from the deal reference.
    """
    exceptions = list(
        ctx.session.scalars(
            select(ExceptionItem).where(ExceptionItem.tenant_id == ctx.tenant_id)
        )
    )
    override_events = list(
        ctx.session.scalars(
            select(AuditEvent).where(
                AuditEvent.tenant_id == ctx.tenant_id,
                AuditEvent.outcome == "OVERRIDDEN",
            )
        )
    )

    rows: list[BreachRow] = []

    # Cache counterparty lookups across both feeds.
    cp_cache: dict[str, Counterparty | None] = {}

    def cp_of(cp_id: str | None) -> Counterparty | None:
        if not cp_id:
            return None
        if cp_id not in cp_cache:
            cp_cache[cp_id] = ctx.session.get(Counterparty, cp_id)
        return cp_cache[cp_id]

    for ex in exceptions:
        cp = cp_of(ex.counterparty_id)
        rows.append(
            BreachRow(
                kind="breach",
                occurred_at=ex.raised_at,
                deal_id=ex.deal_id,
                counterparty_id=ex.counterparty_id,
                counterparty_name=cp.name if cp else None,
                rule=ex.reason_code,
                reason=ex.detail,
                actor_display=None,
                authoriser_display=ex.resolved_by,
                status=ex.status,
                resolution=ex.resolution,
                resolution_reason=ex.resolution_reason,
                resolved_at=ex.resolved_at,
            )
        )

    for ev in override_events:
        payload = _parse_payload(ev.payload_json) or {}
        cp_id = payload.get("counterparty_id")
        cp = cp_of(cp_id) if isinstance(cp_id, str) else None
        failed = payload.get("failed_checks") or []
        rule = ", ".join(failed) if isinstance(failed, list) and failed else "unspecified"
        rows.append(
            BreachRow(
                kind="override",
                occurred_at=ev.occurred_at,
                deal_id=ev.subject_id if ev.subject_type == "deal" else None,
                counterparty_id=cp_id if isinstance(cp_id, str) else None,
                counterparty_name=cp.name if cp else None,
                rule=rule,
                reason=(
                    payload.get("override_reason")
                    if isinstance(payload.get("override_reason"), str)
                    else None
                ),
                actor_display=ev.actor_display,
                authoriser_display=ev.actor_display,
                status="OVERRIDDEN",
                resolution="OVERRIDDEN",
                resolution_reason=None,
                resolved_at=ev.occurred_at,
            )
        )

    rows.sort(key=lambda r: r.occurred_at, reverse=True)

    if status:
        rows = [r for r in rows if r.status == status]

    total_open = sum(1 for r in rows if r.status == "OPEN")
    total_overridden_ytd = sum(1 for r in rows if r.status == "OVERRIDDEN")
    total_resolved_ytd = sum(1 for r in rows if r.status == "RESOLVED")

    return BreachRegister(
        items=rows[:limit],
        total_open=total_open,
        total_overridden_ytd=total_overridden_ytd,
        total_resolved_ytd=total_resolved_ytd,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


# ---------------------------------------------------------- overview strip


class OverviewCounts(BaseModel):
    open_breaches: int
    overrides_ytd: int
    resolved_ytd: int
    events_last_7d: int
    deals_missing_evidence: int
    generated_at: str


@router.get("/overview", response_model=OverviewCounts)
def overview(ctx: Ctx, _: ComplianceGuard) -> OverviewCounts:
    """Compact summary strip for the top of the Compliance page."""
    open_breaches = int(
        ctx.session.scalar(
            select(func.count(ExceptionItem.id)).where(
                ExceptionItem.tenant_id == ctx.tenant_id,
                ExceptionItem.status == "OPEN",
            )
        )
        or 0
    )
    overrides_ytd = int(
        ctx.session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.tenant_id == ctx.tenant_id,
                AuditEvent.outcome == "OVERRIDDEN",
            )
        )
        or 0
    )
    resolved_ytd = int(
        ctx.session.scalar(
            select(func.count(ExceptionItem.id)).where(
                ExceptionItem.tenant_id == ctx.tenant_id,
                ExceptionItem.status == "RESOLVED",
            )
        )
        or 0
    )
    # "Last 7 days" is an ISO string compare; the AuditEvent timestamps
    # are stored as ISO already so lexicographic order works.
    from datetime import timedelta

    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(
        timespec="seconds"
    )
    events_last_7d = int(
        ctx.session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.tenant_id == ctx.tenant_id,
                AuditEvent.occurred_at >= seven_days_ago,
            )
        )
        or 0
    )
    # A deal is "missing evidence" if it has no check_run row. That
    # should be zero on this codebase (every write goes through the
    # engine) so a non-zero value flags a real data-integrity issue.
    deal_ids_with_runs = ctx.session.scalars(
        select(CheckRun.deal_id).where(
            CheckRun.tenant_id == ctx.tenant_id,
            CheckRun.deal_id.is_not(None),
        )
    ).all()
    total_deals = int(
        ctx.session.scalar(
            select(func.count(Deal.id)).where(Deal.tenant_id == ctx.tenant_id)
        )
        or 0
    )
    deals_missing_evidence = max(0, total_deals - len(set(deal_ids_with_runs)))

    return OverviewCounts(
        open_breaches=open_breaches,
        overrides_ytd=overrides_ytd,
        resolved_ytd=resolved_ytd,
        events_last_7d=events_last_7d,
        deals_missing_evidence=deals_missing_evidence,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
