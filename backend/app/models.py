"""SQLAlchemy declarative models.

The fifteen tables the phase one build needs, out of the thirty-three in
document 1. Document 1 section 2.1 lists them by subject area; the count of
eighteen quoted in its prose and in the execution plan does not reconcile
with that list, and the list wins. See docs/ASSUMPTIONS.md.

Conventions, from document 1 section 3.1:
  sterling money   integer pence, suffix _pence
  rates            integer basis points, suffix _bp
  business dates   ISO 8601 text, suffix _date
  timestamps       ISO 8601 text, suffix _at
  identifiers      prefixed text
  booleans         integer 0 or 1, with a check constraint

Nothing is deleted. Superseding a limit, resolving an exception and
responding to a breach are all writes.
"""

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _id() -> Mapped[str]:
    return mapped_column(String(40), primary_key=True)


def _tenant() -> Mapped[str]:
    return mapped_column(String(40), ForeignKey("tenant.id"), nullable=False, index=True)


# --------------------------------------------------------------------------
# Tenancy and policy
# --------------------------------------------------------------------------


class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[str] = _id()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[str] = mapped_column(String(30), nullable=False)


class SystemClock(Base):
    """Today, as the system believes it. Everything derives from this."""

    __tablename__ = "system_clock"

    tenant_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("tenant.id"), primary_key=True
    )
    today_date: Mapped[str] = mapped_column(String(10), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(30), nullable=False)


class PolicyVersion(Base):
    """The treasury policy in force. Versioned, never edited.

    A check run records which version it read, so a decision made last
    quarter re-derives against the rules that applied then rather than
    against the ones that apply now.
    """

    __tablename__ = "policy_version"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    effective_from: Mapped[str] = mapped_column(String(10), nullable=False)
    superseded_at: Mapped[str | None] = mapped_column(String(30))
    concentration_cap_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    threshold_analyst_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    threshold_hot_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    enforcement: Mapped[str] = mapped_column(String(24), nullable=False)
    fx_add_on_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_by: Mapped[str] = mapped_column(String(120), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "enforcement in ('HARD_BLOCK','WARN_WITH_OVERRIDE')",
            name="ck_policy_enforcement",
        ),
        # One current policy per tenant. Partial, so superseded rows may share
        # a tenant without fighting the index.
        Index(
            "ux_policy_current",
            "tenant_id",
            unique=True,
            sqlite_where=text("superseded_at IS NULL"),
        ),
    )


class RatingBand(Base):
    """What a rating entitles a counterparty to, before anyone signs anything.

    ordinal ascends with credit quality, so a downgrade is a fall.
    """

    __tablename__ = "rating_band"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    max_limit_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    max_tenor_months: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (UniqueConstraint("tenant_id", "rating", name="ux_rating_band"),)


# --------------------------------------------------------------------------
# Counterparty control
# --------------------------------------------------------------------------


class CpGroup(Base):
    """A credit group. The only thing that connects two legal entities."""

    __tablename__ = "cp_group"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    group_limit_pence: Mapped[int] = mapped_column(Integer, nullable=False)


class Counterparty(Base):
    __tablename__ = "counterparty"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    group_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("cp_group.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_entity_identifier: Mapped[str | None] = mapped_column(String(40))
    group_parent_name: Mapped[str | None] = mapped_column(String(200))
    country: Mapped[str | None] = mapped_column(String(2))
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    rating_status: Mapped[str] = mapped_column(String(12), nullable=False, default="STABLE")
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("app_user.id", name="fk_counterparty_created_by_user")
    )
    created_at: Mapped[str] = mapped_column(String(30), nullable=False)
    verified_by: Mapped[str | None] = mapped_column(String(120))
    verified_at: Mapped[str | None] = mapped_column(String(30))
    approved_by: Mapped[str | None] = mapped_column(String(120))
    approved_at: Mapped[str | None] = mapped_column(String(30))
    activated_by_user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("app_user.id", name="fk_counterparty_activated_by_user")
    )
    activated_at: Mapped[str | None] = mapped_column(String(30))

    __table_args__ = (
        CheckConstraint(
            "status in ('DRAFT','VERIFIED','APPROVED','ACTIVE','SUSPENDED')",
            name="ck_counterparty_status",
        ),
        CheckConstraint(
            "rating_status in ('STABLE','WATCH','NEGATIVE','POSITIVE')",
            name="ck_counterparty_rating_status",
        ),
    )


