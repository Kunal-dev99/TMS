"""Phase 2. What the accounting entry should be.

The platform works it out. Oracle posts it and keeps it.

The account mapping lives here because the deal does not exist in Oracle, so
nothing there could know that deposit interest, an FX gain and a gilt coupon
go to different accounts. It is a table of data in a module rather than a
table in the database, because a customer changing their chart of accounts
is a configuration change worth a migration, not a screen.

Posting is idempotent per journal rather than per batch. A partial failure
must leave the successful entries posted, because Oracle already has them,
and a retry must post only what did not land.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ErrorCode, TreasuryError
from app.ids import new_id, now
from app.models import Accrual, Deal, Journal
from app.repo import deals as deal_repo

#: Debit and credit per instrument, for an interest accrual. Reversals swap
#: the two rather than negating the amount, so a reversal reads the way an
#: accountant expects.
ACCOUNT_MAP: dict[str, tuple[str, str]] = {
    "DEPOSIT": ("1210 Interest receivable", "4100 Interest income"),
    "MMF": ("1215 Money market fund receivable", "4110 Money market fund income"),
    "GILT": ("1220 Gilt coupon receivable", "4120 Gilt coupon income"),
}


@dataclass
class PostingResult:
    period: str
    posted: int = 0
    skipped: int = 0
    failed: int = 0
    references: list[str] = field(default_factory=list)


class OracleJournalAdapter:
    """Interface I-6. Journals and reversals out, daily or monthly.

    A stub over nothing, which returns a reference the way Fusion would. The
    interface is the deliverable; phase four swaps what is behind it and
    nothing else changes.
    """

    name = "oracle-fusion-gl"

    def post(self, journal: Journal) -> str:
        return f"GL-{journal.period.replace('-', '')}-{journal.id[-8:].upper()}"


class JournalService:
    def __init__(
        self,
        session: Session,
        tenant_id: str,
        as_of_date: str,
        adapter: OracleJournalAdapter | None = None,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.as_of_date = as_of_date
        self.adapter = adapter or OracleJournalAdapter()

    # -------------------------------------------------------------- build

    def build_from_accruals(self) -> int:
        """One journal per accrual row that does not have one yet.

        Building is separate from posting because the two fail differently.
        Building is arithmetic against rows we own; posting depends on
        somebody else being reachable.
        """
        already = {
            row.accrual_id
            for row in self.session.scalars(
                select(Journal).where(Journal.tenant_id == self.tenant_id)
            )
            if row.accrual_id
        }

        deals = {
            deal.id: deal
            for deal in self.session.scalars(
                select(Deal).where(Deal.tenant_id == self.tenant_id)
            )
        }

        built = 0
        for accrual in self.session.scalars(
            select(Accrual).where(Accrual.tenant_id == self.tenant_id)
        ):
            if accrual.id in already:
                continue
            deal = deals.get(accrual.deal_id)
            if deal is None or deal.instrument not in ACCOUNT_MAP:
                continue

            debit, credit = ACCOUNT_MAP[deal.instrument]
            reversal = accrual.reversal_of is not None
            if reversal:
                debit, credit = credit, debit

            self.session.add(
                Journal(
                    id=new_id("jnl"),
                    tenant_id=self.tenant_id,
                    deal_id=accrual.deal_id,
                    accrual_id=accrual.id,
                    type="REVERSAL" if reversal else "ACCRUAL",
                    period=accrual.accrual_date[:7],
                    debit_account=debit,
                    credit_account=credit,
                    amount_pence=abs(accrual.amount_pence),
                    status="BUILT",
                    created_at=now(),
                )
            )
            built += 1

        self.session.flush()
        return built

    # --------------------------------------------------------------- post

    def post_period(self, period: str) -> PostingResult:
        """Hand a period to Oracle.

        Idempotent by journal. Already posted entries are skipped and
        reported as such, so a retry after a partial failure posts only what
        did not land.
        """
        result = PostingResult(period=period)
        journals = list(
            self.session.scalars(
                select(Journal)
                .where(Journal.tenant_id == self.tenant_id)
                .where(Journal.period == period)
            )
        )
        if not journals:
            return result

        for journal in journals:
            if journal.status == "POSTED":
                result.skipped += 1
                continue
            try:
                reference = self.adapter.post(journal)
            except Exception:
                # The entry stays FAILED and retriable. Nothing else in the
                # book depends on the handover succeeding.
                journal.status = "FAILED"
                result.failed += 1
                continue
            journal.status = "POSTED"
            journal.posted_at = now()
            journal.oracle_reference = reference
            result.posted += 1
            result.references.append(reference)

        self.session.flush()
        return result

    # -------------------------------------------------------------- reads

    def list_journals(
        self,
        period: str | None = None,
        status: str | None = None,
        deal_id: str | None = None,
    ) -> list[Journal]:
        statement = select(Journal).where(Journal.tenant_id == self.tenant_id)
        if period:
            statement = statement.where(Journal.period == period)
        if status:
            statement = statement.where(Journal.status == status)
        if deal_id:
            statement = statement.where(Journal.deal_id == deal_id)
        return list(
            self.session.scalars(statement.order_by(Journal.period, Journal.created_at))
        )

    def summary_for_deal(self, deal_id: str) -> list[dict]:
        """Grouped by period and status, which is how the deal panel shows
        them: an accountant asks what is unposted in an open period, not
        which rows exist."""
        grouped: dict[tuple[str, str], dict] = {}
        for journal in self.list_journals(deal_id=deal_id):
            key = (journal.period, journal.status)
            bucket = grouped.setdefault(
                key,
                {
                    "period": journal.period,
                    "status": journal.status,
                    "count": 0,
                    "amount_pence": 0,
                    "oracle_reference": None,
                },
            )
            bucket["count"] += 1
            bucket["amount_pence"] += journal.amount_pence
            if journal.oracle_reference:
                bucket["oracle_reference"] = journal.oracle_reference
        return sorted(grouped.values(), key=lambda row: (row["period"], row["status"]))

    def require_open_period(self, period: str) -> None:
        """Whether a closed period can be reopened is an accounting policy
        decision rather than a technical one, and the answer differs by
        customer.

        Phase three surfaces it as a distinct refusal when an amendment
        reaches into one. Nothing closes a period yet, so this holds the
        shape and refuses nothing.
        """
        if period > self.as_of_date[:7]:
            raise TreasuryError(
                ErrorCode.CLOSED_PERIOD_LOCKED,
                f"{period} has not started yet.",
                field="period",
            )
