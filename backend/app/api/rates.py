"""Rate quote endpoint - the Bloomberg BGN pre-fill story.

In production the treasurer's ticket pre-fills the interest-rate field
from a market composite (Bloomberg BGN via B-PIPE, or the LSEG
equivalent) so they see today's indicative rate before typing over it
with the counterparty's actual negotiated rate.

In the prototype the rate curve is our own deterministic table (same
one the planner uses). The endpoint tags every returned rate as
\"Bloomberg BGN composite - stubbed for demo\" so the shape production
would use is on screen today.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.api.deps import Caller, Ctx
from app.services.planner_service import _rate_for
from app.repo import counterparties as cp_repo

router = APIRouter(tags=["Rates"])


@router.get("/rates/quote")
def rate_quote(
    ctx: Ctx,
    caller: Caller,
    counterparty_id: str = Query(...),
    instrument: str = Query(...),
    tenor_months: int = Query(..., ge=1, le=60),
) -> dict:
    """Indicative rate for a proposed ticket.

    Returns an indicative rate + the source metadata the UI needs to
    render \"from Bloomberg BGN - indicative - as of ... - stubbed\".
    """
    cp = cp_repo.get(ctx.session, counterparty_id)
    if cp is None or cp.tenant_id != ctx.tenant_id:
        # Cheap fallback so the endpoint never breaks the ticket.
        rate_bp = 400
        rating = "A-"
    else:
        rating = cp.rating
        # Clamp tenor to the curve's known range for a stable quote.
        clamped = max(3, min(24, tenor_months))
        rate_bp = _rate_for(rating, clamped)

    now = datetime.now(timezone.utc)
    return {
        "counterparty_id": counterparty_id,
        "instrument": instrument,
        "tenor_months": tenor_months,
        "rate_bp": rate_bp,
        "rating_used": rating,
        "source": "Bloomberg BGN composite",
        "quality": "indicative",
        "as_of": now.strftime("%Y-%m-%d %H:%M UTC"),
        "notice": (
            "Prototype: indicative rate from our own rate curve, "
            "tagged as Bloomberg BGN for the demo shape. In "
            "production this pulls from Bloomberg B-PIPE (or LSEG "
            "Real-Time) as a market composite. The treasurer "
            "overrides with the counterparty's negotiated rate on "
            "booking."
        ),
    }