class CounterpartyInstrument(Base):
    """Which instruments this name is permitted to trade. Check two reads it."""

    __tablename__ = "counterparty_instrument"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    counterparty_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("counterparty.id"), nullable=False, index=True
    )
    instrument: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint(
            "instrument in ('DEPOSIT','FX_FORWARD','MMF','GILT')",
            name="ck_cp_instrument",
        ),
        CheckConstraint("enabled in (0,1)", name="ck_cp_instrument_enabled"),
        UniqueConstraint("counterparty_id", "instrument", name="ux_cp_instrument"),
    )


class CpLimit(Base):
    """A limit version. Superseded, never edited.

    source records whether the amount came from the rating band or was set by
    hand above or below it, because a manual limit above the band is the thing
    an auditor asks about first.
    """

    __tablename__ = "cp_limit"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    counterparty_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("counterparty.id"), nullable=False, index=True
    )
    amount_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    max_tenor_months: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(12), nullable=False)
    effective_from: Mapped[str] = mapped_column(String(10), nullable=False)
    superseded_at: Mapped[str | None] = mapped_column(String(30))
    superseded_by_event: Mapped[str | None] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str] = mapped_column(String(120), nullable=False)
    # Who signed, and who keyed it. They are not always the same person: an
    # approval can be given away from the screen and recorded afterwards.
    approved_by_user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("app_user.id", name="fk_cp_limit_approved_by_user")
    )
    recorded_by_user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("app_user.id", name="fk_cp_limit_recorded_by_user")
    )
    approved_at: Mapped[str] = mapped_column(String(30), nullable=False)

    __table_args__ = (
        CheckConstraint("source in ('BAND','MANUAL')", name="ck_limit_source"),
        # One current limit per counterparty.
        Index(
            "ux_limit_current",
            "counterparty_id",
            unique=True,
            sqlite_where=text("superseded_at IS NULL"),
        ),
    )


class RatingEvent(Base):
    """A rating action, and the re-test it caused."""

    __tablename__ = "rating_event"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    counterparty_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("counterparty.id"), nullable=False, index=True
    )
    previous_rating: Mapped[str] = mapped_column(String(8), nullable=False)
    new_rating: Mapped[str] = mapped_column(String(8), nullable=False)
    previous_status: Mapped[str] = mapped_column(String(12), nullable=False)
    new_status: Mapped[str] = mapped_column(String(12), nullable=False)
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    effective_date: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    policy_version_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("policy_version.id")
    )
    positions_tested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    breaches_raised: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recorded_by: Mapped[str] = mapped_column(String(120), nullable=False)
    recorded_by_user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("app_user.id", name="fk_rating_event_recorded_by_user")
    )
    recorded_at: Mapped[str] = mapped_column(String(30), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "action in ('UPGRADE','DOWNGRADE','WATCH','AFFIRM')", name="ck_rating_action"
        ),
    )


# --------------------------------------------------------------------------
# Dealing
# --------------------------------------------------------------------------


