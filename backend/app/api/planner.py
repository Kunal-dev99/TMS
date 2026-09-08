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

from fastapi import APIRouter

from app.api.deps import Caller, Ctx
from app.services import planner_settings
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


@router.get("/planner/settings")
def get_planner_settings(caller: Caller) -> dict:
    return planner_settings.as_dict(planner_settings.get_settings())


@router.put("/planner/settings")
def put_planner_settings(patch: dict[str, Any], caller: Caller) -> dict:
    return planner_settings.as_dict(planner_settings.update_settings(patch))


@router.post("/planner/settings/reset")
def reset_planner_settings(caller: Caller) -> dict:
    return planner_settings.as_dict(planner_settings.reset_defaults())
