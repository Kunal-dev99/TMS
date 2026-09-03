"""Phase 3. Confirmations, and matching them to deals.

The whole value of matching is that the two records arrive by different
routes. One is what we think we traded; the other is what the counterparty
thinks. Interface I-12 is kept separate from I-1 deliberately: fold the
confirmation into the deal feed and there is nothing to match against, so the
control disappears.

Three things this file has to get right.

A confirmation that arrives before the deal is keyed is not an error. It
waits, unmatched, and matches when the deal appears. That is also the route
by which a deal can be created from a confirmation rather than keyed, which
removes the keying error rather than catching it later.

A confirmation may only match a deal for the same counterparty and the same
instrument. Document 1 lists this as an invariant the schema cannot hold,
because it is a cross row comparison, so it lives here.

The comparison is field by field rather than record against record, so a
mismatch can say the rate was keyed at 4.30 and confirmed at 4.28 rather
than reporting that something differs.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ErrorCode, TreasuryError
from app.formatting import deal_rate, sterling
from app.ids import new_id, now
from app.models import Confirmation, Deal, ExceptionItem, MatchDifference
from app.repo import deals as deal_repo

#: The fields compared, and how each is put into a sentence. Adding a field
#: here is the whole of adding it to matching.
#:
#: Each renderer takes the value and the deal's instrument, because `rate_bp`
#: cannot be read without knowing which instrument it belongs to. The others
#: ignore it rather than having two shapes of renderer to keep straight.
COMPARED = {
    "principal_pence": ("principal", lambda v, _i: sterling(v)),
    "rate_bp": ("rate", deal_rate),
    "value_date": ("value date", lambda v, _i: str(v)),
    "maturity_date": ("maturity date", lambda v, _i: str(v) if v else "none"),
    "instrument": ("instrument", lambda v, _i: str(v).replace("_", " ").lower()),
}


@dataclass
class MatchOutcome:
    confirmation: Confirmation
    differences: list[MatchDifference] = field(default_factory=list)
    queue_item_id: str | None = None
    created: bool = True


class MatchService:
    def __init__(self, session: Session, tenant_id: str, as_of_date: str) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.as_of_date = as_of_date

    # ---------------------------------------------------------- ingestion

    def ingest(
        self,
        message_type: str,
        reference: str,
        instrument: str,
        principal_pence: int,
        rate_bp: int,
        value_date: str,
        maturity_date: str | None = None,
        counterparty_id: str | None = None,
        raw_payload: str | None = None,
    ) -> MatchOutcome:
        """Store it, then try to match it. Stored whatever the outcome.

        Deduplicated by counterparty and reference: a repeat returns the
        existing confirmation rather than a second one, because a feed that
        redelivers is a feed, not a second trade.
        """
        if message_type not in (
            "MT300",
            "MT320",
            "MT535",
            "MT536",
            "BROKER_NOTE",
            "DOCUMENT",
        ):
            raise TreasuryError(ErrorCode.UNKNOWN_MESSAGE_TYPE, field="message_type")

        existing = self.session.scalars(
            select(Confirmation)
            .where(Confirmation.tenant_id == self.tenant_id)
            .where(Confirmation.reference == reference)
            .where(Confirmation.counterparty_id == counterparty_id)
        ).one_or_none()
        if existing is not None:
            return MatchOutcome(
                confirmation=existing,
                differences=self.differences_for(existing.id),
                created=False,
            )

        confirmation = Confirmation(
            id=new_id("cnf"),
            tenant_id=self.tenant_id,
            deal_id=None,
            counterparty_id=counterparty_id,
            message_type=message_type,
            reference=reference,
            instrument=instrument,
            principal_pence=principal_pence,
            rate_bp=rate_bp,
            value_date=value_date,
            maturity_date=maturity_date,
            received_at=now(),
            match_status="UNMATCHED",
            raw_payload=raw_payload,
        )
        self.session.add(confirmation)
        self.session.flush()

        return self.attempt_match(confirmation)

    # ----------------------------------------------------------- matching

    def attempt_match(self, confirmation: Confirmation) -> MatchOutcome:
        """Find the deal this belongs to, if it has arrived yet.

        An unmatched confirmation is not an error. It means the deal has not
        been keyed, and the confirmation waits.
        """
        candidate = self._find_deal(confirmation)
        if candidate is None:
            return MatchOutcome(confirmation=confirmation, differences=[])
        return self.match_to(confirmation, candidate)

    def match_to(self, confirmation: Confirmation, deal: Deal) -> MatchOutcome:
        """Compare field by field and record what disagreed."""
        if confirmation.match_status == "MATCHED":
            raise TreasuryError(ErrorCode.ALREADY_MATCHED)

        # The invariant the schema cannot hold. A confirmation may only match
        # a deal for the same counterparty and instrument, and letting it
        # match anything else would make the control meaningless.
        if (
            confirmation.counterparty_id
            and confirmation.counterparty_id != deal.counterparty_id
        ):
            raise TreasuryError(
                ErrorCode.CONFIRMATION_NOT_FOUND,
                "A confirmation may only match a deal for the same counterparty.",
                field="deal_id",
            )
        if confirmation.instrument != deal.instrument:
            raise TreasuryError(
                ErrorCode.CONFIRMATION_NOT_FOUND,
                "A confirmation may only match a deal for the same instrument.",
                field="deal_id",
            )

        differences = self._compare(confirmation, deal)
        confirmation.deal_id = deal.id
        confirmation.counterparty_id = deal.counterparty_id
        confirmation.matched_at = now()
        confirmation.match_status = "MISMATCHED" if differences else "MATCHED"

        for difference in differences:
            self.session.add(difference)
        self.session.flush()

        queue_item_id = None
        if differences:
            queue_item_id = self._raise_queue_item(confirmation, deal, differences)

        self.session.flush()
        return MatchOutcome(
            confirmation=confirmation,
            differences=differences,
            queue_item_id=queue_item_id,
        )

    def rematch_unmatched_for(self, deal: Deal) -> MatchOutcome | None:
        """Called when a deal is keyed, in case its confirmation got here
        first.

        This is the out of order case, and it is the one document 5 makes an
        exit criterion. Without it, a confirmation that beat the deal would
        sit unmatched for ever and somebody would have to notice.
        """
        waiting = self.session.scalars(
            select(Confirmation)
            .where(Confirmation.tenant_id == self.tenant_id)
            .where(Confirmation.deal_id.is_(None))
            .where(Confirmation.match_status == "UNMATCHED")
            .where(Confirmation.instrument == deal.instrument)
            .order_by(Confirmation.received_at)
        )
        for confirmation in waiting:
            if (
                confirmation.counterparty_id
                and confirmation.counterparty_id != deal.counterparty_id
            ):
                continue
            return self.match_to(confirmation, deal)
        return None

    # ---------------------------------------------------------- internals

    def _find_deal(self, confirmation: Confirmation) -> Deal | None:
        """Matches on counterparty and instrument, then on the closest terms.

        Deliberately narrow. A confirmation that cannot be resolved waits
        rather than being attached to the nearest thing, because a wrong
        match is worse than no match: it closes the control while looking
        like it worked.
        """
        if confirmation.counterparty_id is None:
            return None

        candidates = [
            deal
            for deal in deal_repo.live_for_counterparty(
                self.session, confirmation.counterparty_id
            )
            if deal.instrument == confirmation.instrument
            and not self._already_confirmed(deal.id)
        ]
        if not candidates:
            return None

        exact = [
            deal
            for deal in candidates
            if deal.principal_pence == confirmation.principal_pence
            and deal.value_date == confirmation.value_date
        ]
        if exact:
            return exact[0]

        # Fall back to the same value date, which is the field a bank is
        # least likely to disagree about, so what is left to differ is the
        # rate or the amount, and those are worth showing.
        same_day = [
            deal for deal in candidates if deal.value_date == confirmation.value_date
        ]
        return same_day[0] if same_day else None

    def _already_confirmed(self, deal_id: str) -> bool:
        return (
            self.session.scalars(
                select(Confirmation).where(Confirmation.deal_id == deal_id)
            ).first()
            is not None
        )

    def _compare(
        self, confirmation: Confirmation, deal: Deal
    ) -> list[MatchDifference]:
        differences = []
        for field_name, (_label, render) in COMPARED.items():
            keyed = getattr(deal, field_name)
            confirmed = getattr(confirmation, field_name)
            if keyed == confirmed:
                continue
            differences.append(
                MatchDifference(
                    id=new_id("mdf"),
                    confirmation_id=confirmation.id,
                    field_name=field_name,
                    keyed_value=render(keyed, deal.instrument),
                    confirmed_value=render(confirmed, deal.instrument),
                )
            )
        return differences

    def _raise_queue_item(
        self, confirmation: Confirmation, deal: Deal, differences: list
    ) -> str:
        """The second cause of the one queue.

        A limit failure happens before the deal exists and is resolved by
        changing the deal. A mismatch happens after it exists and is resolved
        by agreeing what was actually traded.
        """
        first = differences[0]
        label = COMPARED[first.field_name][0]
        item_id = new_id("exc")
        self.session.add(
            ExceptionItem(
                id=item_id,
                tenant_id=self.tenant_id,
                deal_id=deal.id,
                confirmation_id=confirmation.id,
                counterparty_id=deal.counterparty_id,
                cause="CONFIRMATION_MISMATCH",
                reason_code=first.field_name.upper(),
                detail=(
                    f"The {label} was keyed at {first.keyed_value} and confirmed "
                    f"at {first.confirmed_value}."
                    + (
                        f" {len(differences) - 1} other field disagrees."
                        if len(differences) == 2
                        else f" {len(differences) - 1} other fields disagree."
                        if len(differences) > 2
                        else ""
                    )
                ),
                check_run_id=None,
                status="OPEN",
                raised_at=now(),
            )
        )
        return item_id

    # -------------------------------------------------------------- reads

    def differences_for(self, confirmation_id: str) -> list[MatchDifference]:
        return list(
            self.session.scalars(
                select(MatchDifference).where(
                    MatchDifference.confirmation_id == confirmation_id
                )
            )
        )

    def get(self, confirmation_id: str) -> Confirmation:
        confirmation = self.session.get(Confirmation, confirmation_id)
        if confirmation is None or confirmation.tenant_id != self.tenant_id:
            raise TreasuryError(ErrorCode.CONFIRMATION_NOT_FOUND)
        return confirmation

    def for_deal(self, deal_id: str) -> Confirmation | None:
        return self.session.scalars(
            select(Confirmation).where(Confirmation.deal_id == deal_id)
        ).first()

    def list_confirmations(self, match_status: str | None = None):
        statement = select(Confirmation).where(Confirmation.tenant_id == self.tenant_id)
        if match_status:
            statement = statement.where(Confirmation.match_status == match_status)
        return list(
            self.session.scalars(statement.order_by(Confirmation.received_at.desc()))
        )
