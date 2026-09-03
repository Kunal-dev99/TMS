"""Step 5 of the build sequence, first half. One queue, two causes.

A limit failure happens before the deal exists and is resolved by changing
the deal. A confirmation mismatch happens after it exists and is resolved by
agreeing what was actually traded. They share one strip entry, which is what
keeps the navigation budget at five.

All six resolutions are reachable since phase three. Two of them belong to
the confirmation cause and are refused against a limit failure, because
applying a mismatch resolution to a limit failure is a defect rather than a
preference.
"""

from sqlalchemy.orm import Session

from app.errors import ErrorCode, TreasuryError
from app.ids import now
from app.models import ExceptionItem, PolicyVersion
from app.repo import deals as deal_repo
from app.repo import evidence as evidence_repo

#: Which cause each resolution belongs to. Applying a mismatch resolution to
#: a limit failure is a defect, not a preference.
RESOLUTIONS = {
    "RESIZED": "LIMIT_FAILURE",
    "REROUTED": "LIMIT_FAILURE",
    "OVERRIDDEN": "LIMIT_FAILURE",
    "CANCELLED": None,  # either cause
    "CORRECTED": "CONFIRMATION_MISMATCH",
    "CHALLENGED": "CONFIRMATION_MISMATCH",
}


class QueueService:
    def __init__(
        self,
        session: Session,
        tenant_id: str,
        policy: PolicyVersion,
        as_of_date: str | None = None,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.policy = policy
        self.as_of_date = as_of_date or ""

    def open_items(self) -> list[ExceptionItem]:
        return evidence_repo.open_queue_items(self.session, self.tenant_id)

    def counts(self) -> dict[str, int]:
        return evidence_repo.open_queue_counts(self.session, self.tenant_id)

    def resolve(
        self,
        item_id: str,
        resolution: str,
        resolved_by,
        reason: str | None = None,
    ) -> ExceptionItem:
        item = evidence_repo.get_queue_item(self.session, item_id)
        if item is None or item.tenant_id != self.tenant_id:
            raise TreasuryError(ErrorCode.QUEUE_ITEM_NOT_FOUND)
        if item.status == "RESOLVED":
            raise TreasuryError(ErrorCode.QUEUE_ITEM_ALREADY_RESOLVED)

        expected_cause = RESOLUTIONS.get(resolution)
        if expected_cause is not None and expected_cause != item.cause:
            raise TreasuryError(
                ErrorCode.QUEUE_ITEM_NOT_FOUND,
                f"{resolution} resolves a {expected_cause.replace('_', ' ').lower()}. "
                f"This item is a {item.cause.replace('_', ' ').lower()}.",
                field="resolution",
            )

        if resolution == "OVERRIDDEN":
            if self.policy.enforcement == "HARD_BLOCK":
                raise TreasuryError(ErrorCode.OVERRIDE_NOT_ALLOWED)
            if not reason:
                raise TreasuryError(ErrorCode.OVERRIDE_REASON_REQUIRED, field="reason")

        item.status = "RESOLVED"
        item.resolution = resolution
        item.resolution_reason = reason
        item.resolved_by = str(resolved_by)
        item.resolved_by_user_id = resolved_by.user_id
        item.resolved_at = now()

        self._apply_to_deal(item, resolution)
        self.session.flush()
        return item

    def _apply_to_deal(self, item: ExceptionItem, resolution: str) -> None:
        """What the resolution does to the deal behind the item.

        RESIZED and REROUTED cancel this deal, because the client resubmits a
        smaller one or books with a different counterparty. Neither edits the
        deal that failed: a deal that was refused is evidence, and rewriting
        it in place would lose the refusal.
        """
        if item.deal_id is None:
            return
        deal = deal_repo.get(self.session, item.deal_id)
        if deal is None:
            return

        if resolution in ("RESIZED", "REROUTED", "CANCELLED"):
            deal.status = "CANCELLED"
            return

        if resolution == "OVERRIDDEN":
            # Set active only when nothing else is outstanding against it.
            outstanding = [
                other
                for other in evidence_repo.open_items_for_deal(self.session, deal.id)
                if other.id != item.id
            ]
            if not outstanding:
                deal.status = "PROPOSED"

        if resolution == "CORRECTED":
            self._correct_to_confirmation(item, deal)

        if resolution == "CHALLENGED":
            self._challenge(item)

    def _correct_to_confirmation(self, item: ExceptionItem, deal) -> None:
        """The deal takes the confirmed terms, and the checks rerun.

        A corrected rate changes the accrual and can change the measured
        exposure, so this is not a data fix: it is a new decision about a
        position, and it has to pass the gate like any other.

        The check run is written even when it passes, because the question
        afterwards is what the terms were tested against, and a correction
        with no evidence is a correction somebody has to take on trust.
        """
        import json

        from app.ids import new_id, now
        from app.models import CheckRun, Confirmation
        from app.services.check_engine import CheckEngine

        if item.confirmation_id is None:
            return
        confirmation = self.session.get(Confirmation, item.confirmation_id)
        if confirmation is None:
            return

        deal.principal_pence = confirmation.principal_pence
        deal.rate_bp = confirmation.rate_bp
        deal.value_date = confirmation.value_date
        if confirmation.maturity_date:
            deal.maturity_date = confirmation.maturity_date
        self.session.flush()

        evaluation = CheckEngine(
            self.session, self.tenant_id, self.as_of_date, self.policy
        ).run(
            deal.counterparty_id,
            deal.instrument,
            deal.principal_pence,
            deal.tenor_months,
            deal.rate_bp,
            exclude_deal_id=deal.id,
        )
        result = evaluation.result

        run_id = new_id("run")
        self.session.add(
            CheckRun(
                id=run_id,
                tenant_id=self.tenant_id,
                counterparty_id=deal.counterparty_id,
                deal_id=deal.id,
                purpose="CORRECTION",
                as_of_date=self.as_of_date,
                limit_id=result.limit_id,
                policy_version_id=self.policy.id,
                outcome=result.outcome,
                failed_count=result.failed_count,
                measured_pence=result.measured_pence,
                measurement_basis=result.measurement_basis,
                required_approver=result.required_approver,
                inputs_json=json.dumps(evaluation.inputs),
                results_json=json.dumps([c.model_dump() for c in result.checks]),
                created_by=item.resolved_by or "unknown",
                created_by_user_id=item.resolved_by_user_id,
                created_at=now(),
            )
        )
        deal.check_run_id = run_id

        confirmation.match_status = "MATCHED"
        confirmation.matched_at = now()
        self.session.flush()

    def _challenge(self, item: ExceptionItem) -> None:
        """The deal is unchanged and the confirmation is disputed.

        Somebody is talking to the bank, so the item stays open. Closing it
        would say the disagreement was settled when only the conversation had
        started.
        """
        from app.models import Confirmation

        if item.confirmation_id is not None:
            confirmation = self.session.get(Confirmation, item.confirmation_id)
            if confirmation is not None:
                confirmation.match_status = "DISPUTED"

        item.status = "OPEN"
        item.resolved_at = None
        self.session.flush()
