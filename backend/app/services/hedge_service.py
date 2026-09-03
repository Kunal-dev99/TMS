"""Phase 3. Currency exposure and hedging.

Two different things are called exposure, and document 1 calls confusing them
the single most likely modelling mistake in the whole system. The defence is
structural, and this file has to keep its half of it:

  Different tables. Counterparty exposure has no table; it is computed from
  deal rows. Currency exposure has its own.
  Different units. That one is pence. This one is minor units with an
  explicit currency on every figure.
  Different names. Nothing here is called exposure without a qualifier.
  No query joins them. `currency_exposure` has no `counterparty_id`, because
  an obligation to a supplier is not an obligation to a bank.

A forward increases counterparty exposure and reduces currency exposure. A
combined figure would be meaningless in the best case and misleading in the
worst, which is why there is no method here that returns both and no endpoint
that asks for one.

The link is the step that makes it hedging rather than owning forwards.
Without it you own forwards and cannot say anything is covered.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ErrorCode, TreasuryError
from app.formatting import minor
from app.ids import new_id, now
from app.models import (
    CurrencyCoverTarget,
    CurrencyExposure,
    Deal,
    HedgeLink,
    InvestmentPolicy,
)

#: The same four buckets as the maturity ladder, so a reader who has learned
#: one has learned the other.
BUCKETS = (
    ("0_3M", "0 to 3 months", 92),
    ("3_6M", "3 to 6 months", 183),
    ("6_12M", "6 to 12 months", 365),
    ("OVER_12M", "over 12 months", None),
)


@dataclass
class BucketCoverage:
    bucket: str
    label: str
    net_minor: int
    covered_minor: int
    target_cover_bp: int
    covered_bp: int


class HedgeService:
    def __init__(self, session: Session, tenant_id: str, as_of_date: str) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.as_of_date = as_of_date

    # ------------------------------------------------------- the register

    def record_exposure(
        self,
        currency: str,
        amount_minor: int,
        direction: str,
        expected_date: str,
        source: str,
        created_by,
        source_reference: str | None = None,
    ) -> CurrencyExposure:
        """A future obligation in another currency.

        It exists before any hedge and often outlives several of them.
        """
        exposure = CurrencyExposure(
            id=new_id("cxp"),
            tenant_id=self.tenant_id,
            currency=currency.upper(),
            amount_minor=amount_minor,
            direction=direction,
            expected_date=expected_date,
            source=source,
            source_reference=source_reference,
            status="IDENTIFIED",
            created_by=str(created_by),
            created_by_user_id=created_by.user_id,
            created_at=now(),
        )
        self.session.add(exposure)
        self.session.flush()
        return exposure

    def exposures(self, currency: str | None = None) -> list[CurrencyExposure]:
        statement = select(CurrencyExposure).where(
            CurrencyExposure.tenant_id == self.tenant_id
        )
        if currency:
            statement = statement.where(CurrencyExposure.currency == currency.upper())
        return list(
            self.session.scalars(statement.order_by(CurrencyExposure.expected_date))
        )

    # -------------------------------------------------------------- links

    def link(
        self,
        currency_exposure_id: str,
        deal_id: str,
        covered_amount_minor: int,
        linked_by,
    ) -> HedgeLink:
        """Link a forward to an obligation.

        Two refusals, and both are invariants the schema cannot hold because
        both are sums across rows.
        """
        exposure = self.session.get(CurrencyExposure, currency_exposure_id)
        if exposure is None or exposure.tenant_id != self.tenant_id:
            raise TreasuryError(
                ErrorCode.CONFIRMATION_NOT_FOUND, "That obligation does not exist."
            )

        deal = self.session.get(Deal, deal_id)
        if deal is None or deal.tenant_id != self.tenant_id:
            raise TreasuryError(ErrorCode.DEAL_NOT_FOUND)

        # Only a forward can cover a currency obligation. A deposit does not
        # deliver currency on a date, so linking one would say something is
        # covered when nothing is.
        if deal.instrument != "FX_FORWARD":
            raise TreasuryError(
                ErrorCode.NOT_AN_FX_FORWARD,
                f"A {deal.instrument.replace('_', ' ').lower()} cannot cover a "
                "currency obligation.",
                field="deal_id",
            )

        already = self.covered_minor(exposure.id)
        if already + covered_amount_minor > exposure.amount_minor:
            raise TreasuryError(
                ErrorCode.HEDGE_EXCEEDS_EXPOSURE,
                f"This link would cover "
                f"{minor(already + covered_amount_minor, exposure.currency)} "
                f"against an obligation of "
                f"{minor(exposure.amount_minor, exposure.currency)}.",
                field="covered_amount_minor",
            )

        link = HedgeLink(
            id=new_id("hl"),
            tenant_id=self.tenant_id,
            currency_exposure_id=exposure.id,
            deal_id=deal.id,
            covered_amount_minor=covered_amount_minor,
            linked_by=str(linked_by),
            linked_at=now(),
        )
        self.session.add(link)
        self.session.flush()
        self._recompute_status(exposure)
        return link

    def unlink(self, link_id: str, reason: str, unlinked_by) -> CurrencyExposure:
        """Break the link. Requires a reason.

        Coverage is recomputed and the status can move backwards. A covered
        exposure becoming partially covered when a delivery slips is correct
        behaviour, not a defect. Nobody made a mistake; the world moved.
        """
        link = self.session.get(HedgeLink, link_id)
        if link is None or link.tenant_id != self.tenant_id:
            raise TreasuryError(
                ErrorCode.CONFIRMATION_NOT_FOUND, "That hedge link does not exist."
            )
        if link.unlinked_at is not None:
            raise TreasuryError(
                ErrorCode.ALREADY_MATCHED, "That link has already been broken."
            )

        link.unlinked_at = now()
        link.unlink_reason = reason
        link.unlinked_by = str(unlinked_by)
        self.session.flush()

        exposure = self.session.get(CurrencyExposure, link.currency_exposure_id)
        self._recompute_status(exposure)
        return exposure

    def live_links(self, currency_exposure_id: str) -> list[HedgeLink]:
        return list(
            self.session.scalars(
                select(HedgeLink)
                .where(HedgeLink.currency_exposure_id == currency_exposure_id)
                .where(HedgeLink.unlinked_at.is_(None))
            )
        )

    def covered_minor(self, currency_exposure_id: str) -> int:
        return sum(link.covered_amount_minor for link in self.live_links(currency_exposure_id))

    def _recompute_status(self, exposure: CurrencyExposure) -> None:
        """The status follows the links rather than being set by hand.

        It is allowed to move backwards, and nothing here treats that as an
        error.
        """
        if exposure.status == "SETTLED":
            return
        covered = self.covered_minor(exposure.id)
        if covered <= 0:
            exposure.status = "IDENTIFIED"
        elif covered >= exposure.amount_minor:
            exposure.status = "COVERED"
        else:
            exposure.status = "PARTIALLY_COVERED"
        self.session.flush()

    # ----------------------------------------------------------- coverage

    def coverage(self, currency: str) -> list[BucketCoverage]:
        """Net obligation and coverage by time bucket, against the policy
        target.

        Netted, because inflows offset outflows and hedging the gross is
        buying cover you do not need.
        """
        targets = self._cover_targets(currency)
        rows = {
            key: BucketCoverage(
                bucket=key,
                label=label,
                net_minor=0,
                covered_minor=0,
                target_cover_bp=targets,
                covered_bp=0,
            )
            for key, label, _days in BUCKETS
        }

        for exposure in self.exposures(currency):
            if exposure.status == "SETTLED":
                continue
            bucket = self._bucket(exposure.expected_date)
            sign = -1 if exposure.direction == "RECEIVABLE" else 1
            rows[bucket].net_minor += sign * exposure.amount_minor
            rows[bucket].covered_minor += self.covered_minor(exposure.id)

        for row in rows.values():
            row.covered_bp = (
                round(row.covered_minor * 10_000 / row.net_minor)
                if row.net_minor > 0
                else 0
            )
        return list(rows.values())

    def _cover_targets(self, currency: str) -> int:
        policy = self.session.scalars(
            select(InvestmentPolicy)
            .where(InvestmentPolicy.tenant_id == self.tenant_id)
            .where(InvestmentPolicy.superseded_at.is_(None))
        ).one_or_none()
        if policy is None:
            return 0
        target = self.session.get(CurrencyCoverTarget, (policy.id, currency.upper()))
        return target.target_cover_bp if target else 0

    def _bucket(self, expected_date: str) -> str:
        days = (
            date.fromisoformat(expected_date) - date.fromisoformat(self.as_of_date)
        ).days
        for key, _label, ceiling in BUCKETS:
            if ceiling is not None and days <= ceiling:
                return key
        return "OVER_12M"

    def uncovered_gap(self, currency: str) -> tuple[int, str] | None:
        """The first bucket below its cover target, and when it falls due.

        Read by the advisory layer, which then recommends cover the same way
        it recommends a deposit: the hedge is an ordinary forward booked
        through the ordinary ticket and the ordinary six checks.
        """
        for row in self.coverage(currency):
            if row.net_minor <= 0 or row.target_cover_bp <= 0:
                continue
            required = row.net_minor * row.target_cover_bp // 10_000
            if row.covered_minor < required:
                return required - row.covered_minor, row.bucket
        return None
