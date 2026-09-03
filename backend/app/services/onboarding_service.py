"""Step 7 of the build sequence. Adding a counterparty.

Four calls, one per step a person performs, and each one separately
refusable. Draft, verified, approved, active. Nothing shortens it, because
the point of the slow loop is that somebody looked at each step.

Independent of the control loop, so it can be built alongside it.

The one refusal worth reading aloud: a limit nobody signed is not a control.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.errors import ErrorCode, TreasuryError
from app.formatting import sterling
from app.ids import new_id, now
from app.models import Counterparty, CounterpartyInstrument, CpGroup, CpLimit
from app.repo import counterparties as cp_repo
from app.repo import policy as policy_repo


@dataclass
class ProposedLimit:
    """What the band entitles this name to, before anybody signs."""

    amount_pence: int
    max_tenor_months: int
    rating: str


class OnboardingService:
    def __init__(self, session: Session, tenant_id: str, as_of_date: str) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.as_of_date = as_of_date

    # 1 ---------------------------------------------------------------------

    def create(
        self, name: str, created_by, group_id: str | None, group_name: str | None
    ) -> Counterparty:
        """Status moves to draft. Nothing can be dealt with yet."""
        if group_id:
            group = cp_repo.group(self.session, group_id)
            if group is None:
                raise TreasuryError(
                    ErrorCode.COUNTERPARTY_NOT_FOUND,
                    "That credit group does not exist.",
                    field="group_id",
                )
        else:
            # A counterparty with no group would sit outside the group check,
            # which is the one check that connects two legal entities. Every
            # name gets a group, even a group of one.
            group = CpGroup(
                id=new_id("grp"),
                tenant_id=self.tenant_id,
                name=group_name or name,
                group_limit_pence=0,
            )
            self.session.add(group)
            self.session.flush()
            group_id = group.id

        counterparty = Counterparty(
            id=new_id("cp"),
            tenant_id=self.tenant_id,
            group_id=group_id,
            name=name,
            rating="BB+",
            rating_status="STABLE",
            status="DRAFT",
            created_by=str(created_by),
            created_by_user_id=created_by.user_id,
            created_at=now(),
        )
        self.session.add(counterparty)
        self.session.flush()
        return counterparty

    # 2 ---------------------------------------------------------------------

    def verify(
        self,
        counterparty_id: str,
        legal_entity_identifier: str,
        group_parent_name: str,
        rating: str,
        country: str,
        instruments: list[str],
        verified_by,
    ) -> tuple[Counterparty, ProposedLimit]:
        """Identifier, group parent, rating, instruments.

        The group parent is the field the whole group check rests on, and it
        comes from a public register rather than from the counterparty.
        """
        counterparty = self._require(counterparty_id)
        if counterparty.status not in ("DRAFT", "VERIFIED"):
            raise TreasuryError(
                ErrorCode.COUNTERPARTY_ALREADY_ACTIVE
                if counterparty.status == "ACTIVE"
                else ErrorCode.COUNTERPARTY_NOT_VERIFIED
            )

        band = policy_repo.band_for_rating(self.session, self.tenant_id, rating)
        if band is None:
            raise TreasuryError(ErrorCode.UNKNOWN_RATING, field="rating")

        counterparty.legal_entity_identifier = legal_entity_identifier
        counterparty.group_parent_name = group_parent_name
        counterparty.rating = rating
        counterparty.country = country
        counterparty.status = "VERIFIED"
        counterparty.verified_by = str(verified_by)
        counterparty.verified_at = now()

        for existing in self.session.query(CounterpartyInstrument).filter(
            CounterpartyInstrument.counterparty_id == counterparty_id
        ):
            existing.enabled = 1 if existing.instrument in instruments else 0

        already = {
            row.instrument
            for row in self.session.query(CounterpartyInstrument).filter(
                CounterpartyInstrument.counterparty_id == counterparty_id
            )
        }
        for instrument in instruments:
            if instrument in already:
                continue
            self.session.add(
                CounterpartyInstrument(
                    id=new_id("cpi"),
                    tenant_id=self.tenant_id,
                    counterparty_id=counterparty_id,
                    instrument=instrument,
                    enabled=1,
                )
            )

        self.session.flush()
        return counterparty, ProposedLimit(
            amount_pence=band.max_limit_pence,
            max_tenor_months=band.max_tenor_months,
            rating=rating,
        )

    # 3 ---------------------------------------------------------------------

    def set_limit(
        self,
        counterparty_id: str,
        amount_pence: int,
        max_tenor_months: int,
        approved_by: str,
        recorded_by,
        reason: str | None,
    ) -> CpLimit:
        """Set the limit and record who signed for it.

        A limit above the band needs a reason as well as an approver. The
        seeded book has exactly one of these, and it is the reason the book
        opens with nothing in breach.
        """
        counterparty = self._require(counterparty_id)
        if counterparty.status == "DRAFT":
            raise TreasuryError(ErrorCode.COUNTERPARTY_NOT_VERIFIED)
        if not approved_by or not approved_by.strip():
            raise TreasuryError(ErrorCode.APPROVER_REQUIRED, field="approved_by")

        band = policy_repo.band_for_rating(
            self.session, self.tenant_id, counterparty.rating
        )
        above_band = band is not None and amount_pence > band.max_limit_pence
        if above_band and not reason:
            raise TreasuryError(
                ErrorCode.LIMIT_REASON_REQUIRED,
                f"{sterling(amount_pence)} is above the "
                f"{sterling(band.max_limit_pence)} ceiling at {counterparty.rating}. "
                "Say why.",
                field="reason",
            )

        timestamp = now()
        current = cp_repo.current_limit(self.session, counterparty_id)
        if current is not None:
            current.superseded_at = timestamp

        limit = CpLimit(
            id=new_id("lim"),
            tenant_id=self.tenant_id,
            counterparty_id=counterparty_id,
            amount_pence=amount_pence,
            max_tenor_months=max_tenor_months,
            source="MANUAL" if above_band or band is None else "BAND",
            effective_from=self.as_of_date,
            superseded_at=None,
            reason=reason,
            approved_by=approved_by,
            recorded_by_user_id=recorded_by.user_id,
            approved_at=timestamp,
        )
        self.session.add(limit)

        counterparty.status = "APPROVED"
        counterparty.approved_by = approved_by
        counterparty.approved_at = timestamp
        self.session.flush()
        return limit

    # 4 ---------------------------------------------------------------------

    def activate(self, counterparty_id: str, activated_by) -> Counterparty:
        """The name appears in the book and in the ticket.

        The boundary between the slow onboarding loop and the fast per deal
        loop. The only thing that puts a name in front of a dealer.
        """
        counterparty = self._require(counterparty_id)
        if counterparty.status == "ACTIVE":
            raise TreasuryError(ErrorCode.COUNTERPARTY_ALREADY_ACTIVE)
        if counterparty.status != "APPROVED":
            raise TreasuryError(ErrorCode.COUNTERPARTY_NOT_APPROVED)
        if cp_repo.current_limit(self.session, counterparty_id) is None:
            raise TreasuryError(ErrorCode.NO_LIMIT_IN_FORCE)

        counterparty.status = "ACTIVE"
        counterparty.activated_by_user_id = activated_by.user_id
        counterparty.activated_at = now()
        self.session.flush()
        return counterparty

    # -----------------------------------------------------------------------

    def _require(self, counterparty_id: str) -> Counterparty:
        counterparty = cp_repo.get(self.session, counterparty_id)
        if counterparty is None or counterparty.tenant_id != self.tenant_id:
            raise TreasuryError(ErrorCode.COUNTERPARTY_NOT_FOUND)
        return counterparty