class Deal(Base):
    """What was placed, with whom, on what terms, and under which versions."""

    __tablename__ = "deal"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    counterparty_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("counterparty.id"), nullable=False, index=True
    )
    instrument: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    tenor_months: Mapped[int] = mapped_column(Integer, nullable=False)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False)
    value_date: Mapped[str] = mapped_column(String(10), nullable=False)
    maturity_date: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    capture_source: Mapped[str] = mapped_column(String(20), nullable=False, default="KEYED")
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    # Phase 1.5. The name stays for display; the identifier is what makes
    # the record evidence rather than a claim, and it is what the
    # segregation of duties comparison reads.
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("app_user.id", name="fk_deal_created_by_user")
    )
    created_at: Mapped[str] = mapped_column(String(30), nullable=False)
    required_approver: Mapped[str | None] = mapped_column(String(24))
    approved_by: Mapped[str | None] = mapped_column(String(120))
    approved_by_user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("app_user.id", name="fk_deal_approved_by_user")
    )
    approved_role: Mapped[str | None] = mapped_column(String(24))
    approved_at: Mapped[str | None] = mapped_column(String(30))
    limit_id_at_booking: Mapped[str | None] = mapped_column(String(40), ForeignKey("cp_limit.id"))
    policy_version_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("policy_version.id")
    )
    check_run_id: Mapped[str | None] = mapped_column(String(40))
    instructed_at: Mapped[str | None] = mapped_column(String(30))
    closed_at: Mapped[str | None] = mapped_column(String(30))

    __table_args__ = (
        CheckConstraint(
            "instrument in ('DEPOSIT','FX_FORWARD','MMF','GILT')", name="ck_deal_instrument"
        ),
        CheckConstraint(
            "status in ('PROPOSED','BLOCKED','ACTIVE','MATURED','CLOSED','CANCELLED')",
            name="ck_deal_status",
        ),
        CheckConstraint(
            "capture_source in ('KEYED','FROM_CONFIRMATION')", name="ck_deal_capture_source"
        ),
        Index("ix_deal_status", "tenant_id", "status"),
        # The check path reads active deals for one counterparty on every
        # keystroke. This index and ix_deal_status are the whole of the
        # performance work, in place of caching.
        Index("ix_deal_cp_active", "counterparty_id", "status"),
    )


# --------------------------------------------------------------------------
# Control and evidence
# --------------------------------------------------------------------------


class CheckRun(Base):
    """The evidence behind one evaluation of the six checks.

    Records the limit version, the policy version, the as of date and the
    inputs, so a verdict from six months ago re-derives rather than being
    reconstructed.
    """

    __tablename__ = "check_run"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    counterparty_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("counterparty.id"), nullable=False, index=True
    )
    deal_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("deal.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(24), nullable=False)
    as_of_date: Mapped[str] = mapped_column(String(10), nullable=False)
    limit_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("cp_limit.id"))
    policy_version_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("policy_version.id"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String(12), nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    measured_pence: Mapped[int | None] = mapped_column(Integer)
    measurement_basis: Mapped[str | None] = mapped_column(Text)
    required_approver: Mapped[str | None] = mapped_column(String(24))
    inputs_json: Mapped[str] = mapped_column(Text, nullable=False)
    results_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("app_user.id", name="fk_check_run_created_by_user")
    )
    created_at: Mapped[str] = mapped_column(String(30), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "purpose in ('CHECK','BOOKING','RETEST','CORRECTION',"
            "'ADVISORY_CANDIDATE','ADVISORY_VALIDATION')",
            name="ck_check_run_purpose",
        ),
        CheckConstraint(
            "outcome in ('PASS','FAIL','OVERRIDDEN')", name="ck_check_run_outcome"
        ),
    )


class ExceptionItem(Base):
    """One queue, two causes. A limit failure, or a confirmation mismatch."""

    __tablename__ = "exception_item"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    deal_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("deal.id"), index=True)
    confirmation_id: Mapped[str | None] = mapped_column(String(40))
    counterparty_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("counterparty.id"), nullable=False
    )
    cause: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    check_run_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("check_run.id"))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="OPEN")
    resolution: Mapped[str | None] = mapped_column(String(16))
    resolution_reason: Mapped[str | None] = mapped_column(Text)
    raised_at: Mapped[str] = mapped_column(String(30), nullable=False)
    resolved_by: Mapped[str | None] = mapped_column(String(120))
    resolved_by_user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("app_user.id", name="fk_exception_resolved_by_user")
    )
    resolved_at: Mapped[str | None] = mapped_column(String(30))

    __table_args__ = (
        CheckConstraint(
            "cause in ('LIMIT_FAILURE','CONFIRMATION_MISMATCH')", name="ck_exception_cause"
        ),
        CheckConstraint("status in ('OPEN','RESOLVED')", name="ck_exception_status"),
        CheckConstraint(
            "resolution is null or resolution in "
            "('RESIZED','REROUTED','OVERRIDDEN','CANCELLED','CORRECTED','CHALLENGED')",
            name="ck_exception_resolution",
        ),
        Index("ix_queue_open", "tenant_id", "status", "cause"),
    )


