"""Phase 2. What was recognised, per deal, per day.

The one place in the system where a computed figure is stored, and the
exception is deliberate. Exposure answers what is true now, and recomputing
it is the only way to be sure it agrees with the deals behind it. An accrual
answers what was recognised on the third of October, which is a historic
fact that a later recomputation would quietly rewrite. Once a journal has
been posted against it, changing it is a reversal rather than a
recalculation.

Two properties this file has to hold.

The daily figures sum to the measured accrual. Each day is written as the
difference between the interest accrued to that day and to the day before,
both from `app.measurement`. So the cumulative on any row equals what
ExposureCalculator measures on the same date, by construction rather than by
coincidence, and the two cannot drift as rounding accumulates.

Running it twice for one date writes once. The partial unique index does the
enforcing; this service does the asking, so a second run is quiet rather
than an error.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id, now
from app.measurement import accrued_interest_pence, days_between
from app.models import Accrual, Deal
from app.repo import deals as deal_repo

#: Interest accrues on these. A forward is revalued rather than accrued, and
#: revaluation is a different journal type that phase two does not build.
ACCRUING_INSTRUMENTS = ("DEPOSIT", "MMF", "GILT")


@dataclass
class AccrualRun:
    as_of_date: str
    deals_considered: int
    rows_written: int
    rows_already_present: int
    amount_pence: int


class AccrualService:
    def __init__(self, session: Session, tenant_id: str, as_of_date: str) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.as_of_date = as_of_date

    # ------------------------------------------------------------ the job

    def accrue_to_date(self, as_of_date: str | None = None) -> AccrualRun:
        """Bring every live position up to date.

        Catches up rather than assuming yesterday ran: a deal booked a week
        ago on a system nobody ran the job on gets seven rows, each carrying
        the rate that applied on its own day.
        """
        target = as_of_date or self.as_of_date
        written = 0
        present = 0
        total = 0
        deals = [
            deal
            for deal in deal_repo.live_for_tenant(self.session, self.tenant_id)
            if deal.instrument in ACCRUING_INSTRUMENTS
        ]

        for deal in deals:
            rows, skipped, amount = self._accrue_one(deal, target)
            written += rows
            present += skipped
            total += amount

        self.session.flush()
        return AccrualRun(
            as_of_date=target,
            deals_considered=len(deals),
            rows_written=written,
            rows_already_present=present,
            amount_pence=total,
        )

    def _accrue_one(self, deal: Deal, target: str) -> tuple[int, int, int]:
        last = min(target, deal.maturity_date) if deal.maturity_date else target
        total_days = days_between(deal.value_date, last)
        if total_days <= 0:
            return 0, 0, 0

        existing = {
            row.accrual_date
            for row in self.session.scalars(
                select(Accrual)
                .where(Accrual.deal_id == deal.id)
                .where(Accrual.reversal_of.is_(None))
            )
        }

        start = date.fromisoformat(deal.value_date)
        written = 0
        skipped = 0
        amount = 0

        for day in range(1, total_days + 1):
            accrual_date = (start + timedelta(days=day)).isoformat()
            if accrual_date in existing:
                skipped += 1
                continue

            cumulative = accrued_interest_pence(deal.principal_pence, deal.rate_bp, day)
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
                    amendment_id=None,
                    created_at=now(),
                )
            )
            written += 1
            amount += daily

        return written, skipped, amount

    # ------------------------------------------------------------- reads

    def for_deal(self, deal_id: str) -> list[Accrual]:
        return list(
            self.session.scalars(
                select(Accrual)
                .where(Accrual.deal_id == deal_id)
                .order_by(Accrual.accrual_date, Accrual.id)
            )
        )

    def summary_for_deal(self, deal_id: str) -> tuple[int | None, int]:
        """Today's figure and the running total.

        The blotter shows the first under the stage label and the deal panel
        shows the second. Reversals are included in the total and excluded
        from today, because a reversal is not something that was earned
        today.
        """
        rows = self.for_deal(deal_id)
        if not rows:
            return None, 0
        cumulative = sum(row.amount_pence for row in rows)
        today = next(
            (
                row.amount_pence
                for row in rows
                if row.accrual_date == self.as_of_date and row.reversal_of is None
            ),
            None,
        )
        return today, cumulative

    def daily_by_deal(self) -> dict[str, tuple[int | None, int]]:
        """One pass for the whole blotter, rather than one query per row."""
        rows = self.session.scalars(
            select(Accrual).where(Accrual.tenant_id == self.tenant_id)
        )
        totals: dict[str, int] = {}
        today: dict[str, int] = {}
        for row in rows:
            totals[row.deal_id] = totals.get(row.deal_id, 0) + row.amount_pence
            if row.accrual_date == self.as_of_date and row.reversal_of is None:
                today[row.deal_id] = row.amount_pence
        return {
            deal_id: (today.get(deal_id), total) for deal_id, total in totals.items()
        }

    # --------------------------------------------------------- reversals

    def reverse_from(
        self, deal_id: str, effective_date: str, amendment_id: str
    ) -> tuple[int, int]:
        """Take back what was recognised on or after a date.

        Recalculating is the easy half. Knowing what was already recognised
        is the hard half, and it is only possible because accrual is stored
        per day rather than computed on read.

        Nothing is edited. Each reversal is its own row, negative, carrying
        the accrual it reverses and the amendment that caused it, so the
        original stays readable and the ledger can be walked either way.

        Used by AmendmentService in phase three. It is here because it is
        accrual arithmetic, and putting it there would be a second place that
        knows how an accrual is shaped.
        """
        originals = [
            row
            for row in self.for_deal(deal_id)
            if row.reversal_of is None and row.accrual_date >= effective_date
        ]
        reversed_pence = 0
        for original in originals:
            already = any(
                row.reversal_of == original.id for row in self.for_deal(deal_id)
            )
            if already:
                continue
            self.session.add(
                Accrual(
                    id=new_id("acr"),
                    tenant_id=self.tenant_id,
                    deal_id=deal_id,
                    accrual_date=original.accrual_date,
                    day_count=original.day_count,
                    rate_bp=original.rate_bp,
                    amount_pence=-original.amount_pence,
                    cumulative_pence=0,
                    reversal_of=original.id,
                    amendment_id=amendment_id,
                    created_at=now(),
                )
            )
            reversed_pence += original.amount_pence

        self.session.flush()
        return len(originals), reversed_pence
