"""The contract.

Every shared response model in document 2 section 5, written before any
endpoint exists. This module is the interface between the backend and the
frontend workstreams, and it is treated as a document rather than as code:
changing a field here is a three way conversation, which is the single most
expensive thing that can happen to the schedule.

Money is integer pence, suffix _pence. Foreign currency is integer minor
units, suffix _minor, and never appears without a currency field beside it.
Rates are basis points. Nulls are explicit, never an omitted key.

The client formats. Nothing here is a formatted string except the human
readable messages, which are composed on the server with the money already
in the sentence.
"""

from typing import Literal

from pydantic import BaseModel, Field

Instrument = Literal["DEPOSIT", "FX_FORWARD", "MMF", "GILT"]
DealStatus = Literal["PROPOSED", "BLOCKED", "ACTIVE", "MATURED", "CLOSED", "CANCELLED"]
Enforcement = Literal["HARD_BLOCK", "WARN_WITH_OVERRIDE"]
ApproverRole = Literal["ANALYST", "HEAD_OF_TREASURY", "CFO"]
CheckKey = Literal[
    "COUNTERPARTY_ACTIVE",
    "INSTRUMENT_PERMITTED",
    "ENTITY_LIMIT",
    "GROUP_LIMIT",
    "TENOR_BAND",
    "CONCENTRATION",
]


# --------------------------------------------------------------------------
# The error body
# --------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None


class ErrorBody(BaseModel):
    error: ErrorDetail


# --------------------------------------------------------------------------
# Policy and reference data
# --------------------------------------------------------------------------


class RatingBandView(BaseModel):
    rating: str
    ordinal: int
    max_limit_pence: int
    max_tenor_months: int


class PolicyConfig(BaseModel):
    """The treasury policy version in force."""

    id: str
    effective_from: str
    concentration_cap_bp: int
    threshold_analyst_pence: int
    threshold_hot_pence: int
    enforcement: Enforcement
    fx_add_on_bp: int
    approved_by: str


class LimitVersion(BaseModel):
    id: str
    counterparty_id: str
    amount_pence: int
    max_tenor_months: int
    source: Literal["BAND", "MANUAL"]
    effective_from: str
    superseded_at: str | None = None
    reason: str | None = None
    approved_by: str


# --------------------------------------------------------------------------
# The six checks
# --------------------------------------------------------------------------


class CheckOutcome(BaseModel):
    """One of the six checks, and the arithmetic behind it.

    detail states the figures rather than the verdict. Group limit exceeded
    tells a user nothing; naming the amount, the other holdings in the group
    and the ceiling tells them what to do next.

    resize_to_pence is present only on a failure that a smaller amount would
    clear. The interface offers it as a control and never computes it, because
    computing it in the browser is a second implementation of the limit
    arithmetic.
    """

    key: CheckKey
    name: str
    passed: bool
    detail: str
    workings: list[str] = Field(default_factory=list)
    resize_to_pence: int | None = None


class CheckResult(BaseModel):
    """The result of one run of the six checks. Written by the check endpoint
    to nothing at all, and by the create endpoint to a check_run row."""

    check_run_id: str | None = None
    as_of_date: str
    counterparty_id: str
    outcome: Literal["PASS", "FAIL", "OVERRIDDEN"]
    checks: list[CheckOutcome]
    failed_count: int
    measured_pence: int | None = None
    measurement_basis: str | None = None
    required_approver: ApproverRole | None = None
    enforcement: Enforcement
    verdict: str
    limit_id: str | None = None
    policy_version_id: str


# --------------------------------------------------------------------------
# The book and the blotter
# --------------------------------------------------------------------------


class BookRow(BaseModel):
    """One counterparty as the book shows it.

    group_used_pence and group_limit_pence sit on the row because a name that
    looks free at entity level can still be constrained by its group, and the
    row is the only place a reader would see both.
    """

    counterparty_id: str
    name: str
    group_id: str
    group_name: str
    rating: str
    rating_status: str
    status: str
    limit_pence: int | None = None
    limit_id: str | None = None
    max_tenor_months: int | None = None
    used_pence: int
    headroom_pence: int | None = None
    utilisation_bp: int | None = None
    group_used_pence: int
    group_limit_pence: int
    group_utilisation_bp: int
    instruments: list[Instrument]
    has_open_breach: bool


class DealSummary(BaseModel):
    """One deal as the blotter shows it.

    measured_pence and measurement_basis travel together, so a forward is
    never read as its notional. stage and flag are computed labels: flag is
    null on a healthy deal, so a pill on a row always means something.
    """

    id: str
    counterparty_id: str
    counterparty_name: str
    instrument: Instrument
    principal_pence: int
    currency: str
    rate_bp: int
    tenor_months: int
    trade_date: str
    value_date: str
    maturity_date: str | None = None
    status: DealStatus
    capture_source: Literal["KEYED", "FROM_CONFIRMATION"]
    measured_pence: int
    measurement_basis: str
    stage: str
    flag: Literal["mismatch", "breach", "amended"] | None = None
    approved_by: str | None = None
    required_approver: ApproverRole | None = None
    accrual_today_pence: int | None = None
    accrual_cumulative_pence: int | None = None


