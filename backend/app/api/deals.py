"""Deals. Group 2 of document 2.

Nine endpoints. The six of phase one, and the three the deal lifecycle
added in phase three: raising an amendment, applying it, and settling.

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
from app.services.amendment_service import AmendmentService
from app.services.deal_service import DealService
from app.services.settlement_service import SettlementService
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


@router.post("/deals/{deal_id}/amendments", status_code=201)
def raise_amendment(
    deal_id: str, body: rq.RaiseAmendmentRequest, ctx: Ctx, caller: Caller
) -> dict:
    """Raise an amendment.

    Records what is proposed and returns what applying it would change,
    without changing it. Raising and applying are two calls on purpose: a
    reversal that reaches into a closed period is a conversation with the
    accountants, and it has to be visible before it happens.
    """
    amendment, preview = _amendments(ctx).raise_amendment(
        deal_id=deal_id,
        type=body.type,
        effective_date=body.effective_date,
        reason=body.reason,
        raised_by=caller,
        new_principal_pence=body.new_principal_pence,
        new_rate_bp=body.new_rate_bp,
        new_maturity_date=body.new_maturity_date,
    )
    ctx.session.commit()
    return {
        "amendment_id": amendment.id,
        "preview": {
            "accruals_affected": preview.accruals_affected,
            "amount_to_reverse_pence": preview.amount_to_reverse_pence,
            "periods_affected": preview.periods_affected,
            "any_period_closed": preview.any_period_closed,
        },
    }


@router.post("/amendments/{amendment_id}/apply")
def apply_amendment(
    amendment_id: str,
    ctx: Ctx,
    caller: Caller,
    body: rq.ApplyAmendmentRequest | None = None,
) -> dict:
    """Re-test, then recalculate, reverse, repost and update. One transaction.

    A partial reversal leaves the ledger disagreeing with the deal, which is
    worse than no amendment at all, so nothing commits until all of it has
    worked.

    A refusal is the exception, and deliberately so: the check run and the
    queue item are committed before the error is raised, because they are the
    evidence that the amendment was tested and what it was tested against.
    Nothing was reversed on that path, so there is no half finished write to
    protect.
    """
    service = _amendments(ctx)
    applied = service.apply(
        amendment_id,
        applied_by=caller,
        override_reason=body.override_reason if body else None,
    )

    if applied.refused:
        ctx.session.commit()
        raise TreasuryError(
            ErrorCode.AMENDMENT_FAILS_CHECKS,
            f"The amended terms do not pass the six checks. {applied.refusal_detail}",
        )

    from app.models import Amendment

    amendment = ctx.session.get(Amendment, amendment_id)
    summary = _summary(_state(ctx), amendment.deal_id)
    ctx.session.commit()
    return {
        "reversed_pence": applied.reversed_pence,
        "reposted_pence": applied.reposted_pence,
        "periods_reopened": applied.periods_reopened,
        "deal": summary.model_dump(),
    }


@router.post("/deals/{deal_id}/settle")
def settle_deal(
    deal_id: str, body: rq.SettleDealRequest, ctx: Ctx, caller: Caller
) -> dict:
    """Record the three way match and close.

    Two of three agreeing is not enough. If the record and the confirmation
    agree but the statement differs, the money did not arrive as promised and
    this returns a break rather than closing.
    """
    service = SettlementService(ctx.session, ctx.tenant_id, ctx.as_of_date)
    outcome = service.settle(deal_id, body.statement_line_id, caller)
    ctx.session.commit()
    return {
        "settlement_id": outcome.settlement.id,
        "deal_id": deal_id,
        "match_status": outcome.settlement.match_status,
        "break_detail": outcome.break_detail,
        "closed_at": outcome.settlement.closed_at,
        "expected_pence": (
            outcome.settlement.expected_principal_pence
            + outcome.settlement.expected_interest_pence
        ),
        "confirmed_pence": outcome.settlement.confirmed_amount_pence,
        "statement_pence": outcome.settlement.statement_amount_pence,
    }


def _amendments(ctx: Ctx) -> AmendmentService:
    return AmendmentService(ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy)


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
