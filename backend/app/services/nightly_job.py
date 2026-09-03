"""Phase 2. The nightly job.

Accrual, then advisory. The order matters and it is not arbitrary: the
advisory layer reads live positions, and a stale accrual mis-states the
ladder it is measuring a gap against.

If accrual fails, the advisory run does not start. A recommendation built on
figures that were not brought up to date is worse than no recommendation,
because it looks exactly like a good one.

Idempotent by clock date. Running it twice for the same date writes accruals
once, because the partial unique index on the accrual day says so and the
service asks rather than assumes. The advisory run is not repeated for a
date that already has one unless force is passed.

The caller is a scheduler and does not wait, which is why the endpoint
returns 202. Nothing here is on a request path anybody is watching.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.errors import TreasuryError
from app.models import PolicyVersion
from app.services.accrual_service import AccrualService
from app.services.advisory_service import AdvisoryService
from app.services.journal_service import JournalService
from app.services.settlement_service import SettlementService


@dataclass
class NightlyResult:
    as_of: str
    accrual_rows_written: int = 0
    accrual_rows_already_present: int = 0
    journals_built: int = 0
    advisory_run_id: str | None = None
    advisory_outcome: str | None = None
    advisory_skipped: str | None = None
    steps: list[str] = field(default_factory=list)


class NightlyJob:
    def __init__(
        self,
        session: Session,
        tenant_id: str,
        as_of_date: str,
        policy: PolicyVersion,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.as_of_date = as_of_date
        self.policy = policy

    def run(self, as_of: str | None = None, force: bool = False) -> NightlyResult:
        target = as_of or self.as_of_date
        result = NightlyResult(as_of=target)

        # 1. Accrual. Everything else waits on this.
        accrual = AccrualService(self.session, self.tenant_id, target).accrue_to_date(
            target
        )
        result.accrual_rows_written = accrual.rows_written
        result.accrual_rows_already_present = accrual.rows_already_present
        result.steps.append(
            f"Accrued {accrual.rows_written} days across "
            f"{accrual.deals_considered} positions."
        )

        # 2. Journals, built from what was just recognised. Built, not
        #    posted: posting is a separate call because it depends on Oracle
        #    being reachable and this does not.
        journals = JournalService(self.session, self.tenant_id, target)
        result.journals_built = journals.build_from_accruals()
        result.steps.append(f"Built {result.journals_built} journal entries.")

        # 3. Anything past its maturity date is due. Matured means due;
        #    closed means three sources agreed. Until it closes the
        #    counterparty still holds the headroom, which is why these are
        #    two states rather than one.
        matured = SettlementService(
            self.session, self.tenant_id, target
        ).mature_due_deals()
        if matured:
            result.steps.append(f"{matured} position(s) reached maturity.")

        # 4. Advisory, last, against positions that are now up to date.
        advisory = AdvisoryService(
            self.session, self.tenant_id, target, self.policy
        )
        try:
            outcome = advisory.run(as_of=target, force=force)
            result.advisory_run_id = outcome.run.id
            result.advisory_outcome = outcome.run.outcome
            result.steps.append(f"Advisory run {outcome.run.outcome.lower()}.")
        except TreasuryError as refusal:
            # The layer refusing to run without an investment policy is a
            # feature, and it must not take the accrual down with it.
            result.advisory_skipped = refusal.message
            result.steps.append(f"Advisory skipped. {refusal.message}")

        return result
