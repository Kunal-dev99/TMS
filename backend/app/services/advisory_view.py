"""Turning a run into the shapes the surface reads.

Separate from AdvisoryService because assembling a response is not a
decision, and the service is where decisions live. Nothing here computes a
figure: every number was written at stage 3 and every sentence at stage 4 or
5b.
"""

import json

from sqlalchemy.orm import Session

from app.formatting import sterling
from app.repo import counterparties as cp_repo
from app.schemas.models import (
    AdvisoryCard,
    AdvisoryRun,
    AdvisoryTicket,
    Candidate,
    ValidationResult,
)
from app.services.advisory_service import RunOutcome


def card_for(session: Session, outcome: RunOutcome) -> AdvisoryCard | None:
    """The card that sits above the ticket fields.

    An input to the work rather than an interruption of it, which is why it
    is inside the ticket column and not a banner across the page.
    """
    recommendation = outcome.recommendation
    if recommendation is None:
        return None

    chosen = next(
        (c for c in outcome.candidates if c.id == recommendation.candidate_id), None
    )
    names = {
        cp.id: cp.name for cp in cp_repo.list_all(session, outcome.run.tenant_id)
    }

    headline = _headline(outcome, chosen, names)
    return AdvisoryCard(
        run_id=outcome.run.id,
        as_of=outcome.run.as_of,
        gap_type=outcome.run.gap_type,
        gap_amount_minor=outcome.run.gap_amount_minor,
        gap_currency=outcome.run.gap_currency,
        gap_date=outcome.run.gap_date,
        recommendation_id=recommendation.id,
        headline=headline,
        # Null when the fallback produced the pick. The recommendation
        # survives; only the explanation is lost, and the source field says
        # so on screen.
        rationale=recommendation.rationale,
        source=recommendation.source,
        alternatives=json.loads(recommendation.alternatives_json),
        ticket=None
        if chosen is None
        else AdvisoryTicket(
            counterparty_id=chosen.counterparty_id,
            instrument=chosen.instrument,
            principal_pence=chosen.amount_pence,
            tenor_months=chosen.tenor_months,
            rate_bp=chosen.indicative_rate_bp,
        ),
    )


def _headline(outcome: RunOutcome, chosen, names: dict) -> str:
    run = outcome.run
    if run.gap_type == "CASH_SURPLUS" and run.gap_amount_minor:
        opening = f"{sterling(run.gap_amount_minor)} lands uninvested today"
    elif run.gap_type == "CASH_SHORTFALL" and run.gap_amount_minor:
        opening = f"{sterling(run.gap_amount_minor)} short of the liquidity buffer"
    elif run.gap_type == "LADDER_GAP":
        opening = "A bucket in the maturity ladder is below its target"
    elif run.gap_type == "CURRENCY_UNCOVERED":
        opening = "A currency obligation is below its cover target"
    else:
        opening = "Nothing to place"

    if chosen is None:
        return f"{opening}, and nothing compliant was available to place it with."
    name = names.get(chosen.counterparty_id, chosen.counterparty_id)
    return (
        f"{opening}. {sterling(chosen.amount_pence)} with {name} for "
        f"{chosen.tenor_months} months."
    )


def run_for(session: Session, outcome: RunOutcome) -> AdvisoryRun:
    names = {
        cp.id: cp.name for cp in cp_repo.list_all(session, outcome.run.tenant_id)
    }
    return AdvisoryRun(
        card=card_for(session, outcome)
        or AdvisoryCard(
            run_id=outcome.run.id,
            as_of=outcome.run.as_of,
            gap_type=outcome.run.gap_type,
            gap_amount_minor=outcome.run.gap_amount_minor,
            gap_currency=outcome.run.gap_currency,
            gap_date=outcome.run.gap_date,
            recommendation_id=None,
            headline=_headline(outcome, None, names),
            rationale=None,
            source="RULE_FALLBACK",
            alternatives=[],
            ticket=None,
        ),
        candidates=[
            Candidate(
                id=candidate.id,
                counterparty_id=candidate.counterparty_id,
                counterparty_name=names.get(
                    candidate.counterparty_id, candidate.counterparty_id
                ),
                instrument=candidate.instrument,
                amount_pence=candidate.amount_pence,
                tenor_months=candidate.tenor_months,
                indicative_rate_bp=candidate.indicative_rate_bp,
                score_bp=candidate.score_bp,
                excluded=bool(candidate.excluded),
                exclusion_reason=candidate.exclusion_reason,
                rank=candidate.rank,
            )
            for candidate in outcome.candidates
        ],
        validation=[
            ValidationResult(
                test=row.test, passed=bool(row.passed), detail=row.detail
            )
            for row in outcome.validation
        ],
        outcome=outcome.run.outcome,
        model_enabled=bool(outcome.run.model_enabled),
        model_name=outcome.run.model_name,
        started_at=outcome.run.started_at,
        finished_at=outcome.run.finished_at,
    )
