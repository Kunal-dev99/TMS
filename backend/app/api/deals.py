"""Deals. Group 2 of document 2.

Six endpoints in phase one. Amendments, apply and settle belong to this
group and arrive in phase three.

The two that matter are next to each other on purpose. `/deals/check`
persists nothing and runs on every pause in typing. `/deals` re-runs the same
engine as the control and has no field for a client supplied result, so a
stale browser cannot hand it a verdict to trust.

One transaction per write endpoint. The check run, the deal and every queue
item commit together or not at all.
"""

from fastapi import APIRouter, Response

from app.api.deps import Caller, Ctx
from app.errors import ErrorCode, TreasuryError
from app.repo import counterparties as cp_repo
from app.repo import deals as deal_repo
from app.schemas import requests as rq
from app.schemas.models import CheckResult, DealDetail, DealSummary
from app.services.deal_service import DealService
from app.services.state_service import StateService

router = APIRouter(tags=["Deals"])


@router.post("/deals/check", response_model=CheckResult)
def check_deal(body: rq.CheckRequest, ctx: Ctx, caller: Caller) -> CheckResult:
    """Run the six checks. Persists nothing."""
    return _deals(ctx).check(
        body.counterparty_id,
        body.instrument,
        body.principal_pence,
        body.tenor_months,
        body.rate_bp,
    )


@router.post("/deals", status_code=201)
def create_deal(body: rq.CreateDealRequest, ctx: Ctx, caller: Caller) -> dict:
    """Record a deal.

    A blocked deal is a 201 with status BLOCKED, not an error. The record was
    created and the exception was raised, so the control worked.
    """
    service = _deals(ctx)
    booking = service.record(
        counterparty_id=body.counterparty_id,
        instrument=body.instrument,
        principal_pence=body.principal_pence,
        tenor_months=body.tenor_months,
        rate_bp=body.rate_bp,
        proposer=caller,
        override_reason=body.override_reason,
        recommendation_id=body.recommendation_id,
    )
    ctx.session.commit()

    state = _state(ctx)
    return {
        "deal": _summary(state, booking.deal.id).model_dump(),
        "run": booking.result.model_dump(),
        "queue_item_id": booking.queue_item_id,
    }


@router.get("/deals", response_model=list[DealSummary])
def list_deals(
    ctx: Ctx,
    caller: Caller,
    status: str | None = None,
    counterparty_id: str | None = None,
) -> list[DealSummary]:
    deals = _state(ctx).deals()
    if status:
        deals = [d for d in deals if d.status == status]
    if counterparty_id:
        deals = [d for d in deals if d.counterparty_id == counterparty_id]
    return deals


@router.get("/deals/{deal_id}", response_model=DealDetail)
def get_deal(deal_id: str, ctx: Ctx, caller: Caller) -> DealDetail:
    """One click, one panel, one call.

    Assembling this on the client would be a waterfall of six requests and
    six loading states, and the figures could disagree with each other.
    """
    detail = _state(ctx).deal_detail(deal_id)
    if detail is None:
        raise TreasuryError(ErrorCode.DEAL_NOT_FOUND)
    return detail


@router.post("/deals/{deal_id}/approve")
def approve_deal(
    deal_id: str, body: rq.ApproveDealRequest, ctx: Ctx, caller: Caller
) -> dict:
    """Record the signature and put the deal on the book."""
    deal = _deals(ctx).approve(deal_id, caller, body.role)
    ctx.session.commit()
    return {
        "deal_id": deal.id,
        "status": deal.status,
        "approved_by": deal.approved_by,
        "approved_at": deal.approved_at,
        "required_approver": deal.required_approver,
        "approved_role": deal.approved_role,
    }


@router.post("/deals/{deal_id}/instruct")
def instruct_deal(
    deal_id: str, body: rq.InstructDealRequest, ctx: Ctx, caller: Caller
) -> dict:
    """Hand a payment instruction to Oracle. Written to a table, not sent."""
    instruction = _deals(ctx).instruct(deal_id, caller)
    ctx.session.commit()
    return {
        "instruction_id": instruction.id,
        "deal_id": instruction.deal_id,
        "status": instruction.status,
        "amount_pence": instruction.amount_pence,
        "value_date": instruction.value_date,
    }


# -- helpers ---------------------------------------------------------------


def _deals(ctx: Ctx) -> DealService:
    return DealService(ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy)


def _state(ctx: Ctx) -> StateService:
    return StateService(
        ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy, ctx.tenant_name
    )


def _summary(state: StateService, deal_id: str) -> DealSummary:
    deal = deal_repo.get(state.session, deal_id)
    if deal is None or deal.tenant_id != state.tenant_id:
        raise TreasuryError(ErrorCode.DEAL_NOT_FOUND)
    counterparty = cp_repo.get(state.session, deal.counterparty_id)
    measure = state.calculator.measure(deal)
    from app.repo import evidence as evidence_repo

    flagged = evidence_repo.deals_with_breaches(state.session, state.tenant_id)
    return DealSummary(
        id=deal.id,
        counterparty_id=deal.counterparty_id,
        counterparty_name=counterparty.name if counterparty else deal.counterparty_id,
        instrument=deal.instrument,
        principal_pence=deal.principal_pence,
        currency=deal.currency,
        rate_bp=deal.rate_bp,
        tenor_months=deal.tenor_months,
        trade_date=deal.trade_date,
        value_date=deal.value_date,
        maturity_date=deal.maturity_date,
        status=deal.status,
        capture_source=deal.capture_source,
        measured_pence=measure.amount_pence,
        measurement_basis=measure.basis,
        stage=state.stage(deal),
        flag="breach" if deal.id in flagged else None,
        approved_by=deal.approved_by,
        required_approver=deal.required_approver,
    )
