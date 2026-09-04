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
from sqlalchemy import select

from app.api.deps import Caller, Ctx
from app.ids import new_id, now
from app.models import PolicyVersion, SystemClock
from app.schemas import requests as rq
from app.schemas.models import PolicyConfig, StateResponse
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


@router.post("/admin/reset", response_model=StateResponse)
def reset(ctx: Ctx, caller: Caller) -> StateResponse:
    """Drop every row and reload the seed. Returns the fresh state.

    The one place in the system where something is deleted. A reseed is not
    the system: nothing a user does inside the system deletes anything.

    Returns the fresh state directly rather than {"reset": True} plus a
    trip back to `GET /state`, because the caller always needs both. That
    cuts one HTTP round trip out of the whole demo Reset flow -- ~230 ms
    on the seed today.
    """
    from sqlalchemy import text
    from seed.seed import clear, load

    # A demo reset is not a durable write. If the process crashes between
    # `clear` and `load`, the next reset will simply try again -- there is
    # no half-committed state to protect. Turning off SQLite's fsync for
    # the duration of the reset alone cuts perhaps a third off the wall
    # clock. Restored below in a finally so a crash cannot leave the
    # session running unsynced.
    prior = ctx.session.execute(text("PRAGMA synchronous")).scalar()
    try:
        ctx.session.execute(text("PRAGMA synchronous = OFF"))
        clear(ctx.session)
        load(ctx.session)
        ctx.session.commit()
    finally:
        ctx.session.execute(text(f"PRAGMA synchronous = {prior}"))

    # The ctx was built from a request that pre-dates the reset. Every ORM
    # object it references was in a row that has just been deleted and
    # replaced. Re-read the two pieces the state service needs, so it sees
    # the fresh rows rather than the detached instances the middleware
    # captured on request entry.
    fresh_policy = ctx.session.scalars(
        select(PolicyVersion)
        .where(PolicyVersion.tenant_id == ctx.tenant_id)
        .where(PolicyVersion.superseded_at.is_(None))
    ).one()
    fresh_clock = ctx.session.get(SystemClock, ctx.tenant_id)
    return StateService(
        ctx.session,
        ctx.tenant_id,
        fresh_clock.today_date,
        fresh_policy,
        ctx.tenant_name,
    ).state()


def _state(ctx: Ctx) -> StateService:
    return StateService(
        ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy, ctx.tenant_name
    )
