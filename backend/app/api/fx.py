"""FX exposure & hedging capability.

A separate router from `currency.py`, which speaks in the language of
document 2 — record an obligation, link a forward, view coverage. This
router speaks in the language of the demo panel — one dashboard endpoint
per screen region, plus a POST that atomically creates the FX forward
Deal row and its HedgeLink so the user does not have to make two calls
from a UI that only lets them click one button.

The panel shows the sales-side story: receivable EUR/USD/CHF from
overseas customers, protected by FX forwards. Payables are handled by
the older /currency-exposures endpoint and stay out of this view for
simplicity.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import Caller, Ctx
from app.errors import ErrorCode, TreasuryError
from app.ids import new_id, now
from app.models import (
    Counterparty,
    CounterpartyInstrument,
    CpGroup,
    CurrencyCoverTarget,
    Deal,
    HedgeLink,
    InvestmentPolicy,
)
from app.repo import counterparties as cp_repo
from app.schemas.models import CheckResult
from app.services.check_engine import CheckEngine
from app.services.exposure_calculator import ExposureCalculator
from app.services.fx_exposure_service import FxExposureService
from app.services.fx_narrator import (
    advise_on_hedge as narrator_advise,
    narrate as narrate_fx,
)
from app.services.fx_rate_service import (
    FxQuote,
    forward as forward_rate,
    spot as spot_rate,
    supported_pairs,
)
from app.services.hedge_service import HedgeService

router = APIRouter(tags=["FX hedging"], prefix="/fx")


# ------------------------------------------------------------- schemas


class FxCurrencySummary(BaseModel):
    currency: str
    gross_minor: int
    hedged_minor: int
    unhedged_minor: int
    hedge_ratio_bp: int
    gross_gbp_pence: int
    unhedged_gbp_pence: int
    target_cover_bp: int
    gap_to_target_minor: int


class FxBucketRow(BaseModel):
    bucket: str
    label: str
    forecast_minor: int
    hedged_minor: int
    unhedged_minor: int
    forecast_gbp_pence: int
    unhedged_gbp_pence: int


class FxExposureRow(BaseModel):
    id: str
    expected_date: str
    amount_minor: int
    direction: str
    source: str
    source_reference: str | None
    status: str
    hedged_minor: int


class FxExposureView(BaseModel):
    currency: str
    summary: FxCurrencySummary
    buckets: list[FxBucketRow]
    exposures: list[FxExposureRow]


class FxSummaryView(BaseModel):
    as_of_date: str
    base_currency: str = "GBP"
    currencies: list[FxCurrencySummary]
    sources: dict[str, str]


class FxRateQuote(BaseModel):
    pair: str
    spot: float
    forward: float
    forward_points_bp: int
    tenor_months: int
    source: str
    quality: str
    as_of: str


class FxCounterpartyView(BaseModel):
    id: str
    name: str
    rating: str
    status: str
    group_name: str | None
    entity_limit_pence: int
    entity_used_pence: int
    entity_headroom_pence: int
    group_limit_pence: int
    group_used_pence: int
    group_headroom_pence: int
    near_cap: bool  # true if either headroom is under 20% of its limit


class FxRecommendationView(BaseModel):
    currency: str
    amount_minor: int
    tenor_months: int
    counterparty_id: str
    counterparty_name: str
    reason: str


class FxBriefingView(BaseModel):
    briefing: str
    recommendations: list[FxRecommendationView]
    watch: list[str]


class InitiateHedgeRequest(BaseModel):
    currency: str = Field(..., description="Foreign currency being sold forward (EUR, USD, CHF)")
    sell_amount_minor: int = Field(..., gt=0)
    tenor_months: int = Field(..., ge=1, le=24)
    counterparty_id: str
    exposure_ids: list[str] = Field(
        default_factory=list,
        description="One or more currency_exposure ids this hedge covers. Amounts allocated pro-rata across unhedged balance.",
    )
    reference: str | None = None
    comments: str | None = None
    override_reason: str | None = None


class HedgeCheckRequest(BaseModel):
    currency: str
    sell_amount_minor: int = Field(..., gt=0)
    tenor_months: int = Field(..., ge=1, le=24)
    counterparty_id: str


class InitiateHedgeResponse(BaseModel):
    deal_id: str
    hedge_link_ids: list[str]
    currency: str
    sell_amount_minor: int
    tenor_months: int
    forward_rate: float
    expected_gbp_pence: int
    counterparty_name: str
    trade_date: str
    maturity_date: str


# ------------------------------------------------------------- helpers


def _pair_for(currency: str) -> str:
    return f"{currency.upper()}_GBP"


def _quote_to_view(q: FxQuote) -> FxRateQuote:
    return FxRateQuote(
        pair=q.pair,
        spot=q.spot,
        forward=q.forward,
        forward_points_bp=q.forward_points_bp,
        tenor_months=q.tenor_months,
        source=q.source,
        quality=q.quality,
        as_of=q.as_of,
    )


# ------------------------------------------------------------- endpoints


@router.get("/exposures", response_model=FxSummaryView)
def summary(ctx: Ctx, caller: Caller) -> FxSummaryView:
    """One row per currency. What the dashboard opens on."""
    service = FxExposureService(ctx.session, ctx.tenant_id, ctx.as_of_date)
    rows = service.summary()
    return FxSummaryView(
        as_of_date=ctx.as_of_date,
        currencies=[FxCurrencySummary(**row.__dict__) for row in rows],
        sources={
            "forecast": "Oracle EPM (stubbed)",
            "rates": "Bloomberg BGN composite (stubbed)",
            "policy": "InvestmentPolicy.CurrencyCoverTarget",
        },
    )


@router.get("/exposures/{currency}", response_model=FxExposureView)
def by_currency(currency: str, ctx: Ctx, caller: Caller) -> FxExposureView:
    """Bucket drilldown plus underlying receivables for one currency."""
    service = FxExposureService(ctx.session, ctx.tenant_id, ctx.as_of_date)
    return FxExposureView(
        currency=currency.upper(),
        summary=FxCurrencySummary(**service._summary_for(currency.upper()).__dict__),
        buckets=[FxBucketRow(**row.__dict__) for row in service.by_bucket(currency.upper())],
        exposures=[FxExposureRow(**row.__dict__) for row in service.exposures(currency.upper())],
    )


@router.get("/rates/spot/{pair}", response_model=FxRateQuote)
def spot_endpoint(pair: str, ctx: Ctx, caller: Caller) -> FxRateQuote:
    try:
        return _quote_to_view(spot_rate(pair))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/rates/forward/{pair}", response_model=FxRateQuote)
def forward_endpoint(
    pair: str,
    ctx: Ctx,
    caller: Caller,
    tenor: int = Query(6, ge=1, le=24),
) -> FxRateQuote:
    try:
        return _quote_to_view(forward_rate(pair, tenor))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/counterparties", response_model=list[FxCounterpartyView])
def fx_counterparties(ctx: Ctx, caller: Caller) -> list[FxCounterpartyView]:
    """Approved counterparties permitted to trade FX_FORWARD.

    Reuses the existing counterparty master (not a separate list) —
    filtered to those with an FX_FORWARD instrument permission.
    Enriched with **live entity and group headroom** so the treasurer
    can see, on the dropdown itself, whether a bank still has room for
    the trade before opening the check panel.
    """
    statement = (
        select(Counterparty, CounterpartyInstrument)
        .join(
            CounterpartyInstrument,
            CounterpartyInstrument.counterparty_id == Counterparty.id,
        )
        .where(Counterparty.tenant_id == ctx.tenant_id)
        .where(Counterparty.status == "ACTIVE")
        .where(CounterpartyInstrument.instrument == "FX_FORWARD")
    )

    exposure_calc = ExposureCalculator(
        ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy
    )
    by_cp = exposure_calc.exposure_by_counterparty()
    by_group = exposure_calc.exposure_by_group()

    seen: set[str] = set()
    out: list[FxCounterpartyView] = []
    for cp, _perm in ctx.session.execute(statement):
        if cp.id in seen:
            continue
        seen.add(cp.id)
        limit = cp_repo.current_limit(ctx.session, cp.id)
        group = cp_repo.group(ctx.session, cp.group_id)
        entity_limit = limit.amount_pence if limit else 0
        entity_used = by_cp.get(cp.id, 0)
        entity_headroom = max(0, entity_limit - entity_used)
        group_limit = group.group_limit_pence if group else 0
        group_used = by_group.get(cp.group_id, 0)
        group_headroom = max(0, group_limit - group_used)

        near_cap = False
        if entity_limit > 0 and entity_headroom * 5 <= entity_limit:
            near_cap = True
        if group_limit > 0 and group_headroom * 5 <= group_limit:
            near_cap = True

        out.append(
            FxCounterpartyView(
                id=cp.id,
                name=cp.name,
                rating=cp.rating,
                status=cp.status,
                group_name=cp.group_parent_name,
                entity_limit_pence=entity_limit,
                entity_used_pence=entity_used,
                entity_headroom_pence=entity_headroom,
                group_limit_pence=group_limit,
                group_used_pence=group_used,
                group_headroom_pence=group_headroom,
                near_cap=near_cap,
            )
        )
    return out


@router.post("/hedges/check", response_model=CheckResult)
def check_hedge(body: HedgeCheckRequest, ctx: Ctx, caller: Caller) -> CheckResult:
    """Dry-run the six checks against a proposed hedge.

    Persists nothing. The modal calls this on every material change to
    show the treasurer a live PASS/FAIL before Initiate is clicked, the
    same pattern the deposit ticket uses.

    The counterparty-exposure figure used here is the same measurement
    the DealService applies to any FX_FORWARD — notional × the policy
    FX add-on — so the six checks read the same numbers on both paths.
    """
    engine = CheckEngine(ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy)
    quote = forward_rate(_pair_for(body.currency), body.tenor_months)
    principal_pence = round(body.sell_amount_minor * quote.forward)
    try:
        return engine.run(
            counterparty_id=body.counterparty_id,
            instrument="FX_FORWARD",
            principal_pence=principal_pence,
            tenor_months=body.tenor_months,
            rate_bp=int(round(quote.forward * 10_000)),
        ).result
    except LookupError as exc:
        raise TreasuryError(
            ErrorCode.COUNTERPARTY_NOT_FOUND, field="counterparty_id"
        ) from exc


@router.post("/hedges", response_model=InitiateHedgeResponse, status_code=201)
def initiate_hedge(
    body: InitiateHedgeRequest, ctx: Ctx, caller: Caller
) -> InitiateHedgeResponse:
    """Book an FX forward and link it to the underlying exposure(s).

    A single click in the panel is two writes: create the Deal row
    (instrument = FX_FORWARD, status ACTIVE) and one HedgeLink per
    exposure it covers. Amount allocation is pro-rata across the
    remaining unhedged balance of the named exposures.
    """
    session = ctx.session
    currency = body.currency.upper()
    pair = _pair_for(currency)
    quote = forward_rate(pair, body.tenor_months)

    counterparty = session.get(Counterparty, body.counterparty_id)
    if counterparty is None or counterparty.tenant_id != ctx.tenant_id:
        raise TreasuryError(ErrorCode.COUNTERPARTY_NOT_FOUND, field="counterparty_id")
    if counterparty.status != "ACTIVE":
        raise TreasuryError(
            ErrorCode.COUNTERPARTY_NOT_ACTIVE,
            f"{counterparty.name} is {counterparty.status.lower()}.",
            field="counterparty_id",
        )

    # The six checks. Every path into the book runs the same engine —
    # deposits and FX forwards alike. A hedge that would push the
    # counterparty past its limit is refused here rather than being
    # discovered later on the exposure panel.
    gbp_expected_pence = round(body.sell_amount_minor * quote.forward)
    rate_bp = int(round(quote.forward * 10_000))
    engine = CheckEngine(session, ctx.tenant_id, ctx.as_of_date, ctx.policy)
    evaluation = engine.run(
        counterparty_id=counterparty.id,
        instrument="FX_FORWARD",
        principal_pence=gbp_expected_pence,
        tenor_months=body.tenor_months,
        rate_bp=rate_bp,
    )
    result = evaluation.result
    if result.outcome == "FAIL":
        if body.override_reason and ctx.policy.enforcement != "HARD_BLOCK":
            pass  # soft-warn override recorded on the deal below
        else:
            failed = [o.key for o in result.checks if not o.passed]
            raise TreasuryError(
                ErrorCode.CHECK_INPUTS_UNAVAILABLE
                if "CHECK_INPUTS" in failed
                else ErrorCode.OVERRIDE_NOT_ALLOWED
                if ctx.policy.enforcement == "HARD_BLOCK"
                else ErrorCode.OVERRIDE_REASON_REQUIRED,
                f"{len(failed)} of six checks failed: {', '.join(failed)}. "
                f"{result.verdict}",
                field="sell_amount_minor",
            )

    trade_date = ctx.as_of_date
    from datetime import date, timedelta

    maturity = (
        date.fromisoformat(trade_date) + timedelta(days=30 * body.tenor_months)
    ).isoformat()

    deal = Deal(
        id=new_id("dl"),
        tenant_id=ctx.tenant_id,
        counterparty_id=counterparty.id,
        instrument="FX_FORWARD",
        principal_pence=gbp_expected_pence,
        currency=currency,
        rate_bp=rate_bp,
        tenor_months=body.tenor_months,
        trade_date=trade_date,
        value_date=trade_date,
        maturity_date=maturity,
        status="ACTIVE",
        capture_source="KEYED",
        created_by=str(caller),
        created_by_user_id=caller.user_id,
        created_at=now(),
        required_approver=result.required_approver,
        limit_id_at_booking=result.limit_id,
        policy_version_id=ctx.policy.id,
        approved_by=None,
        approved_at=None,
    )
    session.add(deal)
    session.flush()

    # Allocate across exposures pro-rata to remaining unhedged.
    hedge = HedgeService(session, ctx.tenant_id, ctx.as_of_date)
    if not body.exposure_ids:
        raise HTTPException(
            status_code=400,
            detail="At least one exposure_id is required.",
        )

    remaining: dict[str, int] = {}
    for exposure_id in body.exposure_ids:
        from app.models import CurrencyExposure  # local import to keep top clean

        exp = session.get(CurrencyExposure, exposure_id)
        if exp is None or exp.tenant_id != ctx.tenant_id:
            raise TreasuryError(
                ErrorCode.CONFIRMATION_NOT_FOUND,
                f"Exposure {exposure_id} not found.",
                field="exposure_ids",
            )
        remaining[exposure_id] = exp.amount_minor - hedge.covered_minor(exp.id)

    total_remaining = sum(v for v in remaining.values() if v > 0)
    if total_remaining <= 0:
        raise TreasuryError(
            ErrorCode.HEDGE_EXCEEDS_EXPOSURE,
            "All selected exposures are already fully covered.",
            field="exposure_ids",
        )
    if body.sell_amount_minor > total_remaining:
        raise TreasuryError(
            ErrorCode.HEDGE_EXCEEDS_EXPOSURE,
            f"Cannot hedge {body.sell_amount_minor / 100:,.2f} {currency}; "
            f"only {total_remaining / 100:,.2f} {currency} remains unhedged "
            f"across the selected exposures.",
            field="sell_amount_minor",
        )

    link_ids: list[str] = []
    to_allocate = body.sell_amount_minor
    keys = list(remaining.keys())
    for idx, exposure_id in enumerate(keys):
        room = remaining[exposure_id]
        if room <= 0:
            continue
        if idx == len(keys) - 1:
            covered = to_allocate  # last slice takes the remainder
        else:
            covered = min(room, round(body.sell_amount_minor * room / total_remaining))
        if covered <= 0:
            continue
        link = hedge.link(
            currency_exposure_id=exposure_id,
            deal_id=deal.id,
            covered_amount_minor=covered,
            linked_by=caller,
        )
        link_ids.append(link.id)
        to_allocate -= covered

    session.commit()

    return InitiateHedgeResponse(
        deal_id=deal.id,
        hedge_link_ids=link_ids,
        currency=currency,
        sell_amount_minor=body.sell_amount_minor,
        tenor_months=body.tenor_months,
        forward_rate=quote.forward,
        expected_gbp_pence=gbp_expected_pence,
        counterparty_name=counterparty.name,
        trade_date=trade_date,
        maturity_date=maturity,
    )


class HedgeAdviseRequest(BaseModel):
    currency: str
    sell_amount_minor: int = Field(..., gt=0)
    tenor_months: int = Field(..., ge=1, le=24)
    counterparty_id: str


class HedgeAdviseView(BaseModel):
    observations: list[str]


@router.post("/hedges/advise", response_model=HedgeAdviseView)
def advise_hedge(
    body: HedgeAdviseRequest, ctx: Ctx, caller: Caller
) -> HedgeAdviseView:
    """AI advisor for the Initiate modal — concentration, ladder, cost of carry."""
    obs = narrator_advise(
        ctx.session,
        ctx.tenant_id,
        ctx.as_of_date,
        ctx.policy,
        currency=body.currency,
        sell_amount_minor=body.sell_amount_minor,
        tenor_months=body.tenor_months,
        counterparty_id=body.counterparty_id,
    )
    return HedgeAdviseView(observations=obs)


class FxPolicyTargetView(BaseModel):
    currency: str
    target_cover_bp: int
    horizon_days: int


class FxPolicyView(BaseModel):
    policy_id: str
    as_of_date: str
    targets: list[FxPolicyTargetView]


class FxPolicyPatch(BaseModel):
    """Upsert a single currency's cover target."""

    currency: str
    target_cover_bp: int = Field(..., ge=0, le=10000)
    horizon_days: int = Field(180, ge=30, le=1095)


