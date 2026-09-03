"""Step 2 of the build sequence. The gate.

There is one CheckEngine. The browser has no copy of it, the mock server has
no copy of it, and the advisory layer has no copy of it. Every path into the
book passes through here, whether a person typed the deal, a model proposed
it, or a correction changed it.

Four properties this file has to hold, from document 4 section 5.

One implementation. Anything that needs a number this produces asks for it
rather than working it out.

Called twice on every booking. Once for the user as they type, once as the
control at the moment of writing. Between the last keystroke and the submit,
another user can book a deal, a rating can move or the clock can change, and
in each case the browser holds a result that is now wrong.

Reproducible. `gather_inputs` reads the world and `evaluate` decides. Nothing
in `evaluate` touches the database, so a run recorded six months ago
re-derives its verdict from its stored inputs rather than being
reconstructed. That is what makes the versioned policy worth having.

Fails closed. A check that cannot read its inputs fails rather than passes.
The concentration check with no Oracle balance is the worked example, and it
is the single most disruptive failure in the system by design.

The messages state the arithmetic, not the verdict. `Group limit exceeded`
tells a user nothing. Naming the amount, the other holdings in the group and
the ceiling tells them what to do next.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.formatting import per_cent, sterling
from app.measurement import principal_for_measure
from app.models import PolicyVersion
from app.repo import counterparties as cp_repo
from app.repo import policy as policy_repo
from app.schemas.models import CheckOutcome, CheckResult
from app.services.approval_router import ApprovalRouter
from app.services.exposure_calculator import ExposureCalculator

BP = 10_000

#: The six, in the order the panel shows them. The group check is fourth
#: because screen 2 of document 3 says so outright: nothing else on the
#: screen connects those two names, and check four is the only thing that
#: does.
CHECK_NAMES: dict[str, str] = {
    "COUNTERPARTY_ACTIVE": "Counterparty approved and active",
    "INSTRUMENT_PERMITTED": "Instrument permitted",
    "ENTITY_LIMIT": "Entity limit",
    "GROUP_LIMIT": "Group limit",
    "TENOR_BAND": "Term inside the rating band",
    "CONCENTRATION": "Concentration cap",
}

#: The checks a smaller amount could clear. A term failure is not one of
#: them: amount and duration are two independent constraints.
AMOUNT_CONSTRAINED = ("ENTITY_LIMIT", "GROUP_LIMIT", "CONCENTRATION")


@dataclass(frozen=True)
class Evaluation:
    """A verdict and everything needed to re-derive it.

    `inputs` is written to check_run.inputs_json and `result.checks` to
    results_json. Handing both to `evaluate` again must produce the same
    verdict, and there is a test that says so.
    """

    result: CheckResult
    inputs: dict


class CheckEngine:
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
        self.exposure = ExposureCalculator(session, tenant_id, as_of_date, policy)
        self.approvals = ApprovalRouter(policy)

    # ---------------------------------------------------------------- read

    def gather_inputs(
        self,
        counterparty_id: str,
        instrument: str,
        principal_pence: int,
        tenor_months: int,
        rate_bp: int,
        exclude_deal_id: str | None = None,
    ) -> dict:
        """Every figure the arithmetic will use, read once.

        Anything absent is recorded as None rather than defaulted. `evaluate`
        turns a None into a failure, which is what failing closed means in
        practice.

        `exclude_deal_id` is for a re-test. The position being tested is
        already inside the held total, so it comes out before its own terms
        are offered back as the proposal.
        """
        counterparty = cp_repo.get(self.session, counterparty_id)
        if counterparty is None:
            raise LookupError(counterparty_id)

        group = cp_repo.group(self.session, counterparty.group_id)
        limit = cp_repo.current_limit(self.session, counterparty_id)
        band = policy_repo.band_for_rating(
            self.session, self.tenant_id, counterparty.rating
        )
        proposed = self.exposure.measure_proposed(instrument, principal_pence)
        entity = self.exposure.entity_exposure(counterparty_id, exclude_deal_id)
        group_exposure = self.exposure.group_exposure(
            counterparty.group_id, exclude_deal_id
        )

        # Named individually, so a failed group check can say which other
        # holdings make up the total rather than reporting a figure the
        # reader cannot decompose.
        contributors = []
        for held in group_exposure.contributors:
            other = cp_repo.get(self.session, held.counterparty_id)
            contributors.append(
                {
                    "counterparty_name": other.name if other else held.counterparty_id,
                    "measure_pence": held.measure.amount_pence,
                }
            )

        return {
            "as_of_date": self.as_of_date,
            "tenant_id": self.tenant_id,
            "proposal": {
                "counterparty_id": counterparty_id,
                "instrument": instrument,
                "principal_pence": principal_pence,
                "tenor_months": tenor_months,
                "rate_bp": rate_bp,
            },
            "counterparty": {
                "id": counterparty.id,
                "name": counterparty.name,
                "status": counterparty.status,
                "rating": counterparty.rating,
                "rating_status": counterparty.rating_status,
                "group_id": counterparty.group_id,
            },
            "group": None
            if group is None
            else {
                "id": group.id,
                "name": group.name,
                "group_limit_pence": group.group_limit_pence,
            },
            "limit": None
            if limit is None
            else {
                "id": limit.id,
                "amount_pence": limit.amount_pence,
                "max_tenor_months": limit.max_tenor_months,
                "source": limit.source,
            },
            "band": None
            if band is None
            else {
                "rating": band.rating,
                "max_limit_pence": band.max_limit_pence,
                "max_tenor_months": band.max_tenor_months,
            },
            "policy": {
                "id": self.policy.id,
                "concentration_cap_bp": self.policy.concentration_cap_bp,
                "fx_add_on_bp": self.policy.fx_add_on_bp,
                "enforcement": self.policy.enforcement,
                "threshold_analyst_pence": self.policy.threshold_analyst_pence,
                "threshold_hot_pence": self.policy.threshold_hot_pence,
            },
            "permitted_instruments": cp_repo.permitted_instruments(
                self.session, counterparty_id
            ),
            "entity_used_pence": entity.amount_pence,
            "group_used_pence": group_exposure.amount_pence,
            "group_contributors": contributors,
            "uninvested_cash_pence": self.exposure.uninvested_cash_pence(),
            "portfolio_total_pence": self.exposure.portfolio_total_pence(exclude_deal_id),
            "proposed_measure_pence": proposed.amount_pence,
            "proposed_measure_basis": proposed.basis,
        }

    # ------------------------------------------------------------- decide

    @staticmethod
    def evaluate(inputs: dict) -> list[CheckOutcome]:
        """The six checks. Pure: no session, no clock, no policy lookup.

        Everything it needs is in `inputs`, which is what makes a historic
        run re-derivable rather than merely recorded.
        """
        proposal = inputs["proposal"]
        counterparty = inputs["counterparty"]
        group = inputs["group"]
        limit = inputs["limit"]
        band = inputs["band"]
        policy = inputs["policy"]
        measure = inputs["proposed_measure_pence"]
        entity_used = inputs["entity_used_pence"]
        group_used = inputs["group_used_pence"]
        portfolio = inputs["portfolio_total_pence"]

        outcomes: list[CheckOutcome] = []

        # 1 -----------------------------------------------------------------
        active = counterparty["status"] == "ACTIVE"
        outcomes.append(
            CheckOutcome(
                key="COUNTERPARTY_ACTIVE",
                name=CHECK_NAMES["COUNTERPARTY_ACTIVE"],
                passed=active,
                detail=(
                    f"{counterparty['name']} is active, rated {counterparty['rating']}."
                    if active
                    else f"{counterparty['name']} is {counterparty['status'].lower()}, "
                    "not active. Only an active counterparty can be dealt with."
                ),
            )
        )

        # 2 -----------------------------------------------------------------
        permitted = proposal["instrument"] in inputs["permitted_instruments"]
        readable = proposal["instrument"].replace("_", " ").lower()
        outcomes.append(
            CheckOutcome(
                key="INSTRUMENT_PERMITTED",
                name=CHECK_NAMES["INSTRUMENT_PERMITTED"],
                passed=permitted,
                detail=(
                    f"A {readable} is approved for this name."
                    if permitted
                    else f"{counterparty['name']} is not approved for a {readable}."
                ),
                workings=[]
                if permitted
                else [
                    "Approved: "
                    + (
                        ", ".join(
                            i.replace("_", " ").lower()
                            for i in inputs["permitted_instruments"]
                        )
                        or "nothing"
                    )
                    + "."
                ],
            )
        )

        # 3 -----------------------------------------------------------------
        if limit is None:
            outcomes.append(
                CheckOutcome(
                    key="ENTITY_LIMIT",
                    name=CHECK_NAMES["ENTITY_LIMIT"],
                    passed=False,
                    detail=(
                        f"{counterparty['name']} has no limit in force, which is "
                        "not the same as a limit of nothing."
                    ),
                )
            )
        else:
            entity_after = entity_used + measure
            outcomes.append(
                CheckOutcome(
                    key="ENTITY_LIMIT",
                    name=CHECK_NAMES["ENTITY_LIMIT"],
                    passed=entity_after <= limit["amount_pence"],
                    detail=(
                        f"{counterparty['name']} would reach {sterling(entity_after)} "
                        f"against a limit of {sterling(limit['amount_pence'])}."
                    ),
                    workings=[
                        f"Already held {sterling(entity_used)}.",
                        f"This deal measures {sterling(measure)}, "
                        f"{inputs['proposed_measure_basis']}.",
                    ],
                )
            )

        # 4 -----------------------------------------------------------------
        if group is None:
            outcomes.append(
                CheckOutcome(
                    key="GROUP_LIMIT",
                    name=CHECK_NAMES["GROUP_LIMIT"],
                    passed=False,
                    detail="This counterparty is in no credit group, so the group "
                    "ceiling cannot be tested.",
                )
            )
        else:
            group_after = group_used + measure
            others = [
                f"Same credit: {c['counterparty_name']} {sterling(c['measure_pence'])}."
                for c in inputs["group_contributors"]
            ]
            outcomes.append(
                CheckOutcome(
                    key="GROUP_LIMIT",
                    name=CHECK_NAMES["GROUP_LIMIT"],
                    passed=group_after <= group["group_limit_pence"],
                    detail=(
                        f"{group['name']} would reach {sterling(group_after)} against "
                        f"a group limit of {sterling(group['group_limit_pence'])}."
                    ),
                    workings=others or ["Nothing else is held in this credit group."],
                )
            )

        # 5 -----------------------------------------------------------------
        if limit is None:
            outcomes.append(
                CheckOutcome(
                    key="TENOR_BAND",
                    name=CHECK_NAMES["TENOR_BAND"],
                    passed=False,
                    detail="No limit in force, so there is no permitted term to test "
                    "against.",
                )
            )
        else:
            months = proposal["tenor_months"]
            allowed = limit["max_tenor_months"]
            workings = []
            if band is not None and band["max_tenor_months"] != allowed:
                workings.append(
                    f"The {band['rating']} band allows {band['max_tenor_months']} "
                    f"months. The limit in force is held at {allowed}."
                )
            outcomes.append(
                CheckOutcome(
                    key="TENOR_BAND",
                    name=CHECK_NAMES["TENOR_BAND"],
                    passed=months <= allowed,
                    detail=(
                        f"{months} months, inside the {allowed} month maximum in "
                        f"force at {counterparty['rating']}."
                        if months <= allowed
                        else f"{months} months, against a maximum of {allowed} in "
                        f"force at {counterparty['rating']}."
                    ),
                    workings=workings,
                )
            )

        # 6 -----------------------------------------------------------------
        if portfolio is None or group is None:
            # Fails closed. Losing the balance feed blocks every deal, which
            # is correct for a control and disruptive in practice. Phase four
            # adds an explicit stale threshold and a visible warning rather
            # than this silent absence.
            outcomes.append(
                CheckOutcome(
                    key="CONCENTRATION",
                    name=CHECK_NAMES["CONCENTRATION"],
                    passed=False,
                    detail=(
                        "No balance has been fed for this date, so the portfolio "
                        "total has no denominator and this check fails rather than "
                        "passes."
                    ),
                )
            )
        else:
            group_after = group_used + measure
            total_after = portfolio + measure
            share_bp = round(group_after * BP / total_after) if total_after else 0
            outcomes.append(
                CheckOutcome(
                    key="CONCENTRATION",
                    name=CHECK_NAMES["CONCENTRATION"],
                    passed=share_bp <= policy["concentration_cap_bp"],
                    detail=(
                        f"{group['name']} would hold {per_cent(share_bp)} of a "
                        f"portfolio of {sterling(total_after)}, against a cap of "
                        f"{per_cent(policy['concentration_cap_bp'])}."
                    ),
                    workings=[
                        f"Portfolio includes {sterling(inputs['uninvested_cash_pence'] or 0)} "
                        "uninvested."
                    ],
                )
            )

        return outcomes

    # -------------------------------------------------------------- resize

    @staticmethod
    def largest_principal_that_passes(inputs: dict) -> int | None:
        """The amount the refusal offers as a route forward.

        A refusal that only says no is a refusal the user cannot act on. This
        is the largest principal that clears every amount constrained check at
        once, so accepting it does not simply move the failure to the next
        row.

        None when nothing would fit, or when an input the arithmetic needs is
        missing. It is never guessed.
        """
        limit = inputs["limit"]
        group = inputs["group"]
        policy = inputs["policy"]
        portfolio = inputs["portfolio_total_pence"]
        entity_used = inputs["entity_used_pence"]
        group_used = inputs["group_used_pence"]

        headrooms: list[int] = []

        if limit is not None:
            headrooms.append(limit["amount_pence"] - entity_used)

        if group is not None:
            headrooms.append(group["group_limit_pence"] - group_used)

        if group is not None and portfolio is not None:
            # (group_used + m) / (portfolio + m) <= cap
            #   =>  m <= (cap_bp * portfolio - BP * group_used) / (BP - cap_bp)
            cap_bp = policy["concentration_cap_bp"]
            denominator = BP - cap_bp
            if denominator <= 0:
                headrooms.append(max(0, portfolio))  # a cap of 100 per cent binds nothing
            else:
                numerator = cap_bp * portfolio - BP * group_used
                headrooms.append(numerator // denominator)

        if not headrooms:
            return None

        allowed_measure = min(headrooms)
        if allowed_measure <= 0:
            return None

        principal = principal_for_measure(
            instrument=inputs["proposal"]["instrument"],
            measure_pence=allowed_measure,
            fx_add_on_bp=policy["fx_add_on_bp"],
        )
        return principal or None

    # ----------------------------------------------------------------- run

    def run(
        self,
        counterparty_id: str,
        instrument: str,
        principal_pence: int,
        tenor_months: int,
        rate_bp: int,
        exclude_deal_id: str | None = None,
    ) -> Evaluation:
        inputs = self.gather_inputs(
            counterparty_id,
            instrument,
            principal_pence,
            tenor_months,
            rate_bp,
            exclude_deal_id,
        )
        outcomes = self.evaluate(inputs)
        failed = [o for o in outcomes if not o.passed]

        if failed:
            resize_to = self.largest_principal_that_passes(inputs)
            if resize_to is not None and resize_to < principal_pence:
                for outcome in failed:
                    if outcome.key in AMOUNT_CONSTRAINED:
                        outcome.resize_to_pence = resize_to

        measure = inputs["proposed_measure_pence"]
        approver = self.approvals.required_approver(principal_pence)
        enforcement = self.policy.enforcement

        if failed:
            verdict = (
                f"{len(failed)} of six checks failed. The policy in force is "
                + (
                    "a hard block."
                    if enforcement == "HARD_BLOCK"
                    else "warn with an override, so this can be recorded with a reason."
                )
            )
        else:
            verdict = (
                f"Measured at {sterling(measure)}, {inputs['proposed_measure_basis']}. "
                f"{self.approvals.phrase(approver)} has to sign."
            )

        return Evaluation(
            result=CheckResult(
                check_run_id=None,
                as_of_date=self.as_of_date,
                counterparty_id=counterparty_id,
                outcome="FAIL" if failed else "PASS",
                checks=outcomes,
                failed_count=len(failed),
                measured_pence=measure,
                measurement_basis=inputs["proposed_measure_basis"],
                required_approver=None if failed else approver,
                enforcement=enforcement,
                verdict=verdict,
                limit_id=(inputs["limit"] or {}).get("id"),
                policy_version_id=self.policy.id,
            ),
            inputs=inputs,
        )
