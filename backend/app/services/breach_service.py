"""Step 5 of the build sequence, second half. Breaches.

A breach is a position that was compliant when it was booked and is not
compliant now. Nobody made a mistake. The world moved.

Responding to a breach records a decision. It does not clear the breach and
it does not change the deal, because the position is still outside policy.
That is the one thing about this service that is easy to get wrong and
expensive to explain afterwards.
"""

from sqlalchemy.orm import Session

from app.errors import ErrorCode, TreasuryError
from app.ids import new_id, now
from app.models import Breach
from app.repo import evidence as evidence_repo

#: Which breach a failed check produces. The keys are check keys, so adding
#: a seventh check without deciding what its breach is called will fail here
#: rather than silently produce nothing.
BREACH_TYPE_FOR_CHECK = {
    "ENTITY_LIMIT": "AMOUNT",
    "GROUP_LIMIT": "GROUP",
    "TENOR_BAND": "TENOR",
    "CONCENTRATION": "CONCENTRATION",
    "COUNTERPARTY_ACTIVE": "RATING",
    "INSTRUMENT_PERMITTED": "RATING",
}

RESPONSES = (
    "HOLD_TO_MATURITY",
    "BREAK_EARLY",
    "SEEK_RATIFICATION",
    "REDUCE_ON_ROLL",
)


class BreachService:
    def __init__(self, session: Session, tenant_id: str) -> None:
        self.session = session
        self.tenant_id = tenant_id

    def list_all(self) -> list[Breach]:
        return evidence_repo.breaches(self.session, self.tenant_id)

    def outstanding_count(self) -> int:
        return evidence_repo.outstanding_breach_count(self.session, self.tenant_id)

    def raise_breach(
        self,
        counterparty_id: str,
        deal_id: str | None,
        check_key: str,
        detail: str,
        limit_id: str | None,
        rating_event_id: str | None,
        original_check_run_id: str | None,
    ) -> Breach:
        breach = Breach(
            id=new_id("brc"),
            tenant_id=self.tenant_id,
            counterparty_id=counterparty_id,
            deal_id=deal_id,
            type=BREACH_TYPE_FOR_CHECK[check_key],
            detail=detail,
            limit_id=limit_id,
            rating_event_id=rating_event_id,
            original_check_run_id=original_check_run_id,
            status="OPEN",
            raised_at=now(),
        )
        self.session.add(breach)
        return breach

    def respond(
        self, breach_id: str, response: str, responded_by, reason: str | None
    ) -> Breach:
        breach = evidence_repo.get_breach(self.session, breach_id)
        if breach is None or breach.tenant_id != self.tenant_id:
            raise TreasuryError(ErrorCode.BREACH_NOT_FOUND)
        if response not in RESPONSES:
            raise TreasuryError(
                ErrorCode.BREACH_NOT_FOUND,
                f"{response} is not one of the four responses.",
                field="response",
            )

        breach.response = response
        breach.response_reason = reason
        breach.responded_by = str(responded_by)
        breach.responded_by_user_id = responded_by.user_id
        breach.responded_at = now()
        # RESPONDED records that somebody decided. It is not CLEARED, and
        # there is no state that is: nothing in phase one takes a position
        # back inside policy, so the count in the strip does not fall when
        # this is called. A count that dropped on a response would say the
        # problem had gone away when only the conversation had.
        breach.status = "RESPONDED"
        self.session.flush()
        return breach