# --------------------------------------------------------------------------
# The queue, breaches and evidence
# --------------------------------------------------------------------------


class QueueItem(BaseModel):
    """One queue, two causes, told apart by cause and reason_code."""

    id: str
    cause: Literal["LIMIT_FAILURE", "CONFIRMATION_MISMATCH"]
    reason_code: str
    detail: str
    deal_id: str | None = None
    confirmation_id: str | None = None
    counterparty_id: str
    counterparty_name: str
    status: Literal["OPEN", "RESOLVED"]
    resolution: str | None = None
    raised_at: str
    differences: list["MatchDifference"] = Field(default_factory=list)


class BreachView(BaseModel):
    """A position that was compliant when booked and is not compliant now.

    Responding records a decision. It does not clear the breach.
    """

    id: str
    counterparty_id: str
    counterparty_name: str
    deal_id: str | None = None
    type: Literal["AMOUNT", "TENOR", "GROUP", "CONCENTRATION", "RATING"]
    detail: str
    status: Literal["OPEN", "RESPONDED"]
    response: str | None = None
    response_reason: str | None = None
    original_check_run_id: str | None = None
    raised_at: str


# --------------------------------------------------------------------------
# Exposure. Two endpoints, never one.
# --------------------------------------------------------------------------


class UtilisationRow(BaseModel):
    key: str
    label: str
    used_pence: int
    limit_pence: int | None = None
    utilisation_bp: int | None = None


class ExposureView(BaseModel):
    """Counterparty exposure. Pence. Recomputed on every call by design."""

    as_of_date: str
    portfolio_total_pence: int
    uninvested_cash_pence: int
    by_group: list[UtilisationRow]
    by_rating_band: list[UtilisationRow]
    by_maturity_bucket: list[UtilisationRow]


class CurrencyBucket(BaseModel):
    bucket: str
    net_minor: int
    covered_minor: int
    target_cover_bp: int
    covered_bp: int


class HedgeLinkView(BaseModel):
    id: str
    deal_id: str
    covered_amount_minor: int
    currency: str
    linked_at: str
    unlinked_at: str | None = None
    unlink_reason: str | None = None


class CurrencyExposureRow(BaseModel):
    id: str
    currency: str
    amount_minor: int
    direction: Literal["PAYABLE", "RECEIVABLE"]
    expected_date: str
    source: str
    source_reference: str | None = None
    status: Literal["IDENTIFIED", "PARTIALLY_COVERED", "COVERED", "SETTLED"]
    hedges: list[HedgeLinkView] = Field(default_factory=list)


class CurrencyExposureView(BaseModel):
    """Currency exposure. Minor units, with a currency on every figure.

    A separate endpoint from counterparty exposure, and never joined to it.
    A forward increases one and reduces the other, so a combined figure would
    be meaningless in the best case and misleading in the worst.
    """

    as_of_date: str
    currency: str
    buckets: list[CurrencyBucket]
    exposures: list[CurrencyExposureRow]
    warning: str = (
        "Counterparty exposure and currency exposure are separate figures "
        "moving in opposite directions. They are never netted."
    )


# --------------------------------------------------------------------------
# The deal lifecycle
# --------------------------------------------------------------------------


class TimelineEvent(BaseModel):
    """One event on the deal timeline.

    Future events are computed from the maturity date rather than stored, so
    a live deal still shows what will happen to it.
    """

    key: str
    title: str
    detail: str
    occurred_at: str | None = None
    source: Literal["PLATFORM", "OUTSIDE", "ORACLE"]
    state: Literal["DONE", "WARN", "FUTURE"]


class MatchDifference(BaseModel):
    """One disagreeing field. Both values as strings, because this object
    exists to be displayed rather than computed on."""

    field_name: str
    keyed_value: str
    confirmed_value: str


class ConfirmationSummary(BaseModel):
    id: str
    deal_id: str | None = None
    counterparty_id: str | None = None
    message_type: str
    reference: str
    received_at: str
    match_status: Literal["UNMATCHED", "MATCHED", "MISMATCHED", "DISPUTED"]
    differences: list[MatchDifference] = Field(default_factory=list)


class AccrualRow(BaseModel):
    id: str
    accrual_date: str
    day_count: int
    rate_bp: int
    amount_pence: int
    cumulative_pence: int
    reversal_of: str | None = None
    amendment_id: str | None = None


class JournalSummary(BaseModel):
    period: str
    status: Literal["BUILT", "POSTED", "FAILED"]
    count: int
    amount_pence: int
    oracle_reference: str | None = None


