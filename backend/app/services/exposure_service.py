"""Step 8 of the build sequence. The exposure panel.

Last to build, first thing a board member asks for.

Utilisation by credit group, by rating band and by maturity bucket,
recomputed on every call by design. There is no `exposure` here without a
qualifier, and there is no method that returns counterparty exposure and
currency exposure together, because a forward increases one and reduces the
other and a combined figure would be meaningless in the best case and
misleading in the worst.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.models import PolicyVersion
from app.repo import counterparties as cp_repo
from app.repo import deals as deal_repo
from app.schemas.models import ExposureView, UtilisationRow
from app.services.exposure_calculator import ExposureCalculator

#: The four buckets of the maturity ladder, as document 1 names them.
BUCKETS = (
    ("0_3M", "0 to 3 months", 92),
    ("3_6M", "3 to 6 months", 183),
    ("6_12M", "6 to 12 months", 365),
    ("OVER_12M", "over 12 months", None),
)


class ExposureService:
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
        self.calculator = ExposureCalculator(session, tenant_id, as_of_date, policy)

    def counterparty_exposure(self) -> ExposureView:
        total = self.calculator.portfolio_total_pence() or 0
        cash = self.calculator.uninvested_cash_pence() or 0

        by_group_amounts = self.calculator.exposure_by_group()
        groups = {g.id: g for g in cp_repo.list_groups(self.session, self.tenant_id)}
        by_group = [
            UtilisationRow(
                key=group_id,
                label=groups[group_id].name if group_id in groups else group_id,
                used_pence=used,
                limit_pence=groups[group_id].group_limit_pence if group_id in groups else None,
                utilisation_bp=_bp(used, groups[group_id].group_limit_pence)
                if group_id in groups
                else None,
            )
            for group_id, used in by_group_amounts.items()
        ]
        by_group.sort(key=lambda row: row.used_pence, reverse=True)

        by_counterparty = self.calculator.exposure_by_counterparty()
        by_band: dict[str, int] = {}
        for counterparty in cp_repo.list_all(self.session, self.tenant_id):
            held = by_counterparty.get(counterparty.id, 0)
            if held:
                by_band[counterparty.rating] = by_band.get(counterparty.rating, 0) + held

        buckets: dict[str, int] = {key: 0 for key, _label, _days in BUCKETS}
        for deal in deal_repo.live_for_tenant(self.session, self.tenant_id):
            buckets[self._bucket(deal.maturity_date)] += self.calculator.measure(
                deal
            ).amount_pence

        return ExposureView(
            as_of_date=self.as_of_date,
            portfolio_total_pence=total,
            uninvested_cash_pence=cash,
            by_group=by_group,
            by_rating_band=[
                UtilisationRow(
                    key=rating,
                    label=rating,
                    used_pence=used,
                    utilisation_bp=_bp(used, total),
                )
                for rating, used in sorted(
                    by_band.items(), key=lambda item: item[1], reverse=True
                )
            ],
            by_maturity_bucket=[
                UtilisationRow(
                    key=key,
                    label=label,
                    used_pence=buckets[key],
                    utilisation_bp=_bp(buckets[key], total),
                )
                for key, label, _days in BUCKETS
            ],
        )

    def _bucket(self, maturity_date: str | None) -> str:
        """An open ended holding sits in the longest bucket.

        It has no maturity, so it cannot mature sooner than anything that
        does, and putting it in the shortest bucket would understate the
        ladder gap the advisory layer measures against.
        """
        if maturity_date is None:
            return "OVER_12M"
        days = (
            date.fromisoformat(maturity_date) - date.fromisoformat(self.as_of_date)
        ).days
        for key, _label, ceiling in BUCKETS:
            if ceiling is not None and days <= ceiling:
                return key
        return "OVER_12M"


def _bp(part: int, whole: int | None) -> int | None:
    if not whole:
        return None
    return round(part * 10_000 / whole)
