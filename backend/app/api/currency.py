"""Currency risk, and counterparty exposure. Group 8 of document 2.

Only the counterparty exposure endpoint is live. Document 2 notes it was
renamed from GET /exposure in revision A, so it belongs to phase one; the
currency register and hedge linkage are phase three.

There is deliberately no GET /exposure that returns both. A forward increases
counterparty exposure and reduces currency exposure, so a single figure would
be meaningless in the best case and misleading in the worst. Making it
impossible to ask for is cheaper than documenting that it should not be
asked for.
"""

from fastapi import APIRouter

from app.api.deps import Caller, Ctx
from app.schemas.models import ExposureView
from app.services.exposure_service import ExposureService

router = APIRouter(tags=["Currency risk"])


@router.get("/exposure/counterparty", response_model=ExposureView)
def exposure_counterparty(ctx: Ctx, caller: Caller) -> ExposureView:
    """Utilisation by credit group, rating band and maturity bucket. Pence.

    Recomputed on every call by design. A cached figure that drifts from the
    deals behind it is worse than a slow query.
    """
    return ExposureService(
        ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy
    ).counterparty_exposure()