class FxPolicyPatchBatch(BaseModel):
    targets: list[FxPolicyPatch]


def _active_policy(session, tenant_id: str) -> InvestmentPolicy | None:
    return session.scalars(
        select(InvestmentPolicy)
        .where(InvestmentPolicy.tenant_id == tenant_id)
        .where(InvestmentPolicy.superseded_at.is_(None))
    ).one_or_none()


@router.get("/policy", response_model=FxPolicyView)
def get_fx_policy(ctx: Ctx, caller: Caller) -> FxPolicyView:
    """Current per-currency hedge policy targets.

    The row this reads and writes is `currency_cover_target` on the
    active investment policy version. In production a change would
    supersede the policy; the prototype mutates in place so a demo can
    show "raise USD from 75% to 90%, watch the gap grow" without a
    policy-versioning ceremony.
    """
    policy = _active_policy(ctx.session, ctx.tenant_id)
    if policy is None:
        raise TreasuryError(ErrorCode.NO_INVESTMENT_POLICY)
    rows = list(
        ctx.session.scalars(
            select(CurrencyCoverTarget).where(
                CurrencyCoverTarget.policy_id == policy.id
            )
        )
    )
    return FxPolicyView(
        policy_id=policy.id,
        as_of_date=ctx.as_of_date,
        targets=[
            FxPolicyTargetView(
                currency=r.currency,
                target_cover_bp=r.target_cover_bp,
                horizon_days=r.horizon_days,
            )
            for r in rows
        ],
    )


