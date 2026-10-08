"""Cash deployment planner.

- POST /planner/deploy-cash — run the planner with current settings.
- GET  /planner/settings    — return the editable knobs the modal renders.
- PUT  /planner/settings    — apply the sliders / strategy list.
- POST /planner/settings/reset — restore the built-in defaults.

Nothing is written to the ledger. Every candidate carries enough to load
straight into the ticket if the treasurer wants to take it — same shape
as any other proposed deal, and it passes through the same six checks on
the way in.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import Caller, Ctx
from app.services import planner_settings
from app.services import rate_limit as rl
from app.services.planner_narrator import narrate
from app.services.planner_service import PlannerService

router = APIRouter(tags=["Planner"])


@router.post(
    "/planner/deploy-cash",
    dependencies=[Depends(rl.limit_by_user(rl.PLANNER_DEPLOY))],
)
def deploy_cash(ctx: Ctx, caller: Caller) -> dict:
    planner = PlannerService(
        ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy
    )
    plan = planner.deploy_cash()
    narrate(plan, planner)
    return asdict(plan)


@router.get("/planner/settings")
def get_planner_settings(ctx: Ctx, caller: Caller) -> dict:
    return planner_settings.as_dict(
        planner_settings.get_settings(ctx.session, ctx.tenant_id)
    )


@router.put("/planner/settings")
def put_planner_settings(patch: dict[str, Any], ctx: Ctx, caller: Caller) -> dict:
    result = planner_settings.as_dict(
        planner_settings.update_settings(
            ctx.session, ctx.tenant_id, patch, updated_by_user_id=caller.user_id
        )
    )
    ctx.session.commit()
    return result


@router.post("/planner/settings/reset")
def reset_planner_settings(ctx: Ctx, caller: Caller) -> dict:
    result = planner_settings.as_dict(
        planner_settings.reset_defaults(
            ctx.session, ctx.tenant_id, updated_by_user_id=caller.user_id
        )
    )
    ctx.session.commit()
    return result
