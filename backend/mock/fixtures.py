"""Fixtures, built from the seed.

Not hand written JSON. Every figure here is derived from app.seed_data using
app.measurement, which is the same module the real ExposureCalculator will
call. That is what stops the mock and the real API disagreeing about a
number, and it is why the contract tests in phase one can compare the two
shape for shape.

What is NOT here is any rule. The mock does not run the six checks. It holds
two prepared CheckResult fixtures, one passing and one failing on the group
limit, and picks between them. The one comparison that picks is marked, and
it goes when the group 2 routers replace the mock.
"""

from datetime import date

from app import seed_data as s
from app.formatting import per_cent, sterling
from app.measurement import measure_deal
from app.schemas.models import (
    AdvisoryCard,
    AdvisoryRun,
    AdvisoryTicket,
    BookRow,
    BreachView,
    Candidate,
    CheckOutcome,
    CheckResult,
    CurrencyBucket,
    CurrencyExposureRow,
    CurrencyExposureView,
    DealDetail,
    DealSummary,
    ExposureView,
    HedgeLinkView,
    LimitVersion,
    PolicyConfig,
    QueueCounts,
    QueueItem,
    RatingBandView,
    StateResponse,
    TimelineEvent,
    UtilisationRow,
    ValidationResult,
)

POLICY = s.POLICY_VERSION
FX_ADD_ON_BP = POLICY["fx_add_on_bp"]

CP_BY_ID = {c["id"]: c for c in s.COUNTERPARTIES}
GROUP_BY_ID = {g[0]: {"id": g[0], "name": g[1], "limit_pence": g[2]} for g in s.CP_GROUPS}
LIMIT_BY_CP = {limit["counterparty_id"]: limit for limit in s.CP_LIMITS}
BAND_BY_RATING = {
    rating: {"ordinal": o, "max_limit_pence": lim, "max_tenor_months": ten}
    for _id, rating, o, lim, ten in s.RATING_BANDS
}


# --------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------


def measured(deal: dict, as_of: str = s.CLOCK_DATE):
    return measure_deal(
        instrument=deal["instrument"],
        principal_pence=deal["principal_pence"],
        rate_bp=deal["rate_bp"],
        value_date=deal["value_date"],
        as_of_date=as_of,
        fx_add_on_bp=FX_ADD_ON_BP,
    )


def used_by_counterparty() -> dict[str, int]:
    used: dict[str, int] = {c["id"]: 0 for c in s.COUNTERPARTIES}
    for deal in s.DEALS:
        if deal["status"] == "ACTIVE":
            used[deal["counterparty_id"]] += measured(deal).amount_pence
    return used


def used_by_group() -> dict[str, int]:
    used: dict[str, int] = {g["id"]: 0 for g in GROUP_BY_ID.values()}
    for cp_id, amount in used_by_counterparty().items():
        used[CP_BY_ID[cp_id]["group_id"]] += amount
    return used


def uninvested_cash_pence() -> int:
    return sum(b["balance_pence"] for b in s.ORACLE_BALANCES)


def portfolio_total_pence() -> int:
    """Active deals at their measure, plus the Oracle balance on the clock date.

    Cash counts. A concentration figure that ignores the money sitting in the
    operating account measures the wrong denominator.
    """
    return sum(used_by_counterparty().values()) + uninvested_cash_pence()


def _bp(part: int, whole: int | None) -> int | None:
    if not whole:
        return None
    return round(part * 10_000 / whole)


# --------------------------------------------------------------------------
# The book
# --------------------------------------------------------------------------


def book_rows() -> list[BookRow]:
    used_cp = used_by_counterparty()
    used_grp = used_by_group()
    rows = []
    for cp in s.COUNTERPARTIES:
        limit = LIMIT_BY_CP.get(cp["id"])
        group = GROUP_BY_ID[cp["group_id"]]
        used = used_cp[cp["id"]]
        rows.append(
            BookRow(
                counterparty_id=cp["id"],
                name=cp["name"],
                group_id=group["id"],
                group_name=group["name"],
                rating=cp["rating"],
                rating_status=cp["rating_status"],
                status=cp["status"],
                limit_pence=limit["amount_pence"] if limit else None,
                limit_id=limit["id"] if limit else None,
                max_tenor_months=limit["max_tenor_months"] if limit else None,
                used_pence=used,
                headroom_pence=(limit["amount_pence"] - used) if limit else None,
                utilisation_bp=_bp(used, limit["amount_pence"] if limit else None),
                group_used_pence=used_grp[group["id"]],
                group_limit_pence=group["limit_pence"],
                group_utilisation_bp=_bp(used_grp[group["id"]], group["limit_pence"]) or 0,
                instruments=cp["instruments"],
                has_open_breach=False,
            )
        )
    return rows