@router.put("/policy", response_model=FxPolicyView)
def put_fx_policy(
    body: FxPolicyPatchBatch, ctx: Ctx, caller: Caller
) -> FxPolicyView:
    """Update per-currency hedge policy targets in place.

    Any currency not in the patch keeps its current row. A new currency
    creates a new row. Zero is a valid target and means "no policy
    requires hedging this currency" — the panel then shows no gap arrow
    for it.
    """
    policy = _active_policy(ctx.session, ctx.tenant_id)
    if policy is None:
        raise TreasuryError(ErrorCode.NO_INVESTMENT_POLICY)

    for patch in body.targets:
        currency = patch.currency.upper()
        row = ctx.session.get(CurrencyCoverTarget, (policy.id, currency))
        if row is None:
            row = CurrencyCoverTarget(
                policy_id=policy.id,
                currency=currency,
                target_cover_bp=patch.target_cover_bp,
                horizon_days=patch.horizon_days,
            )
            ctx.session.add(row)
        else:
            row.target_cover_bp = patch.target_cover_bp
            row.horizon_days = patch.horizon_days
    ctx.session.commit()
    return get_fx_policy(ctx, caller)


@router.post("/narrate", response_model=FxBriefingView)
def narrate(ctx: Ctx, caller: Caller) -> FxBriefingView:
    """Cross-currency briefing + recommended actions + watch callouts.

    The read side of the AI-assist rule from spec §15. AI writes the
    prose and picks a counterparty from a deterministic whitelist; the
    system rejects any response that names a counterparty or amount not
    in the input. No rate prediction, ever.
    """
    briefing = narrate_fx(ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy)
    return FxBriefingView(
        briefing=briefing.briefing,
        recommendations=[
            FxRecommendationView(
                currency=r.currency,
                amount_minor=r.amount_minor,
                tenor_months=r.tenor_months,
                counterparty_id=r.counterparty_id,
                counterparty_name=r.counterparty_name,
                reason=r.reason,
            )
            for r in briefing.recommendations
        ],
        watch=briefing.watch,
    )


