"""Everything the surface needs, from one transaction.

One state call rather than eleven. No waterfall, no eleven loading states,
and every figure on screen agrees with every other because they came from
one read. The cost is the largest response in the system, and it is the
first thing to break apart when a second screen exists.

Nothing here decides anything. It assembles rows the other services and the
calculator produced, and it does no arithmetic the browser could not have
been given directly.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.formatting import sterling
from app.models import PolicyVersion
from app.repo import counterparties as cp_repo
from app.repo import deals as deal_repo
from app.repo import evidence as evidence_repo
from app.repo import policy as policy_repo
from app.schemas.models import (
    AccrualRow,
    BookRow,
    BreachView,
    CheckOutcome,
    CheckResult,
    DealDetail,
    DealSummary,
    LimitVersion,
    PolicyConfig,
    QueueCounts,
    JournalSummary,
    QueueItem,
    RatingBandView,
    StateResponse,
    TimelineEvent,
)
from app.services.accrual_service import AccrualService
from app.services.exposure_calculator import ExposureCalculator
from app.services.journal_service import JournalService


class StateService:
    def __init__(
        self,
        session: Session,
        tenant_id: str,
        as_of_date: str,
        policy: PolicyVersion,
        tenant_name: str,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.as_of_date = as_of_date
        self.policy = policy
        self.tenant_name = tenant_name
        self.calculator = ExposureCalculator(session, tenant_id, as_of_date, policy)

    # -- the book ----------------------------------------------------------

    def book(self) -> list[BookRow]:
        by_counterparty = self.calculator.exposure_by_counterparty()
        by_group = self.calculator.exposure_by_group()
        groups = {g.id: g for g in cp_repo.list_groups(self.session, self.tenant_id)}
        tinted = evidence_repo.counterparties_with_breaches(self.session, self.tenant_id)

        rows = []
        for counterparty in cp_repo.list_all(self.session, self.tenant_id):
            limit = cp_repo.current_limit(self.session, counterparty.id)
            group = groups.get(counterparty.group_id)
            used = by_counterparty.get(counterparty.id, 0)
            group_used = by_group.get(counterparty.group_id, 0)
            group_limit = group.group_limit_pence if group else 0

            rows.append(
                BookRow(
                    counterparty_id=counterparty.id,
                    name=counterparty.name,
                    group_id=counterparty.group_id,
                    group_name=group.name if group else counterparty.group_id,
                    rating=counterparty.rating,
                    rating_status=counterparty.rating_status,
                    status=counterparty.status,
                    limit_pence=limit.amount_pence if limit else None,
                    limit_id=limit.id if limit else None,
                    max_tenor_months=limit.max_tenor_months if limit else None,
                    used_pence=used,
                    headroom_pence=(limit.amount_pence - used) if limit else None,
                    utilisation_bp=_bp(used, limit.amount_pence if limit else None),
                    group_used_pence=group_used,
                    group_limit_pence=group_limit,
                    group_utilisation_bp=_bp(group_used, group_limit) or 0,
                    instruments=cp_repo.permitted_instruments(
                        self.session, counterparty.id
                    ),
                    has_open_breach=counterparty.id in tinted,
                )
            )
        return rows

    # -- the blotter -------------------------------------------------------

    def deals(self) -> list[DealSummary]:
        names = {
            cp.id: cp.name for cp in cp_repo.list_all(self.session, self.tenant_id)
        }
        flagged = evidence_repo.deals_with_breaches(self.session, self.tenant_id)
        # One pass for the whole blotter rather than one query per row. The
        # stage label carries the daily figure, so every row needs it.
        accruals = AccrualService(
            self.session, self.tenant_id, self.as_of_date
        ).daily_by_deal()

        summaries = []
        for deal in deal_repo.all_for_tenant(self.session, self.tenant_id):
            if deal.status == "CANCELLED":
                continue
            measure = self.calculator.measure(deal)
            summaries.append(
                DealSummary(
                    id=deal.id,
                    counterparty_id=deal.counterparty_id,
                    counterparty_name=names.get(deal.counterparty_id, deal.counterparty_id),
                    instrument=deal.instrument,
                    principal_pence=deal.principal_pence,
                    currency=deal.currency,
                    rate_bp=deal.rate_bp,
                    tenor_months=deal.tenor_months,
                    trade_date=deal.trade_date,
                    value_date=deal.value_date,
                    maturity_date=deal.maturity_date,
                    status=deal.status,
                    capture_source=deal.capture_source,
                    measured_pence=measure.amount_pence,
                    measurement_basis=measure.basis,
                    stage=self.stage(deal, accruals.get(deal.id)),
                    flag="breach" if deal.id in flagged else None,
                    approved_by=deal.approved_by,
                    required_approver=deal.required_approver,
                    accrual_today_pence=accruals.get(deal.id, (None, 0))[0],
                    accrual_cumulative_pence=accruals.get(deal.id, (None, 0))[1],
                )
            )
        return summaries

    def stage(self, deal, accrual: tuple[int | None, int] | None = None) -> str:
        """The lifecycle label. Computed, never stored.

        Phase two added the accruing label, which carries the daily figure.
        A deal that accrued today says so; one that has not yet, or does not
        accrue at all, falls back to the countdown. The confirmation labels
        arrive in phase three, and this method is the only thing that changes
        when they do.
        """
        if deal.status == "BLOCKED":
            return "blocked"
        if deal.status == "PROPOSED":
            return "awaiting approval"
        if deal.status == "CLOSED":
            return "closed"
        if deal.status == "MATURED":
            return "matured"
        if not deal.maturity_date:
            return "open ended"

        days = (
            date.fromisoformat(deal.maturity_date) - date.fromisoformat(self.as_of_date)
        ).days
        if days <= 0:
            return "matured"
        if accrual and accrual[0]:
            return f"accruing {sterling(accrual[0])} a day"
        return f"matures in {days} days"

    # -- the panels --------------------------------------------------------

    def queue(self) -> list[QueueItem]:
        names = {
            cp.id: cp.name for cp in cp_repo.list_all(self.session, self.tenant_id)
        }
        return [
            QueueItem(
                id=item.id,
                cause=item.cause,
                reason_code=item.reason_code,
                detail=item.detail,
                deal_id=item.deal_id,
                confirmation_id=item.confirmation_id,
                counterparty_id=item.counterparty_id,
                counterparty_name=names.get(item.counterparty_id, item.counterparty_id),
                status=item.status,
                resolution=item.resolution,
                raised_at=item.raised_at,
                differences=[],
            )
            for item in evidence_repo.open_queue_items(self.session, self.tenant_id)
        ]

    def breaches(self) -> list[BreachView]:
        names = {
            cp.id: cp.name for cp in cp_repo.list_all(self.session, self.tenant_id)
        }
        return [
            BreachView(
                id=breach.id,
                counterparty_id=breach.counterparty_id,
                counterparty_name=names.get(
                    breach.counterparty_id, breach.counterparty_id
                ),
                deal_id=breach.deal_id,
                type=breach.type,
                detail=breach.detail,
                status=breach.status,
                response=breach.response,
                response_reason=breach.response_reason,
                original_check_run_id=breach.original_check_run_id,
                raised_at=breach.raised_at,
            )
            for breach in evidence_repo.breaches(self.session, self.tenant_id)
        ]

    def policy_config(self) -> PolicyConfig:
        return PolicyConfig(
            id=self.policy.id,
            effective_from=self.policy.effective_from,
            concentration_cap_bp=self.policy.concentration_cap_bp,
            threshold_analyst_pence=self.policy.threshold_analyst_pence,
            threshold_hot_pence=self.policy.threshold_hot_pence,
            enforcement=self.policy.enforcement,
            fx_add_on_bp=self.policy.fx_add_on_bp,
            approved_by=self.policy.approved_by,
        )

    def rating_bands(self) -> list[RatingBandView]:
        return [
            RatingBandView(
                rating=band.rating,
                ordinal=band.ordinal,
                max_limit_pence=band.max_limit_pence,
                max_tenor_months=band.max_tenor_months,
            )
            for band in policy_repo.rating_bands(self.session, self.tenant_id)
        ]

    def limit_versions(self, counterparty_id: str) -> list[LimitVersion]:
        return [
            LimitVersion(
                id=limit.id,
                counterparty_id=limit.counterparty_id,
                amount_pence=limit.amount_pence,
                max_tenor_months=limit.max_tenor_months,
                source=limit.source,
                effective_from=limit.effective_from,
                superseded_at=limit.superseded_at,
                reason=limit.reason,
                approved_by=limit.approved_by,
            )
            for limit in cp_repo.limit_history(self.session, counterparty_id)
        ]

    # -- one deal, one panel, one call -------------------------------------

    def deal_detail(self, deal_id: str) -> DealDetail | None:
        """Everything the deal panel needs, in one object.

        Document 2 hangs seven collections off this. Five of them live in
        tables that arrive in phases two and three, so they come back empty
        and the panel grows as they do. The two that exist now are the ones
        the demonstration turns on: the check evidence, and the breaches
        raised against the position afterwards.
        """
        import json

        deal = deal_repo.get(self.session, deal_id)
        if deal is None or deal.tenant_id != self.tenant_id:
            return None

        summary = next((d for d in self.deals() if d.id == deal_id), None)
        if summary is None:
            return None

        run = None
        if deal.check_run_id:
            stored = evidence_repo.get_check_run(self.session, deal.check_run_id)
            if stored is not None:
                run = CheckResult(
                    check_run_id=stored.id,
                    as_of_date=stored.as_of_date,
                    counterparty_id=stored.counterparty_id,
                    outcome=stored.outcome,
                    # Read back from what was written, never recomputed. This
                    # is what the six checks said on the day, against the
                    # limit and the policy version in force then.
                    checks=[
                        CheckOutcome(**row) for row in json.loads(stored.results_json)
                    ],
                    failed_count=stored.failed_count,
                    measured_pence=stored.measured_pence,
                    measurement_basis=stored.measurement_basis,
                    required_approver=stored.required_approver,
                    enforcement=self.policy.enforcement,
                    verdict=(
                        f"Compliant when booked, on {stored.as_of_date}."
                        if stored.outcome != "FAIL"
                        else f"{stored.failed_count} of six checks failed."
                    ),
                    limit_id=stored.limit_id,
                    policy_version_id=stored.policy_version_id,
                )

        limit = None
        if deal.limit_id_at_booking:
            held = cp_repo.limit_by_id(self.session, deal.limit_id_at_booking)
            if held is not None:
                limit = LimitVersion(
                    id=held.id,
                    counterparty_id=held.counterparty_id,
                    amount_pence=held.amount_pence,
                    max_tenor_months=held.max_tenor_months,
                    source=held.source,
                    effective_from=held.effective_from,
                    superseded_at=held.superseded_at,
                    reason=held.reason,
                    approved_by=held.approved_by,
                )

        names = {
            cp.id: cp.name for cp in cp_repo.list_all(self.session, self.tenant_id)
        }
        breaches = [
            BreachView(
                id=breach.id,
                counterparty_id=breach.counterparty_id,
                counterparty_name=names.get(
                    breach.counterparty_id, breach.counterparty_id
                ),
                deal_id=breach.deal_id,
                type=breach.type,
                detail=breach.detail,
                status=breach.status,
                response=breach.response,
                response_reason=breach.response_reason,
                original_check_run_id=breach.original_check_run_id,
                raised_at=breach.raised_at,
            )
            for breach in evidence_repo.breaches_for_deal(self.session, deal_id)
        ]

        return DealDetail(
            deal=summary,
            timeline=self._timeline(deal, breaches),
            run=run,
            limit=limit,
            confirmation=None,
            accruals=[
                AccrualRow(
                    id=row.id,
                    accrual_date=row.accrual_date,
                    day_count=row.day_count,
                    rate_bp=row.rate_bp,
                    amount_pence=row.amount_pence,
                    cumulative_pence=row.cumulative_pence,
                    reversal_of=row.reversal_of,
                    amendment_id=row.amendment_id,
                )
                for row in AccrualService(
                    self.session, self.tenant_id, self.as_of_date
                ).for_deal(deal_id)
            ],
            journals=[
                JournalSummary(**row)
                for row in JournalService(
                    self.session, self.tenant_id, self.as_of_date
                ).summary_for_deal(deal_id)
            ],
            settlement=None,
            amendments=[],
            breaches=breaches,
        )

    def _timeline(self, deal, breaches: list[BreachView]) -> list[TimelineEvent]:
        """Model 2 in one view.

        Execution is labelled outside and payment as Oracle, so the boundary
        is visible without a separate integration screen. Future events are
        computed from the maturity date rather than stored, so a live deal
        still shows what will happen to it.
        """
        from app.formatting import per_cent

        events = [
            TimelineEvent(
                key="executed",
                title="Deal executed",
                detail=f"{per_cent(deal.rate_bp)} for {deal.tenor_months} months.",
                occurred_at=deal.trade_date,
                source="OUTSIDE",
                state="DONE",
            ),
            TimelineEvent(
                key="captured",
                title="Deal captured",
                detail=(
                    "Keyed."
                    if deal.capture_source == "KEYED"
                    else "Created from the confirmation."
                ),
                occurred_at=deal.created_at[:10],
                source="PLATFORM",
                state="DONE",
            ),
            TimelineEvent(
                key="checked",
                title="Six checks run",
                detail=(
                    "Recorded against the limit and the policy version in force."
                    if deal.check_run_id
                    else "No check run recorded."
                ),
                occurred_at=deal.created_at[:10],
                source="PLATFORM",
                state="DONE" if deal.check_run_id else "WARN",
            ),
        ]

        if deal.approved_at:
            events.append(
                TimelineEvent(
                    key="approved",
                    title="Approved",
                    detail=f"Signed by {deal.approved_by}.",
                    occurred_at=deal.approved_at[:10],
                    source="PLATFORM",
                    state="DONE",
                )
            )
        else:
            events.append(
                TimelineEvent(
                    key="approved",
                    title="Awaiting approval",
                    detail=f"{deal.required_approver or 'Somebody'} has to sign.",
                    occurred_at=None,
                    source="PLATFORM",
                    state="FUTURE",
                )
            )

        events.append(
            TimelineEvent(
                key="instructed",
                title="Payment instructed",
                detail="Handed to Oracle Fusion Payments.",
                occurred_at=deal.instructed_at[:10] if deal.instructed_at else None,
                source="ORACLE",
                state="DONE" if deal.instructed_at else "FUTURE",
            )
        )

        for breach in breaches:
            events.append(
                TimelineEvent(
                    key=f"breach_{breach.id}",
                    title="Fell outside policy",
                    detail=breach.detail,
                    occurred_at=breach.raised_at[:10],
                    source="PLATFORM",
                    state="WARN",
                )
            )

        if deal.maturity_date:
            events.append(
                TimelineEvent(
                    key="maturity",
                    title="Maturity due",
                    detail="The expected amount falls due.",
                    occurred_at=deal.maturity_date,
                    source="PLATFORM",
                    state="DONE" if deal.status in ("MATURED", "CLOSED") else "FUTURE",
                )
            )

        events.append(
            TimelineEvent(
                key="closed",
                title="Deal closed",
                detail=(
                    "Headroom returns to the book. Until a deal closes the "
                    "counterparty holds it, and the next deal may be blocked "
                    "for no reason."
                ),
                occurred_at=deal.closed_at[:10] if deal.closed_at else None,
                source="PLATFORM",
                state="DONE" if deal.closed_at else "FUTURE",
            )
        )
        return events

    # -- the one call ------------------------------------------------------

    def state(self) -> StateResponse:
        counts = evidence_repo.open_queue_counts(self.session, self.tenant_id)
        total = self.calculator.portfolio_total_pence()
        cash = self.calculator.uninvested_cash_pence()

        return StateResponse(
            as_of_date=self.as_of_date,
            tenant_name=self.tenant_name,
            enforcement=self.policy.enforcement,
            policy=self.policy_config(),
            rating_bands=self.rating_bands(),
            book=self.book(),
            deals=self.deals(),
            queue_counts=QueueCounts(**counts),
            breach_count=evidence_repo.outstanding_breach_count(
                self.session, self.tenant_id
            ),
            advisory=self.advisory_card(),
            advisory_run_id=self.latest_run_id(),
            uninvested_cash_pence=cash or 0,
            portfolio_total_pence=total or 0,
        )

    def advisory_card(self):
        """The outstanding recommendation, folded into the state call.

        Null when the last run found no gap, or when somebody has already
        decided. The card is absent rather than empty, because an empty card
        implies something is broken.
        """
        from app.services.advisory_service import AdvisoryService
        from app.services.advisory_view import card_for

        outcome = AdvisoryService(
            self.session, self.tenant_id, self.as_of_date, self.policy
        ).latest()
        if outcome is None or outcome.recommendation is None:
            return None
        if outcome.recommendation.decision is not None:
            return None
        return card_for(self.session, outcome)

    def latest_run_id(self) -> str | None:
        """The most recent run, decided or not.

        The card disappears when somebody accepts or rejects, and the run is
        still what says which options were considered and which were refused.
        Losing the route to it with the card would lose the evidence.
        """
        from app.services.advisory_service import AdvisoryService

        outcome = AdvisoryService(
            self.session, self.tenant_id, self.as_of_date, self.policy
        ).latest()
        return outcome.run.id if outcome else None

    def summary_line(self) -> str:
        total = self.calculator.portfolio_total_pence() or 0
        cash = self.calculator.uninvested_cash_pence() or 0
        return (
            f"Every figure computed from the deals behind it, none of it typed. "
            f"Portfolio {sterling(total)}, including {sterling(cash)} uninvested."
        )


def _bp(part: int, whole: int | None) -> int | None:
    if not whole:
        return None
    return round(part * 10_000 / whole)
