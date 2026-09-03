"""The advisory layer. Group 7 of document 2.

Four endpoints. The important one is the last, and what matters about it is
what it does not do: recording a decision returns a ticket and creates
nothing. The deal is created by POST /deals like any other and passes the
same six checks.

That is the whole of the guardrail, expressed as an API shape rather than as
a policy somebody has to remember.
"""

from fastapi import APIRouter

from app.api.deps import Caller, Ctx
from app.schemas import requests as rq
from app.schemas.models import AdvisoryCard, AdvisoryRun
from app.services.advisory_service import AdvisoryService
from app.services.advisory_view import card_for, run_for

router = APIRouter(tags=["The advisory layer"])


@router.get("/advisory/latest")
def advisory_latest(ctx: Ctx, caller: Caller) -> AdvisoryCard | None:
    """Null is a valid answer and not a 404.

    No gap is a real state, and so is a recommendation somebody has already
    acted on. An empty card would imply something is broken.
    """
    outcome = _service(ctx).latest()
    if outcome is None or outcome.recommendation is None:
        return None
    if outcome.recommendation.decision is not None:
        return None
    return card_for(ctx.session, outcome)


@router.get("/advisory/runs/{run_id}", response_model=AdvisoryRun)
def advisory_run(run_id: str, ctx: Ctx, caller: Caller) -> AdvisoryRun:
    """The full run: six stages, every candidate including the excluded ones
    with their reasons, and the three validation results."""
    return run_for(ctx.session, _service(ctx).load_run(run_id))


@router.post("/advisory/runs")
def trigger_advisory_run(body: rq.RunAdvisoryRequest, ctx: Ctx, caller: Caller) -> dict:
    """Called by the scheduler nightly, and by hand during a demonstration."""
    outcome = _service(ctx).run(as_of=body.as_of, force=body.force)
    ctx.session.commit()
    return {
        "run_id": outcome.run.id,
        "outcome": outcome.run.outcome,
        "gap_type": outcome.run.gap_type,
        "recommendation_id": (
            outcome.recommendation.id if outcome.recommendation else None
        ),
        "candidates": len(outcome.candidates),
        "excluded": len([c for c in outcome.candidates if c.excluded]),
    }


@router.post("/advisory/recommendations/{recommendation_id}/decide")
def decide_recommendation(
    recommendation_id: str,
    body: rq.DecideRecommendationRequest,
    ctx: Ctx,
    caller: Caller,
) -> dict:
    """Record what a person decided. Books nothing.

    On acceptance this returns the payload the deal form loads: the same
    five fields somebody would have typed. There is no sixth field carrying
    a result the checks would then trust.
    """
    recommendation, candidate = _service(ctx).decide(
        recommendation_id, body.decision, caller, body.reason
    )
    ctx.session.commit()
    return {
        "ok": True,
        "decision": recommendation.decision,
        "ticket": None
        if candidate is None
        else {
            "counterparty_id": candidate.counterparty_id,
            "instrument": candidate.instrument,
            "principal_pence": candidate.amount_pence,
            "tenor_months": candidate.tenor_months,
            "rate_bp": candidate.indicative_rate_bp,
        },
    }


def _service(ctx: Ctx) -> AdvisoryService:
    return AdvisoryService(ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy)