# --------------------------------------------------------------------------
# The blotter
# --------------------------------------------------------------------------


def _stage(deal: dict) -> str:
    """The lifecycle label. Computed, never stored.

    Phase one has no confirmation and no stored accrual, so a live deal reads
    as awaiting confirmation or as matures in n days. The accruing label
    arrives with phase two, and the label module is the only thing that
    changes when it does.
    """
    if deal["status"] == "BLOCKED":
        return "blocked"
    if deal["status"] == "CLOSED":
        return "closed"
    if not deal["maturity_date"]:
        return "open ended"
    days = (date.fromisoformat(deal["maturity_date"]) - date.fromisoformat(s.CLOCK_DATE)).days
    if days <= 0:
        return "matured"
    return f"matures in {days} days"


def deal_summaries() -> list[DealSummary]:
    out = []
    for deal in s.DEALS:
        m = measured(deal)
        out.append(
            DealSummary(
                id=deal["id"],
                counterparty_id=deal["counterparty_id"],
                counterparty_name=CP_BY_ID[deal["counterparty_id"]]["name"],
                instrument=deal["instrument"],
                principal_pence=deal["principal_pence"],
                currency=deal["currency"],
                rate_bp=deal["rate_bp"],
                tenor_months=deal["tenor_months"],
                trade_date=deal["trade_date"],
                value_date=deal["value_date"],
                maturity_date=deal["maturity_date"],
                status=deal["status"],
                capture_source=deal["capture_source"],
                measured_pence=m.amount_pence,
                measurement_basis=m.basis,
                stage=_stage(deal),
                flag=None,
                approved_by=deal["approved_by"],
                required_approver=deal["required_approver"],
            )
        )
    return out


# --------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------


def policy_config() -> PolicyConfig:
    return PolicyConfig(
        id=POLICY["id"],
        effective_from=POLICY["effective_from"],
        concentration_cap_bp=POLICY["concentration_cap_bp"],
        threshold_analyst_pence=POLICY["threshold_analyst_pence"],
        threshold_hot_pence=POLICY["threshold_hot_pence"],
        enforcement=POLICY["enforcement"],
        fx_add_on_bp=POLICY["fx_add_on_bp"],
        approved_by=POLICY["approved_by"],
    )


def rating_bands() -> list[RatingBandView]:
    return [
        RatingBandView(
            rating=rating, ordinal=o, max_limit_pence=lim, max_tenor_months=ten
        )
        for _id, rating, o, lim, ten in s.RATING_BANDS
    ]


def limit_version(counterparty_id: str) -> LimitVersion | None:
    limit = LIMIT_BY_CP.get(counterparty_id)
    if not limit:
        return None
    return LimitVersion(
        id=limit["id"],
        counterparty_id=counterparty_id,
        amount_pence=limit["amount_pence"],
        max_tenor_months=limit["max_tenor_months"],
        source=limit["source"],
        effective_from=limit["effective_from"],
        superseded_at=None,
        reason=limit["reason"],
        approved_by=limit["approved_by"],
    )


def required_approver(principal_pence: int) -> str:
    """Read from the policy version in force, never from a constant."""
    if principal_pence <= POLICY["threshold_analyst_pence"]:
        return "ANALYST"
    if principal_pence <= POLICY["threshold_hot_pence"]:
        return "HEAD_OF_TREASURY"
    return "CFO"


# --------------------------------------------------------------------------
# The six checks, as two prepared fixtures
# --------------------------------------------------------------------------

