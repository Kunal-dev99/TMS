"""What-if scenarios. AI proposes the reading; the numbers are ours.

Every endpoint here reads the current book, runs one deterministic scenario
against it (rolling back any transient write), asks the model for a short
paragraph, and returns the whole thing. Nothing is persisted.

There is no queue item, no check run, no rating event. A scenario is a
question, not a decision.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import Caller, Ctx
from app.services.credit_signals import CreditSignalService
from app.services.scenario_narrator import narrate
from app.services.scenario_service import ScenarioService

router = APIRouter(tags=["Scenarios"])


class RatingChangeRequest(BaseModel):
    counterparty_id: str
    new_rating: str
    new_status: str = "STABLE"


class NotRolledRequest(BaseModel):
    deal_id: str


class CapChangeRequest(BaseModel):
    new_cap_bp: int


def _service(ctx: Ctx) -> ScenarioService:
    return ScenarioService(
        ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy
    )


def _pack(delta) -> dict:
    """Serialise the delta after asking the model for a paragraph."""
    narrate(delta)
    return asdict(delta)


@router.post("/what-if/rating-change")
def rating_change(body: RatingChangeRequest, ctx: Ctx, caller: Caller) -> dict:
    return _pack(
        _service(ctx).rating_change(
            counterparty_id=body.counterparty_id,
            new_rating=body.new_rating,
            new_status=body.new_status,
        )
    )


@router.post("/what-if/not-rolled")
def not_rolled(body: NotRolledRequest, ctx: Ctx, caller: Caller) -> dict:
    return _pack(_service(ctx).not_rolled(deal_id=body.deal_id))


@router.post("/what-if/cap-change")
def cap_change(body: CapChangeRequest, ctx: Ctx, caller: Caller) -> dict:
    return _pack(_service(ctx).cap_change(new_cap_bp=body.new_cap_bp))


@router.post("/credit-signals/scan")
def scan_credit_signals(ctx: Ctx, caller: Caller) -> dict:
    """Read every counterparty's news file, classify, write cards."""
    from dataclasses import asdict

    service = CreditSignalService(
        ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy
    )
    signals = service.scan()
    return {"signals": [asdict(s) for s in signals]}
