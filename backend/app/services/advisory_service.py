"""Phase 2. The advisory layer.

Six stages, one of which calls a model. The other five exist so that the one
which does cannot go wrong.

    1  Assemble context      deterministic, by query
    2  Detect the gap        deterministic, against the investment policy
    3  Build candidates      deterministic. The main guardrail
    4  Rank and explain      the model
    5  Validate              deterministic. Three tests
    5b Rule based pick       the fallback, flagged as such
    6  Accept or edit        a person. Books nothing

Hallucination is removed rather than instructed against. There is no prompt
saying do not invent counterparties: stage 3 builds a bounded, priced,
already compliant list, the model returns an identifier from it, and the
recommendation carries a foreign key to a candidate row the rules created.
There is no free text field for a name and no arithmetic for the model to
do.

The dashed edge. This service writes no deal and sets no deal status. The
only path from a recommendation into the book runs through a person and then
through the same six checks as a deal somebody typed, and the deal endpoint
is what sets the recommendation deal_id afterwards.
"""

import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ErrorCode, TreasuryError
from app.formatting import sterling
from app.ids import new_id, now
from app.models import (
    AdvisoryRun,
    Candidate,
    ForecastLine,
    InvestmentPolicy,
    LadderTarget,
    PolicyVersion,
    Recommendation,
    ValidationResult,
)
from app.repo import counterparties as cp_repo
from app.repo import deals as deal_repo
from app.services.check_engine import CheckEngine
from app.services.exposure_service import BUCKETS
from app.services.ranker import ranker_for

#: What a candidate is offered at. A real desk quotes; this reads the rating
#: band and adds a spread, so the figure is derived from data the customer
#: owns rather than invented. Every rate in a recommendation comes from here.
BASE_RATE_BP = 400
RATING_SPREAD_BP = {
    "AAA": -10, "AA": 0, "AA-": 8, "A+": 20, "A": 26,
    "A-": 32, "BBB+": 48, "BBB": 60, "BBB-": 75, "BB+": 0,
}
TENOR_SPREAD_BP = {3: 0, 6: 12, 12: 22, 24: 35}


@dataclass
class RunOutcome:
    run: AdvisoryRun
    recommendation: Recommendation | None
    candidates: list[Candidate]
    validation: list[ValidationResult]


