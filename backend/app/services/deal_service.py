"""Step 4 of the build sequence. The only path that writes a deal.

Six services touch a deal. Exactly one creates or books one, and this is it.
If a recommendation could create a deal, the checks would be optional. If
matching could create one silently, the capture route would be unknowable.

The checks run twice on every booking and the second run is the control.
Between the user's last keystroke and their submit, another user can book a
deal, a rating can move, or the clock can change, and in each case the
browser holds a result that is now wrong. There is no field on the request
for a client supplied verdict, so the control cannot be bypassed by a stale
browser.

The whole of `record` is one transaction: the check run, the deal, and every
queue item. A blocked deal with no queue item is invisible, which is worse
than a deal that was never written.
"""

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.errors import ErrorCode, TreasuryError
from app.formatting import sterling
from app.ids import new_id, now
from app.models import CheckRun, Deal, ExceptionItem, PolicyVersion
from app.repo import counterparties as cp_repo
from app.repo import deals as deal_repo
from app.repo import evidence as evidence_repo
from app.schemas.models import CheckResult
from app.services.check_engine import CheckEngine


@dataclass
class Booking:
    deal: Deal
    result: CheckResult
    queue_item_id: str | None


class DealService:
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
        self.checks = CheckEngine(session, tenant_id, as_of_date, policy)

    # ------------------------------------------------------------ the check

    def check(
        self,
        counterparty_id: str,
        instrument: str,
        principal_pence: int,
        tenor_months: int,
        rate_bp: int,
    ) -> CheckResult:
        """Persists nothing. Called on every pause in typing."""
        self._require_counterparty(counterparty_id)
        return self.checks.run(
            counterparty_id, instrument, principal_pence, tenor_months, rate_bp
        ).result

    # ------------------------------------------------------------- the write

    def record(
        self,
        counterparty_id: str,
        instrument: str,
        principal_pence: int,
        tenor_months: int,
        rate_bp: int,
        proposer,
        override_reason: str | None = None,
        capture_source: str = "KEYED",
        recommendation_id: str | None = None,
    ) -> Booking:
        """Re-run the checks, write the run, then write the deal or block it."""
        self._require_counterparty(counterparty_id)

        evaluation = self.checks.run(
            counterparty_id, instrument, principal_pence, tenor_months, rate_bp
        )
        result = evaluation.result
        failed = result.outcome == "FAIL"

        overriding = False
        if failed and override_reason:
            if self.policy.enforcement == "HARD_BLOCK":
                # Shipping both as a policy setting is what takes this
                # decision off the critical path. Under a hard block there is
                # nothing to override, and saying so is better than silently
                # ignoring the reason the user typed.
                raise TreasuryError(
                    ErrorCode.OVERRIDE_NOT_ALLOWED,
                    "The policy in force is a hard block. Nothing can be overridden. "
                    "Resize the deal, reroute it, or change the policy.",
                    field="override_reason",
                )
            overriding = True

        maturity = self._maturity_date(tenor_months)
        deal_id = new_id("dl")
        check_run_id = new_id("run")
        timestamp = now()

        blocked = failed and not overriding
        deal = Deal(
            id=deal_id,
            tenant_id=self.tenant_id,
            counterparty_id=counterparty_id,
            instrument=instrument,
            principal_pence=principal_pence,
            currency="GBP",
            rate_bp=rate_bp,
            tenor_months=tenor_months,
            trade_date=self.as_of_date,
            value_date=self.as_of_date,
            maturity_date=maturity,
            status="BLOCKED" if blocked else "PROPOSED",
            capture_source=capture_source,
            created_by=str(proposer),
            created_by_user_id=proposer.user_id,
            created_at=timestamp,
            # Recorded at booking, so the deal names the versions it was
            # tested against rather than the versions that happen to be
            # current when somebody later asks.
            required_approver=self.checks.approvals.required_approver(principal_pence),
            limit_id_at_booking=result.limit_id,
            policy_version_id=self.policy.id,
            check_run_id=check_run_id,
        )
        self.session.add(deal)
        # The deal is written first because the check run points at it, and
        # these models carry foreign keys without ORM relationships, so
        # nothing orders the inserts for us. Both still commit together: the
        # transaction boundary is the whole of `record`, not each flush.
        self.session.flush()

        self.session.add(
            CheckRun(
                id=check_run_id,
                tenant_id=self.tenant_id,
                counterparty_id=counterparty_id,
                deal_id=deal_id,
                purpose="BOOKING",
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
                created_by=str(proposer),
                created_by_user_id=proposer.user_id,
                created_at=timestamp,
            )
        )
        self.session.flush()

        queue_item_id = None
        if failed:
            queue_item_id = self._raise_queue_item(
                deal=deal,
                result=result,
                proposer=proposer,
                overriding=overriding,
                override_reason=override_reason,
                timestamp=timestamp,
            )

        if recommendation_id and not blocked:
            self._link_recommendation(recommendation_id, deal)

        if not blocked:
            # A confirmation can arrive before the deal is keyed. Without
            # this, one that beat the deal would sit unmatched for ever and
            # somebody would have to notice.
            self._match_waiting_confirmation(deal)

        self.session.flush()
        result.check_run_id = check_run_id
        if overriding:
            result.outcome = "OVERRIDDEN"
        return Booking(deal=deal, result=result, queue_item_id=queue_item_id)

    def _match_waiting_confirmation(self, deal: Deal) -> None:
        """The out of order case. Document 5 makes it an exit criterion."""
        from app.services.match_service import MatchService

        MatchService(
            self.session, self.tenant_id, self.as_of_date
        ).rematch_unmatched_for(deal)

    def _link_recommendation(self, recommendation_id: str, deal: Deal) -> None:
        """The dashed edge, and the only place it is written.

        A recommendation may carry a deal_id only for a deal that passed the
        six checks. The advisory layer cannot set this, because it never sees
        a deal; the deal endpoint sets it afterwards, and only once the deal
        exists. Nothing is recorded because a model suggested it.
        """
        from app.models import Recommendation

        recommendation = self.session.get(Recommendation, recommendation_id)
        if recommendation is None:
            return
        recommendation.deal_id = deal.id

    # ---------------------------------------------------------- the signature

    def approve(self, deal_id: str, signer, role: str) -> Deal:
        """Record the signature and put the deal on the book.

        Three refusals, all of which were impossible before phase 1.5 because
        there was no identity to compare against.

        The signer must not be the proposer. One person doing both is not a
        control, it is a person, and the advisory layer in phase two would
        have doubled the hole by letting the same person accept a
        recommendation and then approve the deal it produced.

        The signer must hold the role they are signing under, and the role
        must be the one the amount requires. The approval router named a role
        from the thresholds in the policy version; until now nothing checked
        that the caller held it.

        And the checks run again. A deal proposed this morning and signed
        this afternoon has sat outside the gate in between, during which a
        rating can move or another deal can take the headroom. Approving is
        the moment it goes on the book, so it is the moment that has to be
        true.
        """
        deal = deal_repo.get(self.session, deal_id)
        if deal is None or deal.tenant_id != self.tenant_id:
            raise TreasuryError(ErrorCode.DEAL_NOT_FOUND)
        if deal.approved_at is not None:
            raise TreasuryError(ErrorCode.DEAL_ALREADY_APPROVED)

        if deal.created_by_user_id and deal.created_by_user_id == signer.user_id:
            raise TreasuryError(
                ErrorCode.SEGREGATION_OF_DUTIES,
                f"{signer.display_name} proposed this deal, so somebody else "
                "has to sign it.",
            )

        required = self.checks.approvals.required_approver(deal.principal_pence)
        if not signer.holds(role):
            raise TreasuryError(
                ErrorCode.ROLE_NOT_HELD,
                f"{signer.display_name} does not hold {role.replace('_', ' ').lower()}.",
                field="role",
            )
        if not self.checks.approvals.may_sign(role, deal.principal_pence):
            raise TreasuryError(
                ErrorCode.ROLE_NOT_HELD,
                f"{sterling(deal.principal_pence)} needs "
                f"{self.checks.approvals.phrase(required).lower()} to sign.",
                field="role",
            )
        if deal.status == "BLOCKED":
            outstanding = evidence_repo.open_items_for_deal(self.session, deal_id)
            if outstanding:
                raise TreasuryError(
                    ErrorCode.DEAL_NOT_APPROVED,
                    "This deal is blocked and its queue item is still open. "
                    "Resolve the exception before signing.",
                )
        if deal.status not in ("PROPOSED", "BLOCKED"):
            raise TreasuryError(
                ErrorCode.DEAL_NOT_APPROVED,
                f"A deal that is {deal.status.lower()} cannot be signed.",
            )

        # The control, a second time. Between proposing and signing, a rating
        # can move or another deal can take the headroom, and signing is the
        # moment the deal goes on the book.
        recheck = self.checks.run(
            deal.counterparty_id,
            deal.instrument,
            deal.principal_pence,
            deal.tenor_months,
            deal.rate_bp,
            exclude_deal_id=deal.id,
        )
        if recheck.result.outcome == "FAIL" and deal.status != "BLOCKED":
            raise TreasuryError(
                ErrorCode.CHECK_INPUTS_UNAVAILABLE,
                f"The world moved since this was proposed. {recheck.result.verdict} "
                "Propose it again against the book as it is now.",
            )

        deal.approved_by = signer.display_name
        deal.approved_by_user_id = signer.user_id
        deal.approved_at = now()
        deal.approved_role = role
        deal.status = "ACTIVE"
        self.session.flush()
        return deal

    def instruct(self, deal_id: str, instructed_by):
        """Hand a payment instruction to Oracle. Written to a table, not sent.

        Interface I-4. The platform describes what should happen and hands
        over; nothing here depends on the handover succeeding.
        """
        from app.models import OracleInstruction

        deal = deal_repo.get(self.session, deal_id)
        if deal is None or deal.tenant_id != self.tenant_id:
            raise TreasuryError(ErrorCode.DEAL_NOT_FOUND)
        if deal.status != "ACTIVE" or deal.approved_at is None:
            raise TreasuryError(ErrorCode.DEAL_NOT_APPROVED)
        if deal.instructed_at is not None:
            raise TreasuryError(ErrorCode.DEAL_ALREADY_INSTRUCTED)

        instruction = OracleInstruction(
            id=new_id("ins"),
            tenant_id=self.tenant_id,
            deal_id=deal.id,
            type="PAYMENT_REQUEST",
            amount_pence=deal.principal_pence,
            currency=deal.currency,
            value_date=deal.value_date,
            status="PENDING",
            payload=json.dumps(
                {
                    "deal_id": deal.id,
                    "counterparty_id": deal.counterparty_id,
                    "amount_pence": deal.principal_pence,
                    "value_date": deal.value_date,
                }
            ),
            created_by=str(instructed_by),
            created_by_user_id=instructed_by.user_id,
            created_at=now(),
        )
        self.session.add(instruction)
        deal.instructed_at = instruction.created_at
        self.session.flush()
        return instruction

    # ------------------------------------------------------------- internals

    def _require_counterparty(self, counterparty_id: str) -> None:
        counterparty = cp_repo.get(self.session, counterparty_id)
        if counterparty is None or counterparty.tenant_id != self.tenant_id:
            raise TreasuryError(
                ErrorCode.COUNTERPARTY_NOT_FOUND, field="counterparty_id"
            )

    def _maturity_date(self, tenor_months: int) -> str:
        from datetime import date

        start = date.fromisoformat(self.as_of_date)
        year, month = divmod(start.month - 1 + tenor_months, 12)
        return date(start.year + year, month + 1, min(start.day, 28)).isoformat()

    def _raise_queue_item(
        self,
        deal: Deal,
        result: CheckResult,
        proposer,
        overriding: bool,
        override_reason: str | None,
        timestamp: str,
    ) -> str:
        """One queue item per blocked deal, carrying the reason code of the
        first check that failed and the arithmetic behind it."""
        first_failure = next(c for c in result.checks if not c.passed)
        item_id = new_id("exc")
        detail = first_failure.detail
        if first_failure.resize_to_pence:
            detail += f" {sterling(first_failure.resize_to_pence)} would fit."

        self.session.add(
            ExceptionItem(
                id=item_id,
                tenant_id=self.tenant_id,
                deal_id=deal.id,
                confirmation_id=None,
                counterparty_id=deal.counterparty_id,
                cause="LIMIT_FAILURE",
                reason_code=first_failure.key,
                detail=detail,
                check_run_id=deal.check_run_id,
                # An override decided at the ticket is a decision already
                # taken, so the item is recorded resolved rather than left
                # open for somebody to resolve a second time. The row still
                # exists, because the reason is the evidence.
                status="RESOLVED" if overriding else "OPEN",
                resolution="OVERRIDDEN" if overriding else None,
                resolution_reason=override_reason if overriding else None,
                raised_at=timestamp,
                resolved_by=str(proposer) if overriding else None,
                resolved_by_user_id=proposer.user_id if overriding else None,
                resolved_at=timestamp if overriding else None,
            )
        )
        return item_id