CHECK_NAMES = {
    "COUNTERPARTY_ACTIVE": "Counterparty approved and active",
    "INSTRUMENT_PERMITTED": "Instrument permitted",
    "ENTITY_LIMIT": "Entity limit",
    "GROUP_LIMIT": "Group limit",
    "TENOR_BAND": "Term inside the rating band",
    "CONCENTRATION": "Concentration cap",
}


def _passing_checks(
    counterparty_id: str, instrument: str, principal_pence: int, tenor_months: int
) -> list[CheckOutcome]:
    cp = CP_BY_ID[counterparty_id]
    limit = LIMIT_BY_CP[counterparty_id]
    group = GROUP_BY_ID[cp["group_id"]]
    used = used_by_counterparty()[counterparty_id]
    group_used = used_by_group()[group["id"]]
    band = BAND_BY_RATING[cp["rating"]]
    total = portfolio_total_pence() + principal_pence
    group_after = group_used + principal_pence
    return [
        CheckOutcome(
            key="COUNTERPARTY_ACTIVE",
            name=CHECK_NAMES["COUNTERPARTY_ACTIVE"],
            passed=True,
            detail=f"{cp['name']} is active, rated {cp['rating']}.",
        ),
        CheckOutcome(
            key="INSTRUMENT_PERMITTED",
            name=CHECK_NAMES["INSTRUMENT_PERMITTED"],
            passed=True,
            detail=f"{instrument.replace('_', ' ').title()} is approved for this name.",
        ),
        CheckOutcome(
            key="ENTITY_LIMIT",
            name=CHECK_NAMES["ENTITY_LIMIT"],
            passed=True,
            detail=(
                f"{cp['name']} would reach {sterling(used + principal_pence)} "
                f"against a limit of {sterling(limit['amount_pence'])}."
            ),
            workings=[f"Already held {sterling(used)}."],
        ),
        CheckOutcome(
            key="GROUP_LIMIT",
            name=CHECK_NAMES["GROUP_LIMIT"],
            passed=True,
            detail=(
                f"{group['name']} would reach {sterling(group_after)} against a "
                f"group limit of {sterling(group['limit_pence'])}."
            ),
            workings=[f"Same credit already holds {sterling(group_used)}."],
        ),
        CheckOutcome(
            key="TENOR_BAND",
            name=CHECK_NAMES["TENOR_BAND"],
            passed=True,
            detail=(
                f"{tenor_months} months, inside the {limit['max_tenor_months']} "
                f"month maximum in force at {cp['rating']}."
            ),
        ),
        CheckOutcome(
            key="CONCENTRATION",
            name=CHECK_NAMES["CONCENTRATION"],
            passed=True,
            detail=(
                f"{group['name']} would hold {per_cent(_bp(group_after, total) or 0)} "
                f"of a portfolio of {sterling(total)}, against a cap of "
                f"{per_cent(POLICY['concentration_cap_bp'])}."
            ),
            workings=[f"Portfolio includes {sterling(uninvested_cash_pence())} uninvested."],
        ),
    ]


def _group_failure(
    counterparty_id: str, instrument: str, principal_pence: int, tenor_months: int
) -> list[CheckOutcome]:
    """The screen 2 fixture. Five green, one red, and a route forward."""
    checks = _passing_checks(counterparty_id, instrument, principal_pence, tenor_months)
    cp = CP_BY_ID[counterparty_id]
    group = GROUP_BY_ID[cp["group_id"]]
    group_used = used_by_group()[group["id"]]
    headroom = group["limit_pence"] - group_used
    others = [
        f"{CP_BY_ID[d['counterparty_id']]['name']} {sterling(measured(d).amount_pence)}"
        for d in s.DEALS
        if d["status"] == "ACTIVE"
        and CP_BY_ID[d["counterparty_id"]]["group_id"] == group["id"]
    ]
    for check in checks:
        if check.key == "GROUP_LIMIT":
            check.passed = False
            check.detail = (
                f"{group['name']} would reach {sterling(group_used + principal_pence)} "
                f"against a group limit of {sterling(group['limit_pence'])}."
            )
            check.workings = [f"Same credit: {name}." for name in others]
            check.resize_to_pence = headroom
    return checks


