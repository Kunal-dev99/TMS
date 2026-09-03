"""Phase 3. Amendments.

Recalculating is the easy half. Knowing what was already recognised is the
hard half, and it is only possible because accrual is stored per day rather
than computed on read. `AccrualService.reverse_from` was written in phase two
for exactly this, and this is the caller it was waiting for.

Raising and applying are two calls on purpose. Raising records what is
proposed and what it will change, which is reviewable. Applying performs
every reversal in one transaction, because a partial reversal leaves the
ledger disagreeing with the deal, and that is worse than no amendment at all.

A correction is an entry, not an edit. The original accrual rows stay,
marked with what reversed them, and new rows are written at the new terms.
"""

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ErrorCode, TreasuryError
from app.formatting import sterling
from app.ids import new_id, now
from app.models import Amendment, CheckRun, ExceptionItem, Journal, PolicyVersion
from app.repo import deals as deal_repo
from app.services.accrual_service import AccrualService
from app.services.check_engine import CheckEngine
from app.services.journal_service import JournalService


@dataclass
class AmendmentPreview:
    """What applying would change, without changing it.

    This is what makes raising and applying two calls rather than one: a
    reversal that reaches into a closed period is a conversation with the
    accountants, and it has to be visible before it happens.
    """

    accruals_affected: int
    amount_to_reverse_pence: int
    periods_affected: list[str] = field(default_factory=list)
    any_period_closed: bool = False


@dataclass
class AmendmentApplied:
    reversed_pence: int
    reposted_pence: int
    periods_reopened: list[str] = field(default_factory=list)
    #: Set when the amended terms failed the six checks and nothing was
    #: reversed. The check run and the queue item are still written, because
    #: a refusal with no evidence is a refusal somebody has to take on trust.
    refused: bool = False
    refusal_detail: str | None = None
    queue_item_id: str | None = None


#: What each kind of amendment is allowed to move.
#:
#: The type is not decoration. A partial drawdown that increases the
#: principal is not a drawdown, and accepting one means the word in the
#: audit trail does not describe what happened. A correction is the
#: exception: it exists to undo a keying error, so any field may move in
#: any direction.
def _validate_terms(
    kind: str,
    deal,
    new_principal_pence: int | None,
    new_rate_bp: int | None,
    new_maturity_date: str | None,
) -> None:
    if kind == "BREAK":
        if any((new_principal_pence, new_rate_bp, new_maturity_date)):
            raise TreasuryError(
                ErrorCode.AMENDMENT_TYPE_INVALID,
                "A break ends the deal on the effective date. It does not "
                "carry new terms.",
            )
        return

    if kind == "ROLL":
        if new_maturity_date is None:
            raise TreasuryError(
                ErrorCode.AMENDMENT_TYPE_INVALID,
                "A roll extends the deal, so it needs a new maturity date.",
                field="new_maturity_date",
            )
        if deal.maturity_date and new_maturity_date <= deal.maturity_date:
            raise TreasuryError(
                ErrorCode.AMENDMENT_TYPE_INVALID,
                f"A roll extends the deal. This one matures on "
                f"{deal.maturity_date}, and {new_maturity_date} is not later.",
                field="new_maturity_date",
            )
        return

    if kind == "PARTIAL_DRAWDOWN":
        if new_principal_pence is None:
            raise TreasuryError(
                ErrorCode.AMENDMENT_TYPE_INVALID,
                "A partial drawdown reduces the principal, so it needs a new one.",
                field="new_principal_pence",
            )
        if new_principal_pence <= 0:
            raise TreasuryError(
                ErrorCode.AMENDMENT_TYPE_INVALID,
                "A drawdown to nothing is a break, not a drawdown.",
                field="new_principal_pence",
            )
        if new_principal_pence >= deal.principal_pence:
            raise TreasuryError(
                ErrorCode.AMENDMENT_TYPE_INVALID,
                f"A partial drawdown reduces the principal. This deal is "
                f"{sterling(deal.principal_pence)} and "
                f"{sterling(new_principal_pence)} is not less.",
                field="new_principal_pence",
            )
        return

    if not any((new_principal_pence, new_rate_bp, new_maturity_date)):
        raise TreasuryError(
            ErrorCode.AMENDMENT_TYPE_INVALID,
            "A correction has to correct something.",
        )


