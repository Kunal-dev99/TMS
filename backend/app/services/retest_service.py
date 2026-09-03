"""Step 6 of the build sequence. A rating action, and the re-test.

One call in, an unknown number of breaches out. This is the closing argument
of the demonstration, and it is cheap, because the rating is a field.

What it does, in one transaction: record the event, move the rating, supersede
the limit and write the new one from the band, then re-test every live
position this counterparty holds and raise a breach for each check that now
fails.

The re-test excludes the position under test from the held total before
offering its own terms back as the proposal. Without that every deal is
counted twice and every position looks like a breach the moment anything is
downgraded.

A breach is not a mistake. A position that was compliant when it was booked
can stop being compliant without anybody doing anything wrong, and the
interface has to say so in those words.
"""

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.errors import ErrorCode, TreasuryError
from app.ids import new_id, now
from app.models import CheckRun, CpLimit, PolicyVersion, RatingEvent
from app.repo import counterparties as cp_repo
from app.repo import deals as deal_repo
from app.repo import policy as policy_repo
from app.services.breach_service import BREACH_TYPE_FOR_CHECK, BreachService
from app.services.check_engine import CheckEngine


@dataclass
class RatingActionResult:
    event: RatingEvent
    new_limit: CpLimit | None
    positions_tested: int
    breaches_raised: int


class RetestService:
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
        self.breaches = BreachService(session, tenant_id)

    def apply_rating_action(
        self,
        counterparty_id: str,
        new_rating: str,
        new_status: str,
        recorded_by,
        effective_date: str | None = None,
        source: str = "Operator entered",
    ) -> RatingActionResult:
        counterparty = cp_repo.get(self.session, counterparty_id)
        if counterparty is None or counterparty.tenant_id != self.tenant_id:
            raise TreasuryError(ErrorCode.COUNTERPARTY_NOT_FOUND)

        band = policy_repo.band_for_rating(self.session, self.tenant_id, new_rating)
        if band is None:
            raise TreasuryError(
                ErrorCode.UNKNOWN_RATING,
                f"{new_rating} has no band in the policy in force.",
                field="new_rating",
            )

        previous_rating = counterparty.rating
        previous_status = counterparty.rating_status
        old_band = policy_repo.band_for_rating(
            self.session, self.tenant_id, previous_rating
        )
        timestamp = now()

        event = RatingEvent(
            id=new_id("rte"),
            tenant_id=self.tenant_id,
            counterparty_id=counterparty_id,
            previous_rating=previous_rating,
            new_rating=new_rating,
            previous_status=previous_status,
            new_status=new_status,
            action=self._action(old_band, band, previous_status, new_status),
            effective_date=effective_date or self.as_of_date,
            source=source,
            policy_version_id=self.policy.id,
            positions_tested=0,
            breaches_raised=0,
            recorded_by=str(recorded_by),
            recorded_by_user_id=recorded_by.user_id,
            recorded_at=timestamp,
        )
        self.session.add(event)

        counterparty.rating = new_rating
        counterparty.rating_status = new_status

        new_limit = self._reset_limit_to_band(
            counterparty_id, band, event.id, recorded_by, timestamp
        )
        self.session.flush()

        tested, raised = self._retest_positions(counterparty_id, event.id, recorded_by)
        event.positions_tested = tested
        event.breaches_raised = raised
        self.session.flush()

        return RatingActionResult(
            event=event,
            new_limit=new_limit,
            positions_tested=tested,
            breaches_raised=raised,
        )

    # ------------------------------------------------------------- internals

    @staticmethod
    def _action(old_band, new_band, previous_status: str, new_status: str) -> str:
        if old_band is not None and new_band is not None:
            if new_band.ordinal < old_band.ordinal:
                return "DOWNGRADE"
            if new_band.ordinal > old_band.ordinal:
                return "UPGRADE"
        if new_status != previous_status and new_status == "WATCH":
            return "WATCH"
        return "AFFIRM"

    def _reset_limit_to_band(
        self,
        counterparty_id: str,
        band,
        event_id: str,
        recorded_by,
        timestamp: str,
    ) -> CpLimit | None:
        """Tighten the limit in force to the band. Never widen it.

        A downgrade takes an entitlement away, and it does so whoever signed
        for the old limit: the band is the ceiling a rating entitles a name
        to, and a rating action is the world moving rather than a decision
        anybody here made.

        An upgrade is not the mirror of that. Raising a limit grants
        headroom, and a limit nobody signed is not a control. An upgrade
        therefore leaves the limit where it is, and somebody has to set the
        higher one through the limit endpoint and put their name against it.
        Without that asymmetry, one rating action hands a counterparty
        millions of new headroom with an approver of whoever happened to key
        the upgrade.

        Amount and term are tightened independently, because they are two
        independent constraints and a rating can move one without the other.

        The old row always survives, because a deal booked under it records
        limit_id_at_booking and has to be re-derivable against the version
        that was actually in force.
        """
        current = cp_repo.current_limit(self.session, counterparty_id)
        if current is None:
            return None

        amount = min(current.amount_pence, band.max_limit_pence)
        tenor = min(current.max_tenor_months, band.max_tenor_months)

        if (
            amount == current.amount_pence
            and tenor == current.max_tenor_months
        ):
            return current

        current.superseded_at = timestamp
        current.superseded_by_event = event_id

        replacement = CpLimit(
            id=new_id("lim"),
            tenant_id=self.tenant_id,
            counterparty_id=counterparty_id,
            amount_pence=amount,
            max_tenor_months=tenor,
            source="BAND",
            effective_from=self.as_of_date,
            superseded_at=None,
            reason=(
                f"Rating action to {band.rating}. Tightened to the band: "
                f"{amount // 100:,} and {tenor} months."
            ),
            approved_by=str(recorded_by),
            recorded_by_user_id=recorded_by.user_id,
            approved_at=timestamp,
        )
        self.session.add(replacement)
        return replacement

    def _retest_positions(
        self, counterparty_id: str, event_id: str, recorded_by
    ) -> tuple[int, int]:
        """Re-run the six checks against every live position, one at a time.

        Each run is written, so a breach can be traced to the evaluation that
        produced it rather than only to the rating action.
        """
        engine = CheckEngine(
            self.session, self.tenant_id, self.as_of_date, self.policy
        )
        positions = deal_repo.live_for_counterparty(self.session, counterparty_id)
        raised = 0

        for deal in positions:
            evaluation = engine.run(
                counterparty_id=deal.counterparty_id,
                instrument=deal.instrument,
                principal_pence=deal.principal_pence,
                tenor_months=deal.tenor_months,
                rate_bp=deal.rate_bp,
                exclude_deal_id=deal.id,
            )
            result = evaluation.result
            timestamp = now()

            self.session.add(
                CheckRun(
                    id=new_id("run"),
                    tenant_id=self.tenant_id,
                    counterparty_id=counterparty_id,
                    deal_id=deal.id,
                    purpose="RETEST",
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
                    created_by=str(recorded_by),
                    created_by_user_id=recorded_by.user_id,
                    created_at=timestamp,
                )
            )

            for check in result.checks:
                if check.passed or check.key not in BREACH_TYPE_FOR_CHECK:
                    continue
                self.breaches.raise_breach(
                    counterparty_id=counterparty_id,
                    deal_id=deal.id,
                    check_key=check.key,
                    detail=(
                        f"{check.detail} Booked at {deal.tenor_months} months and "
                        "compliant when booked."
                    ),
                    limit_id=result.limit_id,
                    rating_event_id=event_id,
                    original_check_run_id=deal.check_run_id,
                )
                raised += 1

        self.session.flush()
        return len(positions), raised
