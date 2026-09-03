"""State and policy. Group 1 of document 2.

A router validates, calls exactly one service and returns. Anything longer
than about ten lines here belongs in a service, and a router that decides
something is a defect.

Four endpoints. The investment policy pair arrived with the advisory layer
in phase two, and the GET returning 404 is a real state rather than an
error: without a buffer, a ladder and cover targets there is nothing to
measure a gap against.
"""

from fastapi import APIRouter

from app.api.deps import Caller, Ctx
from app.errors import ErrorCode, TreasuryError
from app.ids import new_id, now
from app.models import CurrencyCoverTarget, InvestmentPolicy, LadderTarget
from app.schemas import requests as rq
from app.schemas.models import PolicyConfig, StateResponse
from app.services.advisory_service import AdvisoryService
from app.services.state_service import StateService

router = APIRouter(tags=["State and policy"])


@router.get("/state", response_model=StateResponse)
def get_state(ctx: Ctx, caller: Caller) -> StateResponse:
    """Everything the surface needs, in one call."""
    return _service(ctx).state()


@router.get("/policy", response_model=PolicyConfig)
def get_policy(ctx: Ctx, caller: Caller) -> PolicyConfig:
    return _service(ctx).policy_config()


@router.get("/investment-policy")
def get_investment_policy(ctx: Ctx, caller: Caller) -> dict:
    """404 when none has been set.

    That is a real state, and the advisory layer refuses to run in it. The
    refusal is also the conversation that shapes the customer policy.
    """
    service = AdvisoryService(ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy)
    investment = service.investment_policy()
    if investment is None:
        raise TreasuryError(ErrorCode.NO_INVESTMENT_POLICY)

    return {
        "id": investment.id,
        "effective_from": investment.effective_from,
        "liquidity_buffer_pence": investment.liquidity_buffer_pence,
        "buffer_horizon_days": investment.buffer_horizon_days,
        "priority_order": investment.priority_order,
        "model_enabled": bool(investment.model_enabled),
        "approved_by": investment.approved_by,
        "ladder_targets": [
            {
                "bucket": target.bucket,
                "target_share_bp": target.target_share_bp,
                "minimum_pence": target.minimum_pence,
            }
            for target in service.ladder_targets(investment.id)
        ],
    }


@router.post("/investment-policy", status_code=201)
def set_investment_policy(
    body: rq.InvestmentPolicyRequest, ctx: Ctx, caller: Caller
) -> dict:
    """Write a new version. Supersedes the current one, never edits it.

    Refused without an approver, for the same reason a counterparty limit is:
    a policy nobody signed is not a policy.
    """
    if not body.approved_by or not body.approved_by.strip():
        raise TreasuryError(ErrorCode.APPROVER_REQUIRED, field="approved_by")

    service = AdvisoryService(ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy)
    timestamp = now()
    current = service.investment_policy()
    if current is not None:
        current.superseded_at = timestamp

    policy = InvestmentPolicy(
        id=new_id("inv"),
        tenant_id=ctx.tenant_id,
        effective_from=ctx.as_of_date,
        superseded_at=None,
        liquidity_buffer_pence=body.liquidity_buffer_pence,
        buffer_horizon_days=body.buffer_horizon_days,
        priority_order=body.priority_order,
        model_enabled=1 if body.model_enabled else 0,
        approved_by=body.approved_by,
        recorded_by_user_id=caller.user_id,
    )
    ctx.session.add(policy)
    ctx.session.flush()

    for target in body.ladder_targets:
        ctx.session.add(
            LadderTarget(
                policy_id=policy.id,
                bucket=target["bucket"],
                target_share_bp=target["target_share_bp"],
                minimum_pence=target.get("minimum_pence", 0),
            )
        )
    for target in body.currency_cover_targets:
        ctx.session.add(
            CurrencyCoverTarget(
                policy_id=policy.id,
                currency=target["currency"],
                target_cover_bp=target["target_cover_bp"],
                horizon_days=target["horizon_days"],
            )
        )
    ctx.session.commit()
    return {"id": policy.id, "effective_from": policy.effective_from}


def _service(ctx: Ctx) -> StateService:
    return StateService(
        ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy, ctx.tenant_name
    )
