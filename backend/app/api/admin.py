"""Administration. The header controls.

Three endpoints, and they are on the header rather than behind a settings
screen because two of them are the unsettled design decisions made visible.

Switching enforcement live is the fastest way to settle which policy the
business wants: flip it on a failing deal in the room rather than argue about
it in a slide.

Moving the clock is how a demonstration shows accrual and maturity without
waiting. Everything in the system derives from it.
"""

from fastapi import APIRouter

from app.api.deps import Caller, Ctx
from app.ids import new_id, now
from app.models import PolicyVersion, SystemClock
from app.schemas import requests as rq
from app.schemas.models import PolicyConfig
from app.services.state_service import StateService

router = APIRouter(tags=["Administration"])


@router.post("/admin/clock")
def set_clock(body: rq.SetClockRequest, ctx: Ctx, caller: Caller) -> dict:
    """Set today. Everything derives from it."""
    clock = ctx.session.get(SystemClock, ctx.tenant_id)
    clock.today_date = body.today_date
    clock.updated_at = now()
    ctx.session.commit()
    return {"today_date": clock.today_date}


@router.post("/admin/enforcement", response_model=PolicyConfig)
def set_enforcement(
    body: rq.SetEnforcementRequest, ctx: Ctx, caller: Caller
) -> PolicyConfig:
    """Block, or warn with an override.

    A new policy version rather than an edit. The setting is a rule, and a
    rule that changed in place would make every check run recorded under the
    old one unreproducible.
    """
    if body.enforcement == ctx.policy.enforcement:
        return _state(ctx).policy_config()

    timestamp = now()
    ctx.policy.superseded_at = timestamp

    replacement = PolicyVersion(
        id=new_id("pol"),
        tenant_id=ctx.tenant_id,
        effective_from=ctx.as_of_date,
        superseded_at=None,
        concentration_cap_bp=ctx.policy.concentration_cap_bp,
        threshold_analyst_pence=ctx.policy.threshold_analyst_pence,
        threshold_hot_pence=ctx.policy.threshold_hot_pence,
        enforcement=body.enforcement,
        fx_add_on_bp=ctx.policy.fx_add_on_bp,
        approved_by=ctx.policy.approved_by,
    )
    ctx.session.add(replacement)
    ctx.session.commit()

    ctx.policy = replacement
    return _state(ctx).policy_config()


@router.post("/admin/reset")
def reset(ctx: Ctx, caller: Caller) -> dict:
    """Drop every row and reload the seed.

    The one place in the system where something is deleted. A reseed is not
    the system: nothing a user does inside the system deletes anything.
    """
    from seed.seed import clear, load

    clear(ctx.session)
    load(ctx.session)
    ctx.session.commit()
    return {"reset": True}


def _state(ctx: Ctx) -> StateService:
    return StateService(
        ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy, ctx.tenant_name
    )