def check_result(
    counterparty_id: str,
    instrument: str,
    principal_pence: int,
    tenor_months: int,
    as_of: str = s.CLOCK_DATE,
) -> CheckResult:
    """Pick a fixture. This is not the rule engine and never becomes it.

    The single comparison below decides which prepared fixture to hand back so
    the check panel can be seen in both states before any backend exists. It
    is deleted the day the group 2 routers replace the mock, and the frontend
    that consumed it does not change, because the shape is identical.
    """
    cp = CP_BY_ID[counterparty_id]
    group = GROUP_BY_ID[cp["group_id"]]
    group_headroom = group["limit_pence"] - used_by_group()[group["id"]]

    if principal_pence > group_headroom:  # fixture selection, not a check
        checks = _group_failure(counterparty_id, instrument, principal_pence, tenor_months)
    else:
        checks = _passing_checks(counterparty_id, instrument, principal_pence, tenor_months)

    failed = [c for c in checks if not c.passed]
    m = measure_deal(
        instrument=instrument,
        principal_pence=principal_pence,
        rate_bp=0,
        value_date=as_of,
        as_of_date=as_of,
        fx_add_on_bp=FX_ADD_ON_BP,
    )
    approver = required_approver(principal_pence)
    if failed:
        verdict = (
            f"{len(failed)} of six checks failed. The policy in force is "
            f"{'a hard block' if POLICY['enforcement'] == 'HARD_BLOCK' else 'warn with an override'}."
        )
    else:
        verdict = (
            f"Measured at {sterling(m.amount_pence)}, {m.basis}. "
            f"{'The Head of Treasury' if approver == 'HEAD_OF_TREASURY' else approver.title()} "
            f"has to sign."
        )
    return CheckResult(
        check_run_id=None,
        as_of_date=as_of,
        counterparty_id=counterparty_id,
        outcome="FAIL" if failed else "PASS",
        checks=checks,
        failed_count=len(failed),
        measured_pence=m.amount_pence,
        measurement_basis=m.basis,
        required_approver=None if failed else approver,
        enforcement=POLICY["enforcement"],
        verdict=verdict,
        limit_id=LIMIT_BY_CP[counterparty_id]["id"],
        policy_version_id=POLICY["id"],
    )


# --------------------------------------------------------------------------
# The advisory card
# --------------------------------------------------------------------------


def advisory_card() -> AdvisoryCard:
    gap = s.EXPECTED["advisory_gap_pence"]
    return AdvisoryCard(
        run_id="adv_run_001",
        as_of=s.CLOCK_DATE,
        gap_type="CASH_SURPLUS",
        gap_amount_minor=gap,
        gap_currency="GBP",
        gap_date=s.CLOCK_DATE,
        recommendation_id="rec_001",
        headline=(
            f"{sterling(gap)} lands uninvested today and the three to six month "
            f"bucket is empty."
        ),
        rationale=(
            "Meridian Bank plc at A+ takes the whole amount inside its own limit "
            "and its group limit, and a six month term fills the empty bucket "
            "without breaching the twelve month maximum in force."
        ),
        source="MODEL",
        alternatives=[
            "Caledonia Trust Bank, ranked second on yield, would push the "
            "Caledonia group past 30 per cent of the portfolio.",
            "Harbour and Vale Bank was excluded before ranking, because three "
            "months is its ceiling at BBB+ and the gap runs longer.",
        ],
        ticket=AdvisoryTicket(
            counterparty_id="cp_meridian",
            instrument="DEPOSIT",
            principal_pence=gap,
            tenor_months=6,
            rate_bp=428,
        ),
    )