class AmendmentService:
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
        self.accruals = AccrualService(session, tenant_id, as_of_date)
        self.journals = JournalService(session, tenant_id, as_of_date)

    # ------------------------------------------------------------- raise

    def raise_amendment(
        self,
        deal_id: str,
        type: str,
        effective_date: str,
        reason: str,
        raised_by,
        new_principal_pence: int | None = None,
        new_rate_bp: int | None = None,
        new_maturity_date: str | None = None,
    ) -> tuple[Amendment, AmendmentPreview]:
        """Record what is proposed. Nothing is recalculated and nothing is
        reversed."""
        deal = deal_repo.get(self.session, deal_id)
        if deal is None or deal.tenant_id != self.tenant_id:
            raise TreasuryError(ErrorCode.DEAL_NOT_FOUND)

        if not reason or not reason.strip():
            raise TreasuryError(ErrorCode.AMENDMENT_REASON_REQUIRED, field="reason")

        if effective_date < deal.value_date:
            raise TreasuryError(
                ErrorCode.EFFECTIVE_DATE_BEFORE_VALUE_DATE,
                f"This deal started on {deal.value_date}.",
                field="effective_date",
            )

        if deal.status not in ("ACTIVE", "MATURED"):
            raise TreasuryError(
                ErrorCode.DEAL_NOT_AMENDABLE,
                f"Only a live deal can be amended. This one is {deal.status.lower()}.",
            )

        _validate_terms(
            type, deal, new_principal_pence, new_rate_bp, new_maturity_date
        )

        amendment = Amendment(
            id=new_id("amd"),
            tenant_id=self.tenant_id,
            deal_id=deal_id,
            type=type,
            effective_date=effective_date,
            new_principal_pence=new_principal_pence,
            new_rate_bp=new_rate_bp,
            new_maturity_date=new_maturity_date,
            reason=reason.strip(),
            raised_by=str(raised_by),
            raised_by_user_id=raised_by.user_id,
            raised_at=now(),
            status="RAISED",
        )
        self.session.add(amendment)
        self.session.flush()

        return amendment, self.preview(deal_id, effective_date)


    # --------------------------------------------------------------- gate

    @staticmethod
    def _tenor_months(value_date: str, maturity_date: str) -> int:
        """The inverse of the booking maturity calculation.

        A roll changes the maturity, and `TENOR_BAND` is checked against a
        tenor in months, so the new tenor has to be derived rather than
        carried over from the original.
        """
        from datetime import date

        start = date.fromisoformat(value_date)
        end = date.fromisoformat(maturity_date)
        months = (end.year - start.year) * 12 + (end.month - start.month)
        if end.day < min(start.day, 28):
            months -= 1
        return max(1, months)

    def _gate(
        self, deal, amendment: Amendment, applied_by, override_reason: str | None
    ) -> AmendmentApplied | None:
        """Re-test the position at the amended terms.

        Returns None when the amendment may proceed, and a refusal otherwise.
        The check run is written either way, because the question afterwards
        is what the terms were tested against, and an amendment with no
        evidence is one somebody has to take on trust.
        """
        principal = amendment.new_principal_pence or deal.principal_pence
        rate = amendment.new_rate_bp or deal.rate_bp
        maturity = amendment.new_maturity_date or deal.maturity_date
        if amendment.type == "BREAK":
            maturity = amendment.effective_date
        tenor = (
            self._tenor_months(deal.value_date, maturity)
            if maturity
            else deal.tenor_months
        )

        evaluation = CheckEngine(
            self.session, self.tenant_id, self.as_of_date, self.policy
        ).run(
            deal.counterparty_id,
            deal.instrument,
            principal,
            tenor,
            rate,
            # The deal is being amended, not added alongside itself. Without
            # this its current position is counted twice and an amendment
            # that reduces the principal can fail.
            exclude_deal_id=deal.id,
        )
        result = evaluation.result
        failed = result.outcome == "FAIL"

        overriding = False
        if failed and override_reason:
            if self.policy.enforcement == "HARD_BLOCK":
                raise TreasuryError(
                    ErrorCode.OVERRIDE_NOT_ALLOWED,
                    "The policy in force is a hard block. Nothing can be "
                    "overridden. Change the amended terms, or change the policy.",
                    field="override_reason",
                )
            overriding = True

        timestamp = now()
        run_id = new_id("run")
        actor = str(applied_by) if applied_by else amendment.raised_by
        actor_id = getattr(applied_by, "user_id", None) or amendment.raised_by_user_id

        self.session.add(
            CheckRun(
                id=run_id,
                tenant_id=self.tenant_id,
                counterparty_id=deal.counterparty_id,
                deal_id=deal.id,
                purpose="AMENDMENT",
                as_of_date=self.as_of_date,
                limit_id=result.limit_id,
                policy_version_id=self.policy.id,
                outcome="OVERRIDDEN" if overriding else result.outcome,
                failed_count=result.failed_count,
                measured_pence=result.measured_pence,
                measurement_basis=result.measurement_basis,
                required_approver=result.required_approver,
                inputs_json=json.dumps(evaluation.inputs),
                results_json=json.dumps([c.model_dump() for c in result.checks]),
                created_by=actor,
                created_by_user_id=actor_id,
                created_at=timestamp,
            )
        )
        self.session.flush()

        if not failed:
            return None

        first = next(c for c in result.checks if not c.passed)
        detail = first.detail
        if first.resize_to_pence:
            detail += f" {sterling(first.resize_to_pence)} would fit."

        item_id = new_id("exc")
        self.session.add(
            ExceptionItem(
                id=item_id,
                tenant_id=self.tenant_id,
                deal_id=deal.id,
                confirmation_id=None,
                counterparty_id=deal.counterparty_id,
                cause="LIMIT_FAILURE",
                reason_code=first.key,
                detail=detail,
                check_run_id=run_id,
                status="RESOLVED" if overriding else "OPEN",
                resolution="OVERRIDDEN" if overriding else None,
                resolution_reason=override_reason if overriding else None,
                raised_at=timestamp,
                resolved_by=actor if overriding else None,
                resolved_by_user_id=actor_id if overriding else None,
                resolved_at=timestamp if overriding else None,
            )
        )
        self.session.flush()

        if overriding:
            return None

        # The amendment stays RAISED rather than moving to REJECTED. Nothing
        # about it is wrong; the book could not take it. Change the terms and
        # raise another, or resolve the queue item.
        return AmendmentApplied(
            reversed_pence=0,
            reposted_pence=0,
            refused=True,
            refusal_detail=detail,
            queue_item_id=item_id,
        )

    # ------------------------------------------------------------- helpers

    def preview(self, deal_id: str, effective_date: str) -> AmendmentPreview:
        affected = [
            row
            for row in self.accruals.for_deal(deal_id)
            if row.reversal_of is None and row.accrual_date >= effective_date
        ]
        periods = sorted({row.accrual_date[:7] for row in affected})
        return AmendmentPreview(
            accruals_affected=len(affected),
            amount_to_reverse_pence=sum(row.amount_pence for row in affected),
            periods_affected=periods,
            any_period_closed=any(self._is_closed(period) for period in periods),
        )

    # ------------------------------------------------------------- apply

    def apply(
        self,
        amendment_id: str,
        applied_by=None,
        override_reason: str | None = None,
    ) -> AmendmentApplied:
        """Recalculate from the effective date, reverse what was recognised,
        repost at the new terms, and update the deal. One transaction.

        A partial reversal leaves the ledger disagreeing with the deal, so
        nothing here commits on its own: the router commits once, at the end.
        """
        amendment = self.session.get(Amendment, amendment_id)
        if amendment is None or amendment.tenant_id != self.tenant_id:
            raise TreasuryError(
                ErrorCode.DEAL_NOT_FOUND, "That amendment does not exist."
            )
        if amendment.status == "APPLIED":
            raise TreasuryError(ErrorCode.AMENDMENT_ALREADY_APPLIED)

        deal = deal_repo.get(self.session, amendment.deal_id)
        if deal is None:
            raise TreasuryError(ErrorCode.DEAL_NOT_FOUND)

        # The gate. An amendment is a new decision about a position, not a
        # data fix, so it passes the same six checks a booking does.
        #
        # Without this an amendment is the way round the control system: raise
        # a partial drawdown, put the principal up rather than down, and the
        # deal lands at any size with no check run, no queue item and no
        # breach. The correction path in `QueueService` already re-runs the
        # checks on exactly this reasoning. The two paths disagreed, and this
        # is the one that was wrong.
        #
        # Run before anything is reversed, so a refusal leaves the ledger
        # exactly as it was.
        gate = self._gate(deal, amendment, applied_by, override_reason)
        if gate is not None:
            return gate

        preview = self.preview(deal.id, amendment.effective_date)

        # Whether a closed period can be reopened is an accounting policy
        # decision rather than a technical one, and the answer differs by
        # customer. This surfaces it as a distinct refusal rather than
        # deciding it, which is what document 4 recommends.
        closed = [p for p in preview.periods_affected if self._is_closed(p)]
        if closed and not self._may_reopen_closed_periods():
            raise TreasuryError(
                ErrorCode.CLOSED_PERIOD_LOCKED,
                f"This amendment reaches into {', '.join(closed)}, and policy does "
                "not allow a closed period to be reopened.",
            )

        # 1. Take back what was recognised on or after the effective date.
        _count, reversed_pence = self.accruals.reverse_from(
            deal.id, amendment.effective_date, amendment.id
        )

        # 2. Move the deal to its new terms.
        if amendment.new_principal_pence is not None:
            deal.principal_pence = amendment.new_principal_pence
        if amendment.new_rate_bp is not None:
            deal.rate_bp = amendment.new_rate_bp
        if amendment.new_maturity_date is not None:
            deal.maturity_date = amendment.new_maturity_date
        if amendment.type == "BREAK":
            deal.maturity_date = amendment.effective_date
        self.session.flush()

        # 3. Recognise it again at the new terms, from the effective date.
        reposted = self._repost(deal, amendment.effective_date, amendment.id)

        # 4. Journals for both, so the ledger follows the book.
        self.journals.build_from_accruals()

        amendment.status = "APPLIED"
        amendment.applied_at = now()
        self.session.flush()

        return AmendmentApplied(
            reversed_pence=reversed_pence,
            reposted_pence=reposted,
            periods_reopened=closed,
        )

    def _repost(self, deal, effective_date: str, amendment_id: str) -> int:
        """Write the days again at the terms that now apply.

        Each reposted row carries the amendment that produced it, which is
        both the audit trail and what keeps it outside `ux_accrual_day`: that
        index holds one nightly accrual per day, and a correction is not the
        nightly job.
        """
        from datetime import date, timedelta

        from app.measurement import accrued_interest_pence, days_between
        from app.models import Accrual

        last = (
            min(self.as_of_date, deal.maturity_date)
            if deal.maturity_date
            else self.as_of_date
        )
        total_days = days_between(deal.value_date, last)
        if total_days <= 0:
            return 0

        start = date.fromisoformat(deal.value_date)
        live = {
            row.accrual_date
            for row in self.accruals.for_deal(deal.id)
            if row.reversal_of is None
            and not self._has_reversal(deal.id, row.id)
        }

        reposted = 0
        for day in range(1, total_days + 1):
            accrual_date = (start + timedelta(days=day)).isoformat()
            if accrual_date < effective_date or accrual_date in live:
                continue
            cumulative = accrued_interest_pence(
                deal.principal_pence, deal.rate_bp, day
            )
            previous = accrued_interest_pence(
                deal.principal_pence, deal.rate_bp, day - 1
            )
            daily = cumulative - previous
            self.session.add(
                Accrual(
                    id=new_id("acr"),
                    tenant_id=self.tenant_id,
                    deal_id=deal.id,
                    accrual_date=accrual_date,
                    day_count=1,
                    rate_bp=deal.rate_bp,
                    amount_pence=daily,
                    cumulative_pence=cumulative,
                    reversal_of=None,
                    amendment_id=amendment_id,
                    created_at=now(),
                )
            )
            reposted += daily

        self.session.flush()
        return reposted

    def _has_reversal(self, deal_id: str, accrual_id: str) -> bool:
        return any(
            row.reversal_of == accrual_id for row in self.accruals.for_deal(deal_id)
        )

    def _is_closed(self, period: str) -> bool:
        """A period with a posted journal in it is treated as closed.

        Nothing formally closes a period yet. Posting is the closest signal
        there is: once Oracle has the entry, taking it back is a reversal
        rather than a recalculation.
        """
        return (
            self.session.scalars(
                select(Journal)
                .where(Journal.tenant_id == self.tenant_id)
                .where(Journal.period == period)
                .where(Journal.status == "POSTED")
            ).first()
            is not None
        )

    @staticmethod
    def _may_reopen_closed_periods() -> bool:
        """Document 5 lists this as a decision needed at the start of phase
        three, to be settled with the customer's accountants.

        Built as a refusal by default, because refusing something that should
        have been allowed is a conversation, and allowing something that
        should have been refused is a restatement.
        """
        return False

    # -------------------------------------------------------------- reads

    def for_deal(self, deal_id: str) -> list[Amendment]:
        return list(
            self.session.scalars(
                select(Amendment)
                .where(Amendment.deal_id == deal_id)
                .order_by(Amendment.raised_at)
            )
        )
