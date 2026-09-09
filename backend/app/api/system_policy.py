"""System policy endpoints - Control panel's System Policy section.

Concentration cap, enforcement mode, rating bands, and the rate curve.
All in one GET/PUT so the settings panel can save the whole set in one
click.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import Caller, Ctx
from app.services import system_policy

router = APIRouter(tags=["System policy"])


@router.get("/system-policy")
def get_system_policy(ctx: Ctx, caller: Caller) -> dict:
    return system_policy.as_dict(ctx.session, ctx.tenant_id)


@router.put("/system-policy")
def put_system_policy(patch: dict[str, Any], ctx: Ctx, caller: Caller) -> dict:
    return system_policy.update(ctx.session, ctx.tenant_id, patch)


@router.post("/system-policy/reset-rate-curve")
def reset_rate_curve(ctx: Ctx, caller: Caller) -> dict:
    return system_policy.reset(ctx.session, ctx.tenant_id)
