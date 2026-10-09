"""The interfaces every external system reaches the app through.

Every port is a Protocol — adapters implement them structurally, no
inheritance required. Return types are simple dataclasses so callers
never depend on a vendor SDK's shapes.

Rule for every port: the fake adapter and the real adapter are
interchangeable. A test that passes with ``FakeOracle`` bound MUST
pass with ``OracleFusion`` bound — that is the whole point of the
substrate. Any drift between fake and real is a bug in the fake.

Stage 1 gives every port a Protocol and a minimum sensible shape.
Later stages flesh out return types + method surface without
breaking earlier consumers (additive only).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Protocol, runtime_checkable


# ==========================================================================
# Value objects — small dataclasses passed across port boundaries.
# ==========================================================================


@dataclass(frozen=True)
class ExposureSnapshot:
    """One legal-entity's currency exposure at a moment in time.

    Mirrors the shape of the ``currency_exposure`` table so a caller
    can persist it without a translation layer.
    """

    tenant_id: str
    legal_entity_id: str
    currency: str
    gross_receivable_pence: int
    gross_payable_pence: int
    forecast_pence: int
    as_of_date: str  # ISO 'YYYY-MM-DD'
    source: str = "connector"


@dataclass(frozen=True)
class BankStatement:
    """One bank statement covering one account for one date."""

    account_id: str
    as_of_date: str
    opening_balance_pence: int
    closing_balance_pence: int
    currency: str
    lines: list["BankStatementLine"] = field(default_factory=list)


@dataclass(frozen=True)
class BankStatementLine:
    booked_at: str
    amount_pence: int  # positive = credit, negative = debit
    reference: str | None
    counterparty_hint: str | None


@dataclass(frozen=True)
class JournalEntry:
    """One GL journal entry, ledger-agnostic in shape."""

    external_reference: str  # idempotency key; e.g. 'TR:accrual:accr_xyz'
    ledger_name: str
    accounting_date: str
    description: str
    lines: list["JournalLine"]


@dataclass(frozen=True)
class JournalLine:
    account_combination: str
    currency: str
    debit_pence: int = 0
    credit_pence: int = 0


@dataclass(frozen=True)
class JournalAck:
    external_reference: str
    ledger_journal_id: str  # e.g. Oracle JeHeaderId
    posted_at: str


@dataclass(frozen=True)
class Payment:
    """An outbound payment, protocol-agnostic in shape."""

    uetr: str  # unique end-to-end transaction reference
    debtor_account: str
    creditor_account: str
    amount_pence: int
    currency: str
    value_date: str
    reference: str


@dataclass(frozen=True)
class BankSubmissionAck:
    uetr: str
    status: str  # ACCEPTED | REJECTED | PENDING
    bank_reference: str | None
    reason_code: str | None
    reason_text: str | None


@dataclass(frozen=True)
class InboundMessage:
    kind: str  # e.g. 'MT940', 'camt.053', 'MT300'
    body: bytes
    received_at: str


@dataclass(frozen=True)
class Quote:
    pair: str  # 'EURGBP'
    rate: float
    as_of: str  # ISO timestamp
    source: str


@dataclass(frozen=True)
class Rate:
    name: str  # 'SONIA', 'ESTR', 'SOFR'
    value_bp: int
    as_of: str
    source: str


@dataclass(frozen=True)
class LoginStart:
    authorize_url: str
    state: str


@dataclass(frozen=True)
class IdentityAssertion:
    subject: str  # IdP sub or local user_id
    email: str
    display_name: str
    groups: tuple[str, ...] = ()
    mfa_passed: bool = False
    raw_claims: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    tokens_prompt: int
    tokens_completion: int
    fallback: bool


# ==========================================================================
# Ports — interfaces.
# ==========================================================================


@runtime_checkable
class ERPPort(Protocol):
    """AR/AP/forecast in; GL journal entries out."""

    name: str

    def pull_exposure(
        self,
        tenant_id: str,
        legal_entity_id: str,
        as_of: date,
        currency: str = "EUR",
    ) -> ExposureSnapshot: ...

    def pull_bank_statement(self, account_id: str, as_of: date) -> BankStatement | None: ...

    def post_journal(self, entry: JournalEntry) -> JournalAck: ...


@runtime_checkable
class BankPort(Protocol):
    """Outbound payments + inbound statements/confirmations."""

    name: str

    def submit_payment(self, payment: Payment, signature: bytes) -> BankSubmissionAck: ...

    def poll_inbox(self) -> Iterable[InboundMessage]: ...


@runtime_checkable
class MarketDataPort(Protocol):
    """FX spot + forward + interest benchmarks."""

    name: str

    def spot(self, pair: str) -> Quote: ...

    def forward(self, pair: str, tenor_months: int) -> Quote: ...

    def benchmark(self, code: str, as_of: date) -> Rate: ...


@runtime_checkable
class IdentityPort(Protocol):
    """Sign-in + bearer-token verification. Password OR OIDC — same shape."""

    name: str

    def start_login(self, redirect_uri: str) -> LoginStart: ...

    def complete_login(self, code: str, state: str) -> IdentityAssertion: ...

    def verify_bearer(self, token: str) -> IdentityAssertion | None: ...


@runtime_checkable
class SigningPort(Protocol):
    """Sign a payment payload with a customer-controlled key."""

    name: str

    def sign(self, payload: bytes, key_ref: str) -> bytes: ...


@runtime_checkable
class LLMPort(Protocol):
    """One chat call. Adapter picks the model behind ``model_hint``."""

    name: str

    def chat(self, system: str, user: str, model_hint: str | None = None) -> LLMResponse: ...


@runtime_checkable
class SecretsPort(Protocol):
    """Read a named secret. Adapters differ in WHERE they read from."""

    name: str

    def get(self, key: str, default: str | None = None) -> str | None: ...

    def rotate(self, key: str) -> None:  # optional, no-op in most adapters
        ...


@runtime_checkable
class MailPort(Protocol):
    """Send one email. Adapter differs in delivery mechanism."""

    name: str

    def send(
        self, to: str, subject: str, body_text: str, body_html: str | None = None
    ) -> None: ...


@runtime_checkable
class RateLimitStorePort(Protocol):
    """Sliding-window counter store for rate_limit.

    Adapters implement one method. The in-process adapter uses a deque
    per key (today's behaviour); the Redis adapter uses a sorted set so
    multiple app instances share the same bucket. The service calls
    ``hit`` once per request; the store does the window arithmetic.

    Return: ``(allowed, retry_after_seconds)``. When ``allowed`` is
    False the caller raises RATE_LIMITED using ``retry_after_seconds``
    for the user-facing message.
    """

    name: str

    def hit(
        self,
        key: str,
        max_requests: int,
        window_seconds: float,
    ) -> tuple[bool, float]: ...

    def clear(self) -> None:  # for tests; a Redis adapter FLUSHes its namespace
        ...


ALL_PORTS: tuple[type, ...] = (
    ERPPort,
    BankPort,
    MarketDataPort,
    IdentityPort,
    SigningPort,
    LLMPort,
    SecretsPort,
    MailPort,
    RateLimitStorePort,
)
