"""Step 1 of the build sequence. The join between counterparty control and
dealing.

Wrong here means all six checks are wrong, which is why it is built first and
asserted against the seeded numbers before anything visual exists.

Nothing here is stored. Exposure answers what is true now, and recomputing it
on every read is the only way to be sure it agrees with the deals behind it.
A cached figure that drifts from the deals is worse than a slow query.

Measurement is per instrument and the basis travels with the figure, because
the interface shows the basis underneath the number and would otherwise have
to reconstruct it. A forward's notional is not its exposure.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.measurement import Measure, measure_deal
from app.models import Deal, PolicyVersion
from app.repo import counterparties as cp_repo
from app.repo import deals as deal_repo
from app.repo import oracle as oracle_repo


@dataclass(frozen=True)
class MeasuredDeal:
    deal_id: str
    counterparty_id: str
    instrument: str
    principal_pence: int
    measure: Measure


@dataclass(frozen=True)
class Exposure:
    """A held position and what it is made of.

    `contributors` is what lets a failed group check name the other holdings
    individually rather than reporting a total the reader cannot decompose.
    """

    amount_pence: int
    contributors: list[MeasuredDeal] = field(default_factory=list)


class ExposureCalculator:
    """Constructed per request, against one tenant, one clock date and one
    policy version.

    The policy version is passed in rather than read here, so a re-derivation
    of a historic check run can hand it the version that was in force then.
    """

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

    # -- one deal ----------------------------------------------------------

    def measure(self, deal: Deal) -> Measure:
        return measure_deal(
            instrument=deal.instrument,
            principal_pence=deal.principal_pence,
            rate_bp=deal.rate_bp,
            value_date=deal.value_date,
            as_of_date=self.as_of_date,
            fx_add_on_bp=self.policy.fx_add_on_bp,
        )

    def measure_proposed(self, instrument: str, principal_pence: int) -> Measure:
        """A deal that does not exist yet, valued today.

        Its value date is the clock date, so a deposit has accrued nothing and
        measures at its principal. A forward still measures at the add on,
        because that is a property of the instrument rather than of time.
        """
        return measure_deal(
            instrument=instrument,
            principal_pence=principal_pence,
            rate_bp=0,
            value_date=self.as_of_date,
            as_of_date=self.as_of_date,
            fx_add_on_bp=self.policy.fx_add_on_bp,
        )

    def _measured(self, deals: list[Deal]) -> Exposure:
        contributors = [
            MeasuredDeal(
                deal_id=deal.id,
                counterparty_id=deal.counterparty_id,
                instrument=deal.instrument,
                principal_pence=deal.principal_pence,
                measure=self.measure(deal),
            )
            for deal in deals
        ]
        return Exposure(
            amount_pence=sum(c.measure.amount_pence for c in contributors),
            contributors=contributors,
        )

    # -- aggregations ------------------------------------------------------

    def entity_exposure(
        self, counterparty_id: str, exclude_deal_id: str | None = None
    ) -> Exposure:
        deals = deal_repo.live_for_counterparty(self.session, counterparty_id)
        return self._measured(self._without(deals, exclude_deal_id))

    def group_exposure(
        self, group_id: str, exclude_deal_id: str | None = None
    ) -> Exposure:
        """The figure that connects two legal entities in one credit.

        Nothing else on the surface connects them. This is the whole of the
        group check.
        """
        deals = deal_repo.live_for_group(self.session, group_id)
        return self._measured(self._without(deals, exclude_deal_id))

    @staticmethod
    def _without(deals: list[Deal], exclude_deal_id: str | None) -> list[Deal]:
        """Drop one deal from a held total.

        Re-testing an existing position asks whether it would be allowed
        today. The position is already inside the exposure, so it has to come
        out before its own terms are offered back as the proposal. Without
        this a re-test counts every deal twice and every position looks like a
        breach.
        """
        if exclude_deal_id is None:
            return deals
        return [deal for deal in deals if deal.id != exclude_deal_id]

    def exposure_by_counterparty(self) -> dict[str, int]:
        totals = {cp.id: 0 for cp in cp_repo.list_all(self.session, self.tenant_id)}
        for deal in deal_repo.live_for_tenant(self.session, self.tenant_id):
            totals[deal.counterparty_id] = (
                totals.get(deal.counterparty_id, 0) + self.measure(deal).amount_pence
            )
        return totals

    def exposure_by_group(self) -> dict[str, int]:
        by_counterparty = self.exposure_by_counterparty()
        totals = {g.id: 0 for g in cp_repo.list_groups(self.session, self.tenant_id)}
        for cp in cp_repo.list_all(self.session, self.tenant_id):
            totals[cp.group_id] = totals.get(cp.group_id, 0) + by_counterparty.get(cp.id, 0)
        return totals

    # -- the portfolio -----------------------------------------------------

    def uninvested_cash_pence(self) -> int | None:
        """None when the balance feed has not delivered for this date.

        The caller must treat None as an absent denominator and fail the
        concentration check closed. Returning zero here would silently pass a
        check that has nothing to measure against.
        """
        return oracle_repo.uninvested_cash_pence(
            self.session, self.tenant_id, self.as_of_date
        )

    def portfolio_total_pence(self, exclude_deal_id: str | None = None) -> int | None:
        """Live deals at their measure, plus the Oracle balance on the date.

        Cash counts. A concentration figure that ignores the money sitting in
        the operating account measures the wrong denominator.
        """
        cash = self.uninvested_cash_pence()
        if cash is None:
            return None
        invested = sum(
            self.measure(deal).amount_pence
            for deal in self._without(
                deal_repo.live_for_tenant(self.session, self.tenant_id), exclude_deal_id
            )
        )
        return invested + cash
