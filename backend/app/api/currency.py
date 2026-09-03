"""Currency risk, and counterparty exposure. Group 8 of document 2.

There is deliberately no GET /exposure that returns both figures. A forward
increases counterparty exposure and reduces currency exposure, so a single
number would be meaningless in the best case and misleading in the worst.
Making it impossible to ask for is cheaper than documenting that it should
not be asked for.

Two endpoints, two units, and no query in the repository layer joins them.
"""

from fastapi import APIRouter

from app.api.deps import Caller, Ctx
from app.schemas import requests as rq
from app.schemas.models import (
    CurrencyBucket,
    CurrencyExposureRow,
    CurrencyExposureView,
    ExposureView,
    HedgeLinkView,
)
from app.services.exposure_service import ExposureService
from app.services.hedge_service import HedgeService

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


@router.get("/exposure/currency", response_model=CurrencyExposureView)
def exposure_currency(
    ctx: Ctx, caller: Caller, currency: str = "EUR"
) -> CurrencyExposureView:
    """Net obligation and coverage by currency and bucket. Minor units, with
    a currency on every figure.

    Never netted against counterparty exposure, and the response carries the
    warning saying so, because the interface is where somebody would try it.
    """
    service = HedgeService(ctx.session, ctx.tenant_id, ctx.as_of_date)
    return CurrencyExposureView(
        as_of_date=ctx.as_of_date,
        currency=currency.upper(),
        buckets=[
            CurrencyBucket(
                bucket=row.bucket,
                net_minor=row.net_minor,
                covered_minor=row.covered_minor,
                target_cover_bp=row.target_cover_bp,
                covered_bp=row.covered_bp,
            )
            for row in service.coverage(currency)
        ],
        exposures=[
            CurrencyExposureRow(
                id=exposure.id,
                currency=exposure.currency,
                amount_minor=exposure.amount_minor,
                direction=exposure.direction,
                expected_date=exposure.expected_date,
                source=exposure.source,
                source_reference=exposure.source_reference,
                status=exposure.status,
                hedges=[
                    HedgeLinkView(
                        id=link.id,
                        deal_id=link.deal_id,
                        covered_amount_minor=link.covered_amount_minor,
                        currency=exposure.currency,
                        linked_at=link.linked_at,
                        unlinked_at=link.unlinked_at,
                        unlink_reason=link.unlink_reason,
                    )
                    for link in service.live_links(exposure.id)
                ],
            )
            for exposure in service.exposures(currency)
        ],
    )


@router.post("/currency-exposures", status_code=201)
def create_currency_exposure(
    body: rq.CreateCurrencyExposureRequest, ctx: Ctx, caller: Caller
) -> dict:
    """Record an obligation. It exists before any hedge."""
    service = HedgeService(ctx.session, ctx.tenant_id, ctx.as_of_date)
    exposure = service.record_exposure(
        currency=body.currency,
        amount_minor=body.amount_minor,
        direction=body.direction,
        expected_date=body.expected_date,
        source=body.source,
        source_reference=body.source_reference,
        created_by=caller,
    )
    ctx.session.commit()
    return {
        "id": exposure.id,
        "currency": exposure.currency,
        "amount_minor": exposure.amount_minor,
        "direction": exposure.direction,
        "status": exposure.status,
    }


@router.post("/currency-exposures/{exposure_id}/hedges", status_code=201)
def link_hedge(
    exposure_id: str, body: rq.LinkHedgeRequest, ctx: Ctx, caller: Caller
) -> dict:
    """Link a forward to an obligation.

    The step that makes it hedging rather than owning forwards.
    """
    service = HedgeService(ctx.session, ctx.tenant_id, ctx.as_of_date)
    link = service.link(
        currency_exposure_id=exposure_id,
        deal_id=body.deal_id,
        covered_amount_minor=body.covered_amount_minor,
        linked_by=caller,
    )
    ctx.session.commit()
    exposure = ctx.session.get(
        __import__("app.models", fromlist=["CurrencyExposure"]).CurrencyExposure,
        exposure_id,
    )
    return {
        "hedge_link_id": link.id,
        "currency_exposure_id": exposure_id,
        "deal_id": link.deal_id,
        "covered_amount_minor": link.covered_amount_minor,
        "status": exposure.status,
    }


@router.post("/hedge-links/{link_id}/unlink")
def unlink_hedge(
    link_id: str, body: rq.UnlinkHedgeRequest, ctx: Ctx, caller: Caller
) -> dict:
    """Break the link. Requires a reason.

    Coverage is recomputed and the status can move backwards. A covered
    exposure becoming partially covered when a delivery slips is correct
    behaviour: nobody made a mistake, the world moved.
    """
    service = HedgeService(ctx.session, ctx.tenant_id, ctx.as_of_date)
    exposure = service.unlink(link_id, body.reason, caller)
    ctx.session.commit()
    return {
        "hedge_link_id": link_id,
        "unlink_reason": body.reason,
        "currency_exposure_id": exposure.id,
        "status": exposure.status,
        "covered_amount_minor": service.covered_minor(exposure.id),
    }
