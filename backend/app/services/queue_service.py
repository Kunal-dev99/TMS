"""Step 5 of the build sequence, first half. One queue, two causes.

A limit failure happens before the deal exists and is resolved by changing
the deal. A confirmation mismatch happens after it exists and is resolved by
agreeing what was actually traded. They share one strip entry, which is what
keeps the navigation budget at five.

Two of the six resolutions belong to a cause that arrives in phase three.
They are here because the enumeration is part of the contract, and an
unreachable code is either dead or a rule that is not being enforced.
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
        self, session: Session, tenant_id: str, policy: PolicyVersion
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.policy = policy

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

        # CORRECTED and CHALLENGED belong to the confirmation cause, which
        # arrives in phase three with MatchService.