class Breach(Base):
    """A position that was compliant when booked and is not compliant now.

    Responding to a breach records a decision. It does not clear the breach
    and it does not change the deal, because the position is still outside
    policy.
    """

    __tablename__ = "breach"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    counterparty_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("counterparty.id"), nullable=False, index=True
    )
    deal_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("deal.id"), index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    limit_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("cp_limit.id"))
    rating_event_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("rating_event.id"))
    original_check_run_id: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="OPEN")
    response: Mapped[str | None] = mapped_column(String(20))
    response_reason: Mapped[str | None] = mapped_column(Text)
    responded_by: Mapped[str | None] = mapped_column(String(120))
    responded_by_user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("app_user.id", name="fk_breach_responded_by_user")
    )
    responded_at: Mapped[str | None] = mapped_column(String(30))
    raised_at: Mapped[str] = mapped_column(String(30), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "type in ('AMOUNT','TENOR','GROUP','CONCENTRATION','RATING')",
            name="ck_breach_type",
        ),
        CheckConstraint("status in ('OPEN','RESPONDED')", name="ck_breach_status"),
        CheckConstraint(
            "response is null or response in "
            "('HOLD_TO_MATURITY','BREAK_EARLY','SEEK_RATIFICATION','REDUCE_ON_ROLL')",
            name="ck_breach_response",
        ),
    )


# --------------------------------------------------------------------------
# The Oracle boundary
# --------------------------------------------------------------------------


class OracleBalance(Base):
    """Interface I-3. Prior day balances, behind an adapter over this table.

    The concentration check has no denominator without it, and fails closed
    when it is stale or absent.
    """

    __tablename__ = "oracle_balance"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    account_name: Mapped[str] = mapped_column(String(120), nullable=False)
    balance_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    as_of_date: Mapped[str] = mapped_column(String(10), nullable=False)
    received_at: Mapped[str] = mapped_column(String(30), nullable=False)

    __table_args__ = (Index("ix_oracle_balance_asof", "tenant_id", "as_of_date"),)


class OracleInstruction(Base):
    """Interface I-4. Written to a table rather than sent, in this build."""

    __tablename__ = "oracle_instruction"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    deal_id: Mapped[str] = mapped_column(String(40), ForeignKey("deal.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    amount_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    value_date: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    payload: Mapped[str | None] = mapped_column(Text)
    oracle_reference: Mapped[str | None] = mapped_column(String(60))
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("app_user.id", name="fk_instruction_created_by_user")
    )
    created_at: Mapped[str] = mapped_column(String(30), nullable=False)
    sent_at: Mapped[str | None] = mapped_column(String(30))

    __table_args__ = (
        CheckConstraint(
            "type in ('PAYMENT_REQUEST','EXPECTED_INBOUND')", name="ck_instruction_type"
        ),
        CheckConstraint(
            "status in ('PENDING','SENT','ACKNOWLEDGED','FAILED')",
            name="ck_instruction_status",
        ),
    )


# --------------------------------------------------------------------------
# Identity. Phase 1.5.
# --------------------------------------------------------------------------
#
# The largest single gap in the design, closed here. Before this every actor
# in the system was a string in a request body, which meant the approval
# router named a role nobody was checked against, the proposer could approve
# their own deal, and every evidence record was only as good as what somebody
# typed.
#
# Two tables, which is what document 5 budgets. The table is app_user rather
# than user because USER is reserved in PostgreSQL, and phase four is a
# dialect change rather than a rename.


class AppUser(Base):
    """Somebody who can sign in.

    Deleting a person would orphan every check run and limit approval that
    names them, so an account is disabled rather than removed, like
    everything else here.
    """

    __tablename__ = "app_user"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="ACTIVE")
    created_at: Mapped[str] = mapped_column(String(30), nullable=False)
    disabled_at: Mapped[str | None] = mapped_column(String(30))

    __table_args__ = (
        CheckConstraint("status in ('ACTIVE','DISABLED')", name="ck_user_status"),
        UniqueConstraint("tenant_id", "email", name="ux_user_email"),
    )


