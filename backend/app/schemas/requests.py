"""Request bodies.

Shape validation only. Pydantic refuses a malformed request and the handler
reshapes its 422 into the standard error body. Nothing here decides anything:
a body that is well formed and still not allowed is a service's refusal, not
a validation error.

No write body carries an actor. Phase 1.5 removed every one of them: the
caller comes from the bearer token and from nowhere else, so there is no
path by which a client can name somebody other than itself.

approved_by survives on SetLimitRequest alone, and it is not an actor. It
records who signed for a limit, which may be somebody other than whoever is
keying it, and a limit nobody signed is not a control. The caller is still
recorded separately as the person who made the change.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.models import ApproverRole, Instrument


class CheckRequest(BaseModel):
    """The five ticket fields. Nothing else is needed to test a deal."""

    counterparty_id: str
    instrument: Instrument
    principal_pence: int = Field(gt=0)
    tenor_months: int = Field(ge=1, le=60)
    rate_bp: int = Field(ge=0)
    as_of_date: str | None = None


class CreateDealRequest(CheckRequest):
    """Recording a deal.

    There is deliberately no field for a client supplied check result. The
    server re-runs the six checks as the control, and a browser cannot hand it
    a verdict to trust.
    """

    override_reason: str | None = None
    #: Set when the ticket was filled from a recommendation. The advisory
    #: layer never writes a deal; the deal endpoint writes back to the
    #: recommendation once the deal has passed the six checks, which is the
    #: only direction that edge runs in.
    recommendation_id: str | None = None


class ApproveDealRequest(BaseModel):
    """Signing a deal.

    No approver field. The signature is the caller, and the role they are
    signing under has to be one they actually hold.
    """

    role: ApproverRole


class InstructDealRequest(BaseModel):
    """Empty. The caller comes from the token."""


class CreateCounterpartyRequest(BaseModel):
    name: str
    group_id: str | None = None
    group_name: str | None = None


class VerifyCounterpartyRequest(BaseModel):
    legal_entity_identifier: str
    group_parent_name: str
    rating: str
    country: str
    instruments: list[Instrument]


class SetLimitRequest(BaseModel):
    amount_pence: int = Field(gt=0)
    max_tenor_months: int = Field(ge=1, le=60)
    approved_by: str
    reason: str | None = None


class ActivateCounterpartyRequest(BaseModel):
    """Empty. The caller comes from the token."""


class RatingActionRequest(BaseModel):
    """A rating action, and the re-test it causes.

    One call in, an unknown number of breaches out.
    """

    new_rating: str
    new_status: Literal["STABLE", "WATCH", "NEGATIVE", "POSITIVE"] = "STABLE"
    effective_date: str | None = None
    source: str = "Operator entered"


class ResolveQueueItemRequest(BaseModel):
    resolution: Literal[
        "RESIZED", "REROUTED", "OVERRIDDEN", "CANCELLED", "CORRECTED", "CHALLENGED"
    ]
    reason: str | None = None


class RespondToBreachRequest(BaseModel):
    response: Literal[
        "HOLD_TO_MATURITY", "BREAK_EARLY", "SEEK_RATIFICATION", "REDUCE_ON_ROLL"
    ]
    reason: str | None = None


class RaiseAmendmentRequest(BaseModel):
    type: Literal["BREAK", "ROLL", "PARTIAL_DRAWDOWN", "CORRECTION"]
    effective_date: str
    new_principal_pence: int | None = None
    new_rate_bp: int | None = None
    new_maturity_date: str | None = None
    reason: str


class IngestConfirmationRequest(BaseModel):
    message_type: Literal["MT300", "MT320", "MT535", "MT536", "BROKER_NOTE", "DOCUMENT"]
    reference: str
    counterparty_id: str | None = None
    instrument: Instrument
    principal_pence: int
    rate_bp: int
    value_date: str
    maturity_date: str | None = None
    raw_payload: str | None = None


class MatchConfirmationRequest(BaseModel):
    deal_id: str


class ApplyAmendmentRequest(BaseModel):
    """An amendment is re-tested before it is applied, so it needs the same
    override field a booking has."""

    override_reason: str | None = None


class SettleDealRequest(BaseModel):
    statement_line_id: str


class PostJournalsRequest(BaseModel):
    period: str


class StatementLineRequest(BaseModel):
    account_name: str
    amount_pence: int
    value_date: str
    reference: str | None = None


class InvestmentPolicyRequest(BaseModel):
    liquidity_buffer_pence: int
    buffer_horizon_days: int
    priority_order: str
    model_enabled: bool
    approved_by: str
    ladder_targets: list[dict]
    currency_cover_targets: list[dict]


class RunAdvisoryRequest(BaseModel):
    as_of: str | None = None
    force: bool = False


class DecideRecommendationRequest(BaseModel):
    decision: Literal["ACCEPTED", "EDITED", "REJECTED"]
    reason: str | None = None


class CreateCurrencyExposureRequest(BaseModel):
    currency: str
    amount_minor: int = Field(gt=0)
    direction: Literal["PAYABLE", "RECEIVABLE"]
    expected_date: str
    source: Literal["CONTRACT", "PURCHASE_ORDER", "INVOICE", "FORECAST"]
    source_reference: str | None = None


class LinkHedgeRequest(BaseModel):
    deal_id: str
    covered_amount_minor: int = Field(gt=0)


class UnlinkHedgeRequest(BaseModel):
    reason: Literal["ROLLED", "CLOSED_EARLY", "EXPOSURE_CANCELLED", "REALLOCATED"]


class NightlyJobRequest(BaseModel):
    as_of: str | None = None
    force: bool = False


class SetClockRequest(BaseModel):
    today_date: str


class SetEnforcementRequest(BaseModel):
    enforcement: Literal["HARD_BLOCK", "WARN_WITH_OVERRIDE"]


class SignInRequest(BaseModel):
    """The only body in the system that carries a credential."""

    email: str
    password: str