@router.get("/hedges", response_model=list[dict])
def list_hedges(ctx: Ctx, caller: Caller) -> list[dict]:
    """All live FX forwards for the tenant."""
    statement = (
        select(Deal, HedgeLink, Counterparty)
        .join(HedgeLink, HedgeLink.deal_id == Deal.id)
        .join(Counterparty, Counterparty.id == Deal.counterparty_id)
        .where(Deal.tenant_id == ctx.tenant_id)
        .where(Deal.instrument == "FX_FORWARD")
        .where(HedgeLink.unlinked_at.is_(None))
    )
    grouped: dict[str, dict] = {}
    for deal, link, cp in ctx.session.execute(statement):
        row = grouped.setdefault(
            deal.id,
            {
                "deal_id": deal.id,
                "counterparty_id": cp.id,
                "counterparty_name": cp.name,
                "currency": deal.currency,
                "principal_pence": deal.principal_pence,
                "tenor_months": deal.tenor_months,
                "trade_date": deal.trade_date,
                "maturity_date": deal.maturity_date,
                "status": deal.status,
                "covered_amount_minor": 0,
                "exposure_ids": [],
            },
        )
        row["covered_amount_minor"] += link.covered_amount_minor
        row["exposure_ids"].append(link.currency_exposure_id)
    return list(grouped.values())