class Membership(Base):
    """What a person may do, and who said so.

    A role is granted rather than set, so a person can hold more than one and
    the history of who granted what survives. The approval router compares
    the amount against the roles held here.
    """

    __tablename__ = "membership"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("app_user.id", name="fk_membership_user"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    granted_by: Mapped[str] = mapped_column(String(120), nullable=False)
    granted_at: Mapped[str] = mapped_column(String(30), nullable=False)
    revoked_at: Mapped[str | None] = mapped_column(String(30))

    __table_args__ = (
        CheckConstraint(
            "role in ('ANALYST','HEAD_OF_TREASURY','CFO','OPERATOR','AUDITOR')",
            name="ck_membership_role",
        ),
        Index(
            "ux_membership_live",
            "user_id",
            "role",
            unique=True,
            sqlite_where=text("revoked_at IS NULL"),
        ),
    )


# --------------------------------------------------------------------------
# Accounting. Phase 2.
# --------------------------------------------------------------------------
#
# The one place in the system where something computed is stored, and the
# exception is deliberate. Exposure answers what is true now, and recomputing
# it is the only way to be sure it agrees with the deals behind it. An
# accrual answers what was recognised on the third of October, which is a
# historic fact that a later recomputation would quietly rewrite. Once a
# journal has been posted against it, changing it is a reversal rather than a
# recalculation.


class Accrual(Base):
    """What was recognised, per deal, per day."""

    __tablename__ = "accrual"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    deal_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("deal.id"), nullable=False, index=True
    )
    accrual_date: Mapped[str] = mapped_column(String(10), nullable=False)
    day_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rate_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    # Denormalised on purpose. The alternative is a window function on every
    # read of the blotter, and the blotter is read on every write.
    cumulative_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    reversal_of: Mapped[str | None] = mapped_column(String(40))
    amendment_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(30), nullable=False)

    __table_args__ = (
        # One original accrual per deal per day. Partial, so a reversal can
        # share a date with the row it reverses.
        Index(
            "ux_accrual_day",
            "deal_id",
            "accrual_date",
            unique=True,
            sqlite_where=text("reversal_of IS NULL"),
        ),
        Index("ix_accrual_date", "tenant_id", "accrual_date"),
    )


class Journal(Base):
    """What the accounting entry should be.

    The platform works it out. Oracle posts it and keeps it. The account
    mapping lives here because the deal does not exist in Oracle, so nothing
    there could know that deposit interest, an FX gain and a gilt coupon go
    to different accounts.
    """

    __tablename__ = "journal"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    deal_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("deal.id"), nullable=False, index=True
    )
    accrual_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("accrual.id"))
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    # The accounting period, as YYYY-MM. Whether a closed period can be
    # reopened is an accounting policy decision rather than a technical one,
    # and this column is where it bites.
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    debit_account: Mapped[str] = mapped_column(String(40), nullable=False)
    credit_account: Mapped[str] = mapped_column(String(40), nullable=False)
    amount_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="BUILT")
    posted_at: Mapped[str | None] = mapped_column(String(30))
    # What Fusion returned. The only evidence that the entry landed.
    oracle_reference: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[str] = mapped_column(String(30), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "type in ('ACCRUAL','SETTLEMENT','REVALUATION','REVERSAL')",
            name="ck_journal_type",
        ),
        CheckConstraint(
            "status in ('BUILT','POSTED','FAILED')", name="ck_journal_status"
        ),
        Index("ix_journal_period", "tenant_id", "period", "status"),
    )


# --------------------------------------------------------------------------
# The advisory layer. Phase 2.
# --------------------------------------------------------------------------
#
# Read the direction of the arrows. Policy and forecast flow in, candidates
# and a recommendation flow out, and the only edge into the deal table is
# dashed, because nothing is recorded because a model suggested it.