class SettlementView(BaseModel):
    id: str
    expected_principal_pence: int
    expected_interest_pence: int
    confirmed_amount_pence: int | None = None
    statement_amount_pence: int | None = None
    match_status: Literal["PENDING", "AGREED", "BREAK"]
    break_detail: str | None = None
    closed_at: str | None = None


class AmendmentView(BaseModel):
    id: str
    type: Literal["BREAK", "ROLL", "PARTIAL_DRAWDOWN", "CORRECTION"]
    effective_date: str
    new_principal_pence: int | None = None
    new_rate_bp: int | None = None
    new_maturity_date: str | None = None
    reason: str
    status: Literal["RAISED", "APPLIED", "REJECTED"]
    raised_by: str
    raised_at: str
    applied_at: str | None = None


class DealDetail(BaseModel):
    """Everything the deal panel needs, in one object.

    One click, one panel, one call. Assembling this on the client would be a
    waterfall of six requests and six loading states.
    """

    deal: DealSummary
    timeline: list[TimelineEvent]
    run: CheckResult | None = None
    limit: LimitVersion | None = None
    confirmation: ConfirmationSummary | None = None
    accruals: list[AccrualRow] = Field(default_factory=list)
    journals: list[JournalSummary] = Field(default_factory=list)
    settlement: SettlementView | None = None
    amendments: list[AmendmentView] = Field(default_factory=list)
    breaches: list[BreachView] = Field(default_factory=list)


# --------------------------------------------------------------------------
# The advisory layer
# --------------------------------------------------------------------------


class Candidate(BaseModel):
    """An option the rules produced, priced.

    Excluded candidates are kept and returned, because why was this one not
    picked is the question that gets asked, and the exclusion is the guardrail
    rather than the ranking.
    """

    id: str
    counterparty_id: str
    counterparty_name: str
    instrument: Instrument
    amount_pence: int
    tenor_months: int
    indicative_rate_bp: int
    score_bp: int
    excluded: bool
    exclusion_reason: str | None = None
    rank: int | None = None


class ValidationResult(BaseModel):
    test: Literal["ID_IS_REAL", "CHECKS_RERUN_CLEAN", "FIGURES_AGREE"]
    passed: bool
    detail: str | None = None


class AdvisoryTicket(BaseModel):
    """What the deal form loads when a recommendation is accepted.

    Five fields, the same five a person would type. There is no sixth field
    carrying a result the checks would then trust.
    """

    counterparty_id: str
    instrument: Instrument
    principal_pence: int
    tenor_months: int
    rate_bp: int


class AdvisoryCard(BaseModel):
    """The recommendation as the ticket shows it.

    source is on the card and on the screen. A pick the model could not
    explain is still a pick, flagged RULE_FALLBACK, with only the explanation
    lost.
    """

    run_id: str
    as_of: str
    gap_type: Literal[
        "CASH_SURPLUS", "CASH_SHORTFALL", "LADDER_GAP", "CURRENCY_UNCOVERED", "NONE"
    ]
    gap_amount_minor: int | None = None
    gap_currency: str | None = None
    gap_date: str | None = None
    recommendation_id: str | None = None
    headline: str
    rationale: str | None = None
    source: Literal["MODEL", "RULE_FALLBACK"]
    alternatives: list[str] = Field(default_factory=list)
    ticket: AdvisoryTicket | None = None


class AdvisoryRun(BaseModel):
    card: AdvisoryCard
    candidates: list[Candidate]
    validation: list[ValidationResult]
    outcome: Literal["NO_GAP", "MODEL_ACCEPTED", "MODEL_REJECTED_FALLBACK", "RULE_ONLY"]
    model_enabled: bool
    model_name: str | None = None
    started_at: str
    finished_at: str | None = None


# --------------------------------------------------------------------------
# The one state call
# --------------------------------------------------------------------------


class QueueCounts(BaseModel):
    """Split by cause, because one queue with two causes still has to say
    which kind of work is waiting."""

    total: int
    limit_failures: int
    confirmation_mismatches: int


class StateResponse(BaseModel):
    """Everything the surface needs, from one transaction.

    No waterfall and no eleven loading states, and every figure on screen
    agrees with every other because they came from one read.
    """

    as_of_date: str
    tenant_name: str
    enforcement: Enforcement
    policy: PolicyConfig
    rating_bands: list[RatingBandView]
    book: list[BookRow]
    deals: list[DealSummary]
    queue_counts: QueueCounts
    breach_count: int
    advisory: AdvisoryCard | None = None
    #: The most recent run, whether or not it left a recommendation
    #: outstanding. The card goes when somebody decides; the run is still
    #: the evidence of what was considered, so the strip has to be able to
    #: reach it.
    advisory_run_id: str | None = None
    uninvested_cash_pence: int
    portfolio_total_pence: int


QueueItem.model_rebuild()