def advisory_run() -> AdvisoryRun:
    gap = s.EXPECTED["advisory_gap_pence"]
    return AdvisoryRun(
        card=advisory_card(),
        candidates=[
            Candidate(
                id="cand_001",
                counterparty_id="cp_meridian",
                counterparty_name="Meridian Bank plc",
                instrument="DEPOSIT",
                amount_pence=gap,
                tenor_months=6,
                indicative_rate_bp=428,
                score_bp=8120,
                excluded=False,
                rank=1,
            ),
            Candidate(
                id="cand_002",
                counterparty_id="cp_caledonia",
                counterparty_name="Caledonia Trust Bank",
                instrument="DEPOSIT",
                amount_pence=gap,
                tenor_months=6,
                indicative_rate_bp=433,
                score_bp=7740,
                excluded=False,
                rank=2,
            ),
            Candidate(
                id="cand_003",
                counterparty_id="cp_northern",
                counterparty_name="Northern Bank plc",
                instrument="DEPOSIT",
                amount_pence=gap,
                tenor_months=6,
                indicative_rate_bp=421,
                score_bp=6980,
                excluded=False,
                rank=3,
            ),
            Candidate(
                id="cand_004",
                counterparty_id="cp_harbour",
                counterparty_name="Harbour and Vale Bank",
                instrument="DEPOSIT",
                amount_pence=gap,
                tenor_months=6,
                indicative_rate_bp=452,
                score_bp=0,
                excluded=True,
                exclusion_reason=(
                    "Excluded before ranking, because three months is its ceiling "
                    "at BBB+ and the gap runs longer."
                ),
                rank=None,
            ),
        ],
        validation=[
            ValidationResult(test="ID_IS_REAL", passed=True, detail="cand_001 is a row in this run."),
            ValidationResult(
                test="CHECKS_RERUN_CLEAN", passed=True, detail="Six of six passed."
            ),
            ValidationResult(
                test="FIGURES_AGREE",
                passed=True,
                detail="Every figure in the prose matches one computed at stage 3.",
            ),
        ],
        outcome="MODEL_ACCEPTED",
        model_enabled=True,
        model_name="ranker-v1",
        started_at=f"{s.CLOCK_DATE}T02:00:00+00:00",
        finished_at=f"{s.CLOCK_DATE}T02:00:11+00:00",
    )


# --------------------------------------------------------------------------
# Exposure
# --------------------------------------------------------------------------


def exposure_counterparty() -> ExposureView:
    used_grp = used_by_group()
    total = portfolio_total_pence()
    by_group = [
        UtilisationRow(
            key=g["id"],
            label=g["name"],
            used_pence=used_grp[g["id"]],
            limit_pence=g["limit_pence"],
            utilisation_bp=_bp(used_grp[g["id"]], g["limit_pence"]),
        )
        for g in GROUP_BY_ID.values()
    ]
    by_band: dict[str, int] = {}
    for cp_id, amount in used_by_counterparty().items():
        by_band[CP_BY_ID[cp_id]["rating"]] = by_band.get(CP_BY_ID[cp_id]["rating"], 0) + amount
    by_bucket: dict[str, int] = {"0_3M": 0, "3_6M": 0, "6_12M": 0, "OVER_12M": 0}
    for deal in s.DEALS:
        if deal["status"] != "ACTIVE":
            continue
        if not deal["maturity_date"]:
            by_bucket["OVER_12M"] += measured(deal).amount_pence
            continue
        days = (
            date.fromisoformat(deal["maturity_date"]) - date.fromisoformat(s.CLOCK_DATE)
        ).days
        bucket = (
            "0_3M" if days <= 92 else "3_6M" if days <= 183 else "6_12M" if days <= 365 else "OVER_12M"
        )
        by_bucket[bucket] += measured(deal).amount_pence
    return ExposureView(
        as_of_date=s.CLOCK_DATE,
        portfolio_total_pence=total,
        uninvested_cash_pence=uninvested_cash_pence(),
        by_group=by_group,
        by_rating_band=[
            UtilisationRow(key=r, label=r, used_pence=v, utilisation_bp=_bp(v, total))
            for r, v in sorted(by_band.items())
            if v
        ],
        by_maturity_bucket=[
            UtilisationRow(key=k, label=k.replace("_", " to ").replace("OVER to", "over"), used_pence=v, utilisation_bp=_bp(v, total))
            for k, v in by_bucket.items()
        ],
    )