class InvestmentPolicy(Base):
    """The buffer, the ladder and the cover targets.

    The advisory layer refuses to run without one, and says so. That refusal
    is a feature, because it is also the conversation that shapes the
    customer policy.
    """

    __tablename__ = "investment_policy"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    effective_from: Mapped[str] = mapped_column(String(10), nullable=False)
    superseded_at: Mapped[str | None] = mapped_column(String(30))
    liquidity_buffer_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    buffer_horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # What the ranking stage is told to optimise for. Data rather than a
    # prompt, which is what stops it being an instruction a model may ignore.
    priority_order: Mapped[str] = mapped_column(String(60), nullable=False)
    # 0 or 1. Switching it off drops ranking to a weighted score. The
    # recommendation survives; only the explanation is lost.
    model_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_by: Mapped[str] = mapped_column(String(120), nullable=False)
    recorded_by_user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("app_user.id", name="fk_investment_policy_recorded_by")
    )

    __table_args__ = (
        CheckConstraint("model_enabled in (0,1)", name="ck_investment_model_enabled"),
        Index(
            "ux_investment_policy_current",
            "tenant_id",
            unique=True,
            sqlite_where=text("superseded_at IS NULL"),
        ),
    )


class LadderTarget(Base):
    """What share of the portfolio should mature in each bucket."""

    __tablename__ = "ladder_target"

    policy_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("investment_policy.id"), primary_key=True
    )
    bucket: Mapped[str] = mapped_column(String(10), primary_key=True)
    target_share_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    # An absolute floor, for when the portfolio is small enough that a share
    # is meaningless.
    minimum_pence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint(
            "bucket in ('0_3M','3_6M','6_12M','OVER_12M')", name="ck_ladder_bucket"
        ),
    )


class CurrencyCoverTarget(Base):
    """How much of a currency obligation must be hedged, and how far out."""

    __tablename__ = "currency_cover_target"

    policy_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("investment_policy.id"), primary_key=True
    )
    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    target_cover_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)


class ForecastLine(Base):
    """The forecast from Oracle EPM. Interface I-9.

    Without it the advisory layer has nothing to test. A forecast is a
    statement made on a day and it is not corrected in place, which is why
    as_of is on every row.
    """

    __tablename__ = "forecast_line"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    as_of: Mapped[str] = mapped_column(String(10), nullable=False)
    forecast_date: Mapped[str] = mapped_column(String(10), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # Signed. Positive on an inflow. Minor units of the stated currency.
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    entity: Mapped[str | None] = mapped_column(String(120))
    received_at: Mapped[str] = mapped_column(String(30), nullable=False)

    __table_args__ = (Index("ix_forecast_window", "tenant_id", "forecast_date"),)


class AdvisoryRun(Base):
    """One nightly run.

    Written whether or not a model was called, and whether or not a gap was
    found. A run that found nothing is evidence that the layer looked.
    """

    __tablename__ = "advisory_run"

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    as_of: Mapped[str] = mapped_column(String(10), nullable=False)
    started_at: Mapped[str] = mapped_column(String(30), nullable=False)
    finished_at: Mapped[str | None] = mapped_column(String(30))
    policy_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("investment_policy.id"), nullable=False
    )
    gap_type: Mapped[str] = mapped_column(String(24), nullable=False)
    gap_amount_minor: Mapped[int | None] = mapped_column(Integer)
    gap_currency: Mapped[str | None] = mapped_column(String(3))
    gap_date: Mapped[str | None] = mapped_column(String(10))
    # As it stood at the time of the run, not as it stands now.
    model_enabled: Mapped[int] = mapped_column(Integer, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(60))
    outcome: Mapped[str] = mapped_column(String(28), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "gap_type in ('CASH_SURPLUS','CASH_SHORTFALL','LADDER_GAP',"
            "'CURRENCY_UNCOVERED','NONE')",
            name="ck_run_gap_type",
        ),
        CheckConstraint(
            "outcome in ('NO_GAP','MODEL_ACCEPTED','MODEL_REJECTED_FALLBACK',"
            "'RULE_ONLY','NO_CANDIDATES')",
            name="ck_run_outcome",
        ),
        Index("ix_advisory_run_asof", "tenant_id", "as_of"),
    )


