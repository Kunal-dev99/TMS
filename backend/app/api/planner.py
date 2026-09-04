"""Cash deployment planner.

One endpoint. Reads the idle cash and the current book, generates four
candidate deployments, has the AI rank and label them, returns the whole
thing for the modal to render.

Nothing is written. Each candidate carries enough to load straight into
the ticket if the treasurer wants to take it — same shape as any other
proposed deal, and it passes through the same six checks on the way in.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from app.api.deps import Caller, Ctx
from app.services.planner_narrator import narrate
from app.services.planner_service import PlannerService

router = APIRouter(tags=["Planner"])


@router.post("/planner/deploy-cash")
def deploy_cash(ctx: Ctx, caller: Caller) -> dict:
    planner = PlannerService(
        ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy
    )
    plan = planner.deploy_cash()
    narrate(plan, planner)
    return asdict(plan)