def exposure_currency() -> CurrencyExposureView:
    """Illustrative. The currency register is phase three; this is the shape
    the frontend builds the second tab against."""
    return CurrencyExposureView(
        as_of_date=s.CLOCK_DATE,
        currency="EUR",
        buckets=[
            CurrencyBucket(bucket="0_3M", net_minor=180_000_000, covered_minor=150_000_000, target_cover_bp=8000, covered_bp=8333),
            CurrencyBucket(bucket="3_6M", net_minor=400_000_000, covered_minor=300_000_000, target_cover_bp=8000, covered_bp=7500),
            CurrencyBucket(bucket="6_12M", net_minor=120_000_000, covered_minor=0, target_cover_bp=5000, covered_bp=0),
        ],
        exposures=[
            CurrencyExposureRow(
                id="cxp_001",
                currency="EUR",
                amount_minor=400_000_000,
                direction="PAYABLE",
                expected_date=s.months_after(s.CLOCK_DATE, 5),
                source="PURCHASE_ORDER",
                source_reference="PO-2026-4471",
                status="PARTIALLY_COVERED",
                hedges=[
                    HedgeLinkView(
                        id="hl_001",
                        deal_id="dl_har_001",
                        covered_amount_minor=300_000_000,
                        currency="EUR",
                        linked_at=f"{s.days_ago(30)}T10:12:00+00:00",
                    )
                ],
            )
        ],
    )


# --------------------------------------------------------------------------
# The queue, breaches and the deal panel
# --------------------------------------------------------------------------


def queue_items() -> list[QueueItem]:
    """Nothing open. A blocked deal or a confirmation mismatch lands here."""
    return []


def breaches() -> list[BreachView]:
    """Nothing flagged. A breach appears when a rating action makes an
    existing position fall outside a revised limit."""
    return []


def deal_detail(deal_id: str) -> DealDetail | None:
    deal = next((d for d in s.DEALS if d["id"] == deal_id), None)
    if deal is None:
        return None
    summary = next(d for d in deal_summaries() if d.id == deal_id)
    return DealDetail(
        deal=summary,
        timeline=_timeline(deal),
        run=None,
        limit=limit_version(deal["counterparty_id"]),
        confirmation=None,
        accruals=[],
        journals=[],
        settlement=None,
        amendments=[],
        breaches=[],
    )


def _timeline(deal: dict) -> list[TimelineEvent]:
    cp = CP_BY_ID[deal["counterparty_id"]]
    events = [
        TimelineEvent(
            key="executed",
            title="Deal executed",
            detail=f"{cp['name']}, {per_cent(deal['rate_bp'])}, {deal['tenor_months']} months.",
            occurred_at=deal["trade_date"],
            source="OUTSIDE",
            state="DONE",
        ),
        TimelineEvent(
            key="captured",
            title="Deal captured",
            detail=f"Keyed, {sterling(deal['principal_pence'])} principal.",
            occurred_at=deal["trade_date"],
            source="PLATFORM",
            state="DONE",
        ),
        TimelineEvent(
            key="approved",
            title="Approved",
            detail=f"Signed by {deal['approved_by']}.",
            occurred_at=deal["trade_date"],
            source="PLATFORM",
            state="DONE",
        ),
        TimelineEvent(
            key="instructed",
            title="Payment instructed",
            detail="Handed to Oracle Fusion Payments.",
            occurred_at=deal["value_date"],
            source="ORACLE",
            state="DONE",
        ),
    ]
    if deal["maturity_date"]:
        events.append(
            TimelineEvent(
                key="maturity",
                title="Maturity due",
                detail=(
                    f"Expected {sterling(deal['principal_pence'])} principal plus "
                    f"interest."
                ),
                occurred_at=deal["maturity_date"],
                source="PLATFORM",
                state="FUTURE",
            )
        )
        events.append(
            TimelineEvent(
                key="closed",
                title="Deal closed",
                detail="Headroom returns to the book only when three sources agree.",
                occurred_at=None,
                source="PLATFORM",
                state="FUTURE",
            )
        )
    return events


# --------------------------------------------------------------------------
# The one state call
# --------------------------------------------------------------------------


def state() -> StateResponse:
    return StateResponse(
        as_of_date=s.CLOCK_DATE,
        tenant_name=s.TENANT_NAME,
        enforcement=POLICY["enforcement"],
        policy=policy_config(),
        rating_bands=rating_bands(),
        book=book_rows(),
        deals=deal_summaries(),
        queue_counts=QueueCounts(total=0, limit_failures=0, confirmation_mismatches=0),
        breach_count=0,
        advisory=advisory_card(),
        uninvested_cash_pence=uninvested_cash_pence(),
        portfolio_total_pence=portfolio_total_pence(),
    )