class AdvisoryService:
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
        self.checks = CheckEngine(session, tenant_id, as_of_date, policy)

    # ------------------------------------------------------------- policy

    def investment_policy(self) -> InvestmentPolicy | None:
        return self.session.scalars(
            select(InvestmentPolicy)
            .where(InvestmentPolicy.tenant_id == self.tenant_id)
            .where(InvestmentPolicy.superseded_at.is_(None))
        ).one_or_none()

    def ladder_targets(self, policy_id: str) -> list[LadderTarget]:
        return list(
            self.session.scalars(
                select(LadderTarget).where(LadderTarget.policy_id == policy_id)
            )
        )

    # ---------------------------------------------------------------- run

    def run(self, as_of: str | None = None, force: bool = False) -> RunOutcome:
        target = as_of or self.as_of_date
        investment = self.investment_policy()
        if investment is None:
            # The refusal is a feature. Without a buffer, a ladder and cover
            # targets there is nothing to measure a gap against, and guessing
            # any of them would be inventing a policy the customer owns.
            raise TreasuryError(ErrorCode.NO_INVESTMENT_POLICY)

        existing = self.session.scalars(
            select(AdvisoryRun)
            .where(AdvisoryRun.tenant_id == self.tenant_id)
            .where(AdvisoryRun.as_of == target)
            .order_by(AdvisoryRun.started_at.desc())
        ).first()
        if existing is not None and not force:
            return self._load(existing)

        run = AdvisoryRun(
            id=new_id("adv"),
            tenant_id=self.tenant_id,
            as_of=target,
            started_at=now(),
            policy_id=investment.id,
            gap_type="NONE",
            model_enabled=investment.model_enabled,
            model_name=None,
            outcome="NO_GAP",
        )

        context = self._stage_one_context(target)
        gap = self._stage_two_gap(context, investment, target)

        run.gap_type = gap["type"]
        run.gap_amount_minor = gap["amount_minor"]
        run.gap_currency = gap["currency"]
        run.gap_date = gap["date"]

        self.session.add(run)
        self.session.flush()

        if gap["type"] == "NONE":
            # With no gap the model is never called at all.
            run.outcome = "NO_GAP"
            run.finished_at = now()
            self.session.flush()
            self._expire_earlier(run)
            return RunOutcome(run=run, recommendation=None, candidates=[], validation=[])

        candidates = self._stage_three_candidates(run, gap, context)
        eligible = [c for c in candidates if not c.excluded]

        if not eligible:
            run.outcome = "NO_CANDIDATES"
            run.finished_at = now()
            self.session.flush()
            self._expire_earlier(run)
            return RunOutcome(
                run=run, recommendation=None, candidates=candidates, validation=[]
            )

        pick, validation = self._stage_four_and_five(run, eligible, context, gap)

        recommendation = Recommendation(
            id=new_id("rec"),
            run_id=run.id,
            candidate_id=pick.candidate_id,
            rationale=pick.rationale,
            alternatives_json=json.dumps(
                [
                    self._alternative_sentence(candidate, context)
                    for candidate in candidates
                    if candidate.id != pick.candidate_id
                ]
            ),
            source=pick.source,
            decision=None,
        )
        run.finished_at = now()
        self.session.add(recommendation)
        self.session.flush()
        self._expire_earlier(run)

        return RunOutcome(
            run=run,
            recommendation=recommendation,
            candidates=candidates,
            validation=validation,
        )

    # ------------------------------------------------------------ stage 1

    def _stage_one_context(self, target: str) -> dict:
        """Built by query from data already owned.

        There is no retrieval quality problem here because nothing is
        retrieved: the four inputs are the book, the forecast, the policy and
        the clock.
        """
        from app.repo import oracle as oracle_repo

        counterparties = cp_repo.list_all(self.session, self.tenant_id)
        live = deal_repo.live_for_tenant(self.session, self.tenant_id)

        buckets = {key: 0 for key, _label, _days in BUCKETS}
        for deal in live:
            buckets[self._bucket(deal.maturity_date, target)] += deal.principal_pence

        inflow = (
            self.session.scalar(
                select(func.sum(ForecastLine.amount_minor))
                .where(ForecastLine.tenant_id == self.tenant_id)
                .where(ForecastLine.currency == "GBP")
                .where(ForecastLine.forecast_date <= target)
            )
            or 0
        )

        return {
            "as_of": target,
            "cash_pence": oracle_repo.uninvested_cash_pence(
                self.session, self.tenant_id, target
            )
            or 0,
            "forecast_inflow_pence": int(inflow),
            "invested_pence": sum(deal.principal_pence for deal in live),
            "buckets": buckets,
            "names": {cp.id: cp.name for cp in counterparties},
            "ratings": {cp.id: cp.rating for cp in counterparties},
            "counterparties": counterparties,
        }

    def _bucket(self, maturity_date: str | None, target: str) -> str:
        if maturity_date is None:
            return "OVER_12M"
        days = (date.fromisoformat(maturity_date) - date.fromisoformat(target)).days
        for key, _label, ceiling in BUCKETS:
            if ceiling is not None and days <= ceiling:
                return key
        return "OVER_12M"

    # ------------------------------------------------------------ stage 2

    def _stage_two_gap(
        self, context: dict, investment: InvestmentPolicy, target: str
    ) -> dict:
        """Arithmetic against the investment policy. No model is involved.

        Cash above the buffer is a surplus and comes first, because money
        sitting uninvested is the loudest gap. A ladder bucket below its
        target is the second, and it changes the term rather than the amount.
        """
        available = context["cash_pence"] + context["forecast_inflow_pence"]
        surplus = available - investment.liquidity_buffer_pence

        if surplus > 0:
            return {
                "type": "CASH_SURPLUS",
                "amount_minor": surplus,
                "currency": "GBP",
                "date": target,
                "bucket": self._emptiest_bucket(context, investment),
            }

        if surplus < 0:
            return {
                "type": "CASH_SHORTFALL",
                "amount_minor": -surplus,
                "currency": "GBP",
                "date": target,
                "bucket": None,
            }

        empty = self._emptiest_bucket(context, investment)
        if empty is not None:
            return {
                "type": "LADDER_GAP",
                "amount_minor": 0,
                "currency": "GBP",
                "date": target,
                "bucket": empty,
            }

        return {"type": "NONE", "amount_minor": None, "currency": None, "date": None, "bucket": None}

    def _emptiest_bucket(self, context: dict, investment: InvestmentPolicy) -> str | None:
        targets = {t.bucket: t for t in self.ladder_targets(investment.id)}
        if not targets:
            return None
        total = sum(context["buckets"].values()) or 1
        worst = None
        worst_shortfall = 0
        for bucket, target in targets.items():
            held = context["buckets"].get(bucket, 0)
            share_bp = round(held * 10_000 / total)
            shortfall = target.target_share_bp - share_bp
            if held < target.minimum_pence:
                shortfall = max(shortfall, 1)
            if shortfall > worst_shortfall:
                worst, worst_shortfall = bucket, shortfall
        return worst

    # ------------------------------------------------------------ stage 3

    def _stage_three_candidates(
        self, run: AdvisoryRun, gap: dict, context: dict
    ) -> list[Candidate]:
        """The main guardrail.

        Anything that would fail the six checks is excluded before the list
        exists, and the exclusion is recorded with its reason. Excluded
        candidates never reach the model, so it cannot pick one.
        """
        amount = gap["amount_minor"] or 0
        tenor = self._tenor_for(gap.get("bucket"))
        rows: list[Candidate] = []

        for counterparty in context["counterparties"]:
            if counterparty.status != "ACTIVE":
                continue
            if "DEPOSIT" not in cp_repo.permitted_instruments(
                self.session, counterparty.id
            ):
                continue

            rate = self._indicative_rate(counterparty.rating, tenor)
            evaluation = self.checks.run(
                counterparty.id, "DEPOSIT", amount, tenor, rate
            )
            failed = [c for c in evaluation.result.checks if not c.passed]

            candidate = Candidate(
                id=new_id("cnd"),
                run_id=run.id,
                counterparty_id=counterparty.id,
                instrument="DEPOSIT",
                amount_pence=amount,
                tenor_months=tenor,
                indicative_rate_bp=rate,
                score_bp=0,
                excluded=1 if failed else 0,
                exclusion_reason=self._exclusion_sentence(failed) if failed else None,
                rank=None,
            )
            candidate.score_bp = 0 if failed else self._score(
                candidate, counterparty, context
            )
            rows.append(candidate)
            self.session.add(candidate)

        self.session.flush()

        eligible = sorted(
            (row for row in rows if not row.excluded),
            key=lambda row: row.score_bp,
            reverse=True,
        )
        for position, row in enumerate(eligible, start=1):
            row.rank = position
        self.session.flush()
        return rows

    @staticmethod
    def _tenor_for(bucket: str | None) -> int:
        return {"0_3M": 3, "3_6M": 6, "6_12M": 12, "OVER_12M": 24}.get(bucket or "", 6)

    @staticmethod
    def _indicative_rate(rating: str, tenor_months: int) -> int:
        return (
            BASE_RATE_BP
            + RATING_SPREAD_BP.get(rating, 0)
            + TENOR_SPREAD_BP.get(tenor_months, 12)
        )

    def _score(self, candidate: Candidate, counterparty, context: dict) -> int:
        """Yield, headroom impact and ladder fit, weighted.

        Computed on every eligible candidate whether or not the model runs,
        which is what makes the fallback always available rather than a code
        path nobody has exercised.

        The weights follow the policy priority order, so a customer who puts
        security before yield gets a different ranking without a code change.
        """
        investment = self.investment_policy()
        priorities = (investment.priority_order if investment else "").split(",")
        yield_weight = 3 if priorities and priorities[-1].strip() == "YIELD" else 5

        limit = cp_repo.current_limit(self.session, counterparty.id)
        headroom_bp = 0
        if limit and limit.amount_pence:
            used = self.checks.exposure.entity_exposure(counterparty.id).amount_pence
            headroom_bp = round(
                max(0, limit.amount_pence - used - candidate.amount_pence)
                * 10_000
                / limit.amount_pence
            )

        quality = RATING_SPREAD_BP.get(counterparty.rating, 50)
        return (
            candidate.indicative_rate_bp * yield_weight
            + headroom_bp
            - quality * 4
        )

    @staticmethod
    def _exclusion_sentence(failed: list) -> str:
        first = failed[0]
        return f"Excluded before ranking. {first.detail}"

    def _alternative_sentence(self, candidate: Candidate, context: dict) -> str:
        name = context["names"].get(candidate.counterparty_id, candidate.counterparty_id)
        if candidate.excluded:
            return f"{name}: {candidate.exclusion_reason}"
        return (
            f"{name}: ranked {candidate.rank} on "
            f"{sterling(candidate.amount_pence)} for {candidate.tenor_months} months."
        )

    # -------------------------------------------------------- stages 4, 5

    def _stage_four_and_five(
        self, run: AdvisoryRun, eligible: list[Candidate], context: dict, gap: dict
    ):
        """Rank, then validate. Fall back rather than fail.

        Three tests, all of which must pass: the identifier is real, the six
        checks rerun clean, and every figure in the prose matches a value
        computed at stage 3. A confident wrong answer is rejected, the
        deterministic pick is shown instead, and the source field says
        RULE_FALLBACK on screen.
        """
        import logging

        from app.services.ranker import WeightedScoreRanker

        ranker = ranker_for(bool(run.model_enabled))
        attempted = bool(run.model_enabled)
        run.model_name = ranker.name if attempted else None

        try:
            investment = self.investment_policy()
            pick = ranker.rank(
                eligible,
                {
                    **context,
                    "gap_type": gap["type"],
                    "priority_order": investment.priority_order if investment else "",
                },
            )
        except Exception as failure:
            # Unreachable, slow, or answering with something unreadable. The
            # recommendation survives either way, but the reason must not
            # vanish: a model that has been failing for a week looks exactly
            # like one that is switched off unless somebody is told.
            logging.getLogger(__name__).warning(
                "Advisory run %s: the model call failed, falling back to the "
                "weighted score. %s: %s",
                run.id,
                type(failure).__name__,
                failure,
            )
            pick = WeightedScoreRanker().rank(eligible, context)

        validation = self._validate(run, pick, eligible, context)
        if all(row.passed for row in validation):
            if pick.source == "MODEL":
                run.outcome = "MODEL_ACCEPTED"
            else:
                # RULE_ONLY means the model was switched off in the policy.
                # A model that was asked and did not answer is a different
                # thing, and calling both the same would hide an outage.
                run.outcome = (
                    "MODEL_REJECTED_FALLBACK" if attempted else "RULE_ONLY"
                )
            self.session.flush()
            return pick, validation

        fallback = WeightedScoreRanker().rank(eligible, context)
        run.outcome = "MODEL_REJECTED_FALLBACK"
        self.session.flush()
        return fallback, validation

    def _validate(
        self, run: AdvisoryRun, pick, eligible: list[Candidate], context: dict
    ) -> list[ValidationResult]:
        by_id = {candidate.id: candidate for candidate in eligible}
        chosen = by_id.get(pick.candidate_id)

        results = [
            self._record(
                run,
                "ID_IS_REAL",
                chosen is not None,
                f"{pick.candidate_id} is a row in this run."
                if chosen is not None
                else f"{pick.candidate_id} is not a candidate from this run.",
            )
        ]

        if chosen is None:
            results.append(self._record(run, "CHECKS_RERUN_CLEAN", False, "No candidate."))
            results.append(self._record(run, "FIGURES_AGREE", False, "No candidate."))
            return results

        rerun = self.checks.run(
            chosen.counterparty_id,
            chosen.instrument,
            chosen.amount_pence,
            chosen.tenor_months,
            chosen.indicative_rate_bp,
        )
        failed = [c for c in rerun.result.checks if not c.passed]
        results.append(
            self._record(
                run,
                "CHECKS_RERUN_CLEAN",
                not failed,
                "Six of six passed."
                if not failed
                else f"{len(failed)} failed on the rerun: {failed[0].detail}",
            )
        )

        # Every figure in the prose has to match one computed at stage 3.
        # The model has no arithmetic to do, so a figure that does not match
        # is a figure it invented.
        agree, detail = self._figures_agree(pick.rationale, chosen)
        results.append(self._record(run, "FIGURES_AGREE", agree, detail))
        return results

    @staticmethod
    def _figures_agree(rationale: str | None, candidate: Candidate) -> tuple[bool, str]:
        if not rationale:
            return True, "No prose to check. The rule based pick writes none."

        import re

        permitted = {
            f"{candidate.indicative_rate_bp / 100:.2f}",
            f"{candidate.tenor_months}",
            f"{round(candidate.amount_pence / 100):,}",
        }
        quoted = set(re.findall(r"\d[\d,]*\.?\d*", rationale))
        invented = {
            figure
            for figure in quoted
            if figure not in permitted and figure.replace(",", "") not in permitted
        }
        if invented:
            return False, f"Figures not computed at stage 3: {sorted(invented)}"
        return True, "Every figure matches a value computed at stage 3."

    def _record(
        self, run: AdvisoryRun, test: str, passed: bool, detail: str
    ) -> ValidationResult:
        row = ValidationResult(
            id=new_id("val"),
            run_id=run.id,
            test=test,
            passed=1 if passed else 0,
            detail=detail,
        )
        self.session.add(row)
        return row

    # ------------------------------------------------------------ stage 6

    def decide(
        self, recommendation_id: str, decision: str, decider, reason: str | None
    ) -> tuple[Recommendation, Candidate | None]:
        """Record what a person decided. Books nothing.

        The deal is created by POST /deals like any other and passes the same
        six checks. That is the whole of the guardrail, expressed as an API
        shape rather than as a policy.
        """
        recommendation = self.session.get(Recommendation, recommendation_id)
        if recommendation is None:
            raise TreasuryError(ErrorCode.RUN_NOT_FOUND, "That recommendation does not exist.")
        if recommendation.decision is not None:
            if recommendation.decision == "EXPIRED":
                raise TreasuryError(ErrorCode.RECOMMENDATION_EXPIRED)
            raise TreasuryError(ErrorCode.ALREADY_DECIDED)
        if decision == "REJECTED" and not reason:
            raise TreasuryError(ErrorCode.REJECTION_REASON_REQUIRED, field="reason")

        recommendation.decision = decision
        recommendation.decided_by = str(decider)
        recommendation.decided_by_user_id = decider.user_id
        recommendation.decided_at = now()
        recommendation.decision_reason = reason
        self.session.flush()

        if decision == "REJECTED":
            return recommendation, None
        return recommendation, self.session.get(Candidate, recommendation.candidate_id)

    def latest(self) -> RunOutcome | None:
        """The current recommendation, if there is one.

        Null is a valid answer and not a 404: no gap is a real state, and so
        is a recommendation somebody has already acted on.
        """
        run = self.session.scalars(
            select(AdvisoryRun)
            .where(AdvisoryRun.tenant_id == self.tenant_id)
            .order_by(AdvisoryRun.as_of.desc(), AdvisoryRun.started_at.desc())
        ).first()
        return self._load(run) if run else None

    def load_run(self, run_id: str) -> RunOutcome:
        run = self.session.get(AdvisoryRun, run_id)
        if run is None or run.tenant_id != self.tenant_id:
            raise TreasuryError(ErrorCode.RUN_NOT_FOUND)
        return self._load(run)

    def _load(self, run: AdvisoryRun) -> RunOutcome:
        return RunOutcome(
            run=run,
            recommendation=self.session.scalars(
                select(Recommendation).where(Recommendation.run_id == run.id)
            ).first(),
            candidates=list(
                self.session.scalars(
                    select(Candidate)
                    .where(Candidate.run_id == run.id)
                    .order_by(Candidate.excluded, Candidate.rank)
                )
            ),
            validation=list(
                self.session.scalars(
                    select(ValidationResult).where(ValidationResult.run_id == run.id)
                )
            ),
        )

    def _expire_earlier(self, run: AdvisoryRun) -> None:
        """A recommendation not acted on before the next run expires rather
        than persisting. Yesterday's advice against today's forecast is worse
        than no advice."""
        stale = self.session.scalars(
            select(Recommendation)
            .join(AdvisoryRun, AdvisoryRun.id == Recommendation.run_id)
            .where(AdvisoryRun.tenant_id == self.tenant_id)
            .where(Recommendation.run_id != run.id)
            .where(Recommendation.decision.is_(None))
        )
        for recommendation in stale:
            recommendation.decision = "EXPIRED"
            recommendation.decided_at = now()
        self.session.flush()
