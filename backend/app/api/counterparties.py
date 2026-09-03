"""Counterparties. Group 5 of document 2.

Four onboarding calls, one per step a person performs, each separately
refusable. Then the limit history, and the rating action.

The rating endpoint is one call in and an unknown number of breaches out.
Nobody inside the organisation triggers it; it is the world moving.
"""

from fastapi import APIRouter

from app.api.deps import Caller, Ctx
from app.schemas import requests as rq
from app.schemas.models import LimitVersion
from app.services.onboarding_service import OnboardingService
from app.services.retest_service import RetestService
from app.services.state_service import StateService

router = APIRouter(tags=["Counterparties"])


@router.post("/counterparties", status_code=201)
def create_counterparty(
    body: rq.CreateCounterpartyRequest, ctx: Ctx, caller: Caller
) -> dict:
    counterparty = _onboarding(ctx).create(
        name=body.name,
        created_by=caller,
        group_id=body.group_id,
        group_name=body.group_name,
    )
    ctx.session.commit()
    return {
        "counterparty_id": counterparty.id,
        "name": counterparty.name,
        "group_id": counterparty.group_id,
        "status": counterparty.status,
    }


@router.post("/counterparties/{counterparty_id}/verify")
def verify_counterparty(
    counterparty_id: str, body: rq.VerifyCounterpartyRequest, ctx: Ctx, caller: Caller
) -> dict:
    """Identifier, group parent, rating, instruments.

    Returns what the band entitles this name to, so the next step starts
    from the band rather than from a blank field.
    """
    counterparty, proposed = _onboarding(ctx).verify(
        counterparty_id=counterparty_id,
        legal_entity_identifier=body.legal_entity_identifier,
        group_parent_name=body.group_parent_name,
        rating=body.rating,
        country=body.country,
        instruments=list(body.instruments),
        verified_by=caller,
    )
    ctx.session.commit()
    return {
        "counterparty_id": counterparty.id,
        "status": counterparty.status,
        "rating": counterparty.rating,
        "proposed_limit_pence": proposed.amount_pence,
        "proposed_max_tenor_months": proposed.max_tenor_months,
    }


@router.post("/counterparties/{counterparty_id}/limit", status_code=201)
def set_limit(
    counterparty_id: str, body: rq.SetLimitRequest, ctx: Ctx, caller: Caller
) -> dict:
    """A limit nobody signed is not a control."""
    limit = _onboarding(ctx).set_limit(
        counterparty_id=counterparty_id,
        amount_pence=body.amount_pence,
        max_tenor_months=body.max_tenor_months,
        approved_by=body.approved_by,
        recorded_by=caller,
        reason=body.reason,
    )
    ctx.session.commit()
    return {
        "limit_id": limit.id,
        "counterparty_id": limit.counterparty_id,
        "amount_pence": limit.amount_pence,
        "max_tenor_months": limit.max_tenor_months,
        "source": limit.source,
        "approved_by": limit.approved_by,
    }


@router.post("/counterparties/{counterparty_id}/activate")
def activate_counterparty(
    counterparty_id: str, body: rq.ActivateCounterpartyRequest, ctx: Ctx, caller: Caller
) -> dict:
    """The name appears in the book and in the ticket."""
    counterparty = _onboarding(ctx).activate(counterparty_id, caller)
    ctx.session.commit()
    return {"counterparty_id": counterparty.id, "status": counterparty.status}


@router.get("/counterparties/{counterparty_id}/limits", response_model=list[LimitVersion])
def list_limits(
    counterparty_id: str, ctx: Ctx, caller: Caller
) -> list[LimitVersion]:
    """Every version, newest first. Superseded rows are the history."""
    return StateService(
        ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy, ctx.tenant_name
    ).limit_versions(counterparty_id)


@router.post("/counterparties/{counterparty_id}/rating")
def record_rating_action(
    counterparty_id: str, body: rq.RatingActionRequest, ctx: Ctx, caller: Caller
) -> dict:
    """One call in, an unknown number of breaches out."""
    service = RetestService(ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy)
    outcome = service.apply_rating_action(
        counterparty_id=counterparty_id,
        new_rating=body.new_rating,
        new_status=body.new_status,
        recorded_by=caller,
        effective_date=body.effective_date,
        source=body.source,
    )
    ctx.session.commit()
    return {
        "rating_event_id": outcome.event.id,
        "counterparty_id": counterparty_id,
        "action": outcome.event.action,
        "previous_rating": outcome.event.previous_rating,
        "new_rating": outcome.event.new_rating,
        "new_limit_pence": outcome.new_limit.amount_pence if outcome.new_limit else None,
        "new_max_tenor_months": (
            outcome.new_limit.max_tenor_months if outcome.new_limit else None
        ),
        "positions_tested": outcome.positions_tested,
        "breaches_raised": outcome.breaches_raised,
        "policy_version_id": ctx.policy.id,
    }


def _onboarding(ctx: Ctx) -> OnboardingService:
    return OnboardingService(ctx.session, ctx.tenant_id, ctx.as_of_date)
