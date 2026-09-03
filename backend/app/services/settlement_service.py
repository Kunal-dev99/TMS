"""Phase 3. Settlement, and the close.

Where three sources have to agree: the deal record, the counterparty's
confirmation, and the bank statement line.

**Two of three agreeing is not enough.** If the deal record and the
confirmation agree but the statement differs, the money did not arrive as
promised, and that is a break rather than a close. This is the one rule in
the file that is easy to get wrong and expensive to explain afterwards, so
`_agree` returns which two agreed and by how much the third differed rather
than a boolean.

Closing is part of the control system rather than an accounting formality.
Until a deal closes, the counterparty's headroom is still consumed and the
next deal may be blocked for no reason.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ErrorCode, TreasuryError
from app.formatting import sterling
from app.ids import new_id, now
from app.models import BankStatementLine, Confirmation, Deal, Settlement
from app.repo import deals as deal_repo
from app.services.accrual_service import AccrualService

#: How far apart two figures may be and still count as agreeing. Zero: these
#: are integer pence and a penny of disagreement is a disagreement. A
#: tolerance here would be a policy decision hidden in a constant.
TOLERANCE_PENCE = 0


@dataclass
class SettlementOutcome:
    settlement: Settlement
    closed: bool
    break_detail: str | None


class SettlementService:
    def __init__(self, session: Session, tenant_id: str, as_of_date: str) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.as_of_date = as_of_date
        self.accruals = AccrualService(session, tenant_id, as_of_date)

    # ------------------------------------------------------ the third source

    def ingest_statement_line(
        self,
        account_name: str,
        amount_pence: int,
        value_date: str,
        reference: str | None = None,
    ) -> BankStatementLine:
        """Interface I-3, the statement half.

        Prior day rather than intraday. A stated boundary rather than a
        defect: nothing here pretends to know what happened this morning.
        """
        line = BankStatementLine(
            id=new_id("bsl"),
            tenant_id=self.tenant_id,
            account_name=account_name,
            amount_pence=amount_pence,
            value_date=value_date,
            reference=reference,
            received_at=now(),
        )
        self.session.add(line)
        self.session.flush()
        return line

    def statement_lines(self) -> list[BankStatementLine]:
        return list(
            self.session.scalars(
                select(BankStatementLine)
                .where(BankStatementLine.tenant_id == self.tenant_id)
                .order_by(BankStatementLine.value_date.desc())
            )
        )

    # ------------------------------------------------------------- settle

    def settle(
        self, deal_id: str, statement_line_id: str, settled_by
    ) -> SettlementOutcome:
        """Compare three sources and close only on agreement."""
        deal = deal_repo.get(self.session, deal_id)
        if deal is None or deal.tenant_id != self.tenant_id:
            raise TreasuryError(ErrorCode.DEAL_NOT_FOUND)
        if deal.closed_at is not None:
            raise TreasuryError(
                ErrorCode.DEAL_NOT_AMENDABLE, "This deal is already closed."
            )
        if deal.status not in ("ACTIVE", "MATURED"):
            raise TreasuryError(
                ErrorCode.DEAL_NOT_APPROVED,
                f"A deal that is {deal.status.lower()} cannot be settled.",
            )

        line = self.session.get(BankStatementLine, statement_line_id)
        if line is None or line.tenant_id != self.tenant_id:
            raise TreasuryError(
                ErrorCode.CONFIRMATION_NOT_FOUND,
                "That statement line does not exist.",
                field="statement_line_id",
            )

        # Source one: what the deal record says should arrive.
        _today, interest = self.accruals.summary_for_deal(deal_id)
        expected = deal.principal_pence + interest

        # Source two: what the counterparty confirmed. Absent is not the same
        # as disagreeing, and it is not the same as agreeing either.
        confirmation = self.session.scalars(
            select(Confirmation).where(Confirmation.deal_id == deal_id)
        ).first()
        confirmed = None
        if confirmation is not None and confirmation.match_status in (
            "MATCHED",
            "MISMATCHED",
        ):
            confirmed = confirmation.principal_pence + interest

        # Source three: what the bank actually paid.
        received = abs(line.amount_pence)

        status, detail = self._agree(expected, confirmed, received)

        settlement = self.session.scalars(
            select(Settlement).where(Settlement.deal_id == deal_id)
        ).one_or_none()
        if settlement is None:
            settlement = Settlement(
                id=new_id("stl"),
                tenant_id=self.tenant_id,
                deal_id=deal_id,
                expected_principal_pence=deal.principal_pence,
                expected_interest_pence=interest,
                match_status="PENDING",
            )
            self.session.add(settlement)
            self.session.flush()

        settlement.confirmed_amount_pence = confirmed
        settlement.statement_amount_pence = received
        settlement.statement_line_id = line.id
        settlement.match_status = status
        settlement.break_detail = detail
        settlement.settled_by = str(settled_by)
        settlement.settled_by_user_id = settled_by.user_id

        if status == "AGREED":
            settlement.closed_at = now()
            deal.closed_at = settlement.closed_at
            deal.status = "CLOSED"

        self.session.flush()
        return SettlementOutcome(
            settlement=settlement,
            closed=status == "AGREED",
            break_detail=detail,
        )

    # ---------------------------------------------------------- the rule

    @staticmethod
    def _agree(
        expected: int, confirmed: int | None, received: int
    ) -> tuple[str, str | None]:
        """Three sources, and two of three is not enough.

        Returns which two agree and by how much the third differs, because
        `mismatch` tells a treasurer nothing and `the record and the
        confirmation say 18,119,836 and the bank paid 18,000,000` tells them
        who to ring.
        """

        def same(left: int | None, right: int | None) -> bool:
            if left is None or right is None:
                return False
            return abs(left - right) <= TOLERANCE_PENCE

        if confirmed is None:
            # Only two sources. Not a break, but not a close either: the
            # confirmation has not arrived, and closing on two sources is
            # exactly the shortcut this control exists to prevent.
            if same(expected, received):
                return (
                    "PENDING",
                    "The record and the statement agree. Waiting on the "
                    "confirmation, because closing on two sources is not a "
                    "three way match.",
                )
            return (
                "BREAK",
                f"The record says {sterling(expected)} and the bank paid "
                f"{sterling(received)}. No confirmation has arrived.",
            )

        if same(expected, confirmed) and same(expected, received):
            return "AGREED", None

        if same(expected, confirmed):
            return (
                "BREAK",
                f"The record and the confirmation agree at {sterling(expected)}. "
                f"The bank paid {sterling(received)}, "
                f"{sterling(abs(expected - received))} out. The money did not "
                "arrive as promised.",
            )

        if same(expected, received):
            return (
                "BREAK",
                f"The record and the statement agree at {sterling(expected)}. "
                f"The counterparty confirmed {sterling(confirmed)}, "
                f"{sterling(abs(expected - confirmed))} out.",
            )

        if same(confirmed, received):
            return (
                "BREAK",
                f"The confirmation and the statement agree at "
                f"{sterling(confirmed)}. Our record says {sterling(expected)}, "
                f"{sterling(abs(expected - confirmed))} out.",
            )

        return (
            "BREAK",
            f"All three disagree. Record {sterling(expected)}, confirmation "
            f"{sterling(confirmed)}, statement {sterling(received)}.",
        )

    # -------------------------------------------------------------- reads

    def for_deal(self, deal_id: str) -> Settlement | None:
        return self.session.scalars(
            select(Settlement).where(Settlement.deal_id == deal_id)
        ).one_or_none()

    def mature_due_deals(self) -> int:
        """Move deals past their maturity date to MATURED.

        Matured means due. Closed means three sources agreed. Until closed,
        the counterparty's headroom is still consumed, which is why this
        transition exists at all rather than jumping straight to closed.
        """
        moved = 0
        for deal in deal_repo.live_for_tenant(self.session, self.tenant_id):
            if (
                deal.status == "ACTIVE"
                and deal.maturity_date
                and deal.maturity_date <= self.as_of_date
            ):
                deal.status = "MATURED"
                moved += 1
        self.session.flush()
        return moved
