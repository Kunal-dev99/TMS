"""The queue and breaches. Group 6 of document 2.

One queue, two causes, told apart by a reason code. Four endpoints.

Responding to a breach records the decision. It does not clear the breach and
it does not change the deal, and the count in the strip does not fall,
because the position is still outside policy.
"""

from fastapi import APIRouter

from app.api.deps import Caller, Ctx
from app.schemas import requests as rq
from app.schemas.models import BreachView, QueueItem
from app.services.breach_service import BreachService
from app.services.queue_service import QueueService
from app.services.state_service import StateService

router = APIRouter(tags=["The queue and breaches"])


@router.get("/queue", response_model=list[QueueItem])
def get_queue(ctx: Ctx, caller: Caller) -> list[QueueItem]:
    """Open items, both causes. Each carries its reason code."""
    return _state(ctx).queue()


@router.post("/queue/{item_id}/resolve")
def resolve_queue_item(
    item_id: str, body: rq.ResolveQueueItemRequest, ctx: Ctx, caller: Caller
) -> dict:
    service = QueueService(ctx.session, ctx.tenant_id, ctx.policy, ctx.as_of_date)
    item = service.resolve(
        item_id=item_id,
        resolution=body.resolution,
        resolved_by=caller,
        reason=body.reason,
    )
    ctx.session.commit()
    return {
        "queue_item_id": item.id,
        "status": item.status,
        "resolution": item.resolution,
        "deal_id": item.deal_id,
    }


@router.get("/breaches", response_model=list[BreachView])
def get_breaches(ctx: Ctx, caller: Caller) -> list[BreachView]:
    """All breaches, newest first."""
    return _state(ctx).breaches()


@router.post("/breaches/{breach_id}/respond")
def respond_to_breach(
    breach_id: str, body: rq.RespondToBreachRequest, ctx: Ctx, caller: Caller
) -> dict:
    breach = BreachService(ctx.session, ctx.tenant_id).respond(
        breach_id=breach_id,
        response=body.response,
        responded_by=caller,
        reason=body.reason,
    )
    ctx.session.commit()
    return {
        "breach_id": breach.id,
        "status": breach.status,
        "response": breach.response,
        "responded_at": breach.responded_at,
        "cleared": False,
    }


def _state(ctx: Ctx) -> StateService:
    return StateService(
        ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy, ctx.tenant_name
    )