class Candidate(Base):
    """The options the rules produced, priced.

    Excluded options are kept, because why was X not picked is the question
    that gets asked, and the exclusion is the guardrail rather than the
    ranking.
    """

    __tablename__ = "candidate"

    id: Mapped[str] = _id()
    run_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("advisory_run.id"), nullable=False
    )
    counterparty_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("counterparty.id"), nullable=False
    )
    instrument: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    tenor_months: Mapped[int] = mapped_column(Integer, nullable=False)
    # Computed at stage 3. The model never generates a rate, and this column
    # is where every figure in the recommendation comes from.
    indicative_rate_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    # The deterministic score, computed whether or not the model runs, so the
    # fallback is always available.
    score_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
    rank: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint("excluded in (0,1)", name="ck_candidate_excluded"),
        Index("ix_candidate_run", "run_id", "excluded", "rank"),
    )


class Recommendation(Base):
    """What was proposed and what a person did about it.

    candidate_id is a foreign key, which is what makes an invented
    counterparty structurally impossible rather than merely discouraged.

    The disagreement log is the most valuable data this produces. Every
    rejection with its reason is a record of where the ranking disagreed with
    a treasurer, and that is worth more than the ranking itself.
    """

    __tablename__ = "recommendation"

    id: Mapped[str] = _id()
    run_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("advisory_run.id"), nullable=False
    )
    candidate_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("candidate.id"), nullable=False
    )
    # The model prose. Null when the fallback produced the pick.
    rationale: Mapped[str | None] = mapped_column(Text)
    alternatives_json: Mapped[str] = mapped_column(Text, nullable=False)
    # Shown to the user, not hidden.
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    decision: Mapped[str | None] = mapped_column(String(12))
    decided_by: Mapped[str | None] = mapped_column(String(120))
    decided_by_user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("app_user.id", name="fk_recommendation_decided_by")
    )
    decided_at: Mapped[str | None] = mapped_column(String(30))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    # Set only if it became a deal, and only after that deal passed the six
    # checks. Written by the deal endpoint, never by the advisory layer.
    deal_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("deal.id"))

    __table_args__ = (
        CheckConstraint("source in ('MODEL','RULE_FALLBACK')", name="ck_rec_source"),
        CheckConstraint(
            "decision is null or decision in ('ACCEPTED','EDITED','REJECTED','EXPIRED')",
            name="ck_rec_decision",
        ),
    )


class ValidationResult(Base):
    """Three tests, all of which must pass. One row each, so a failure names
    itself."""

    __tablename__ = "validation_result"

    id: Mapped[str] = _id()
    run_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("advisory_run.id"), nullable=False
    )
    test: Mapped[str] = mapped_column(String(24), nullable=False)
    passed: Mapped[int] = mapped_column(Integer, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "test in ('ID_IS_REAL','CHECKS_RERUN_CLEAN','FIGURES_AGREE')",
            name="ck_validation_test",
        ),
        CheckConstraint("passed in (0,1)", name="ck_validation_passed"),
    )


#: Every table the running system has. Named for the phase that introduced
#: the first of them; identity added two in phase 1.5, and accounting and the
#: advisory layer added ten in phase 2.
PHASE_ONE_TABLES = [
    Tenant,
    AppUser,
    Membership,
    SystemClock,
    PolicyVersion,
    RatingBand,
    CpGroup,
    Counterparty,
    CounterpartyInstrument,
    CpLimit,
    RatingEvent,
    Deal,
    CheckRun,
    ExceptionItem,
    Breach,
    OracleBalance,
    OracleInstruction,
    InvestmentPolicy,
    LadderTarget,
    CurrencyCoverTarget,
    ForecastLine,
    Accrual,
    Journal,
    AdvisoryRun,
    Candidate,
    Recommendation,
    ValidationResult,
]
