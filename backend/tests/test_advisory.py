"""Phase 2, the advisory layer.

Document 5 sets two exit criteria for this half:

    A recommendation that fails validation still appears, with the rule
    based pick flagged as such and only the explanation lost.

    Accepting a recommendation produces a deal that carries a check run
    identical in shape to a typed deal.

The rest of this file tests the four failures document 4 says the design
makes structurally impossible: an invented counterparty, an invented figure,
a recommendation against policy, and a confident wrong answer.

Those are not tested by prompting a model and hoping. They are tested by
showing there is no code path that could produce them.
"""

import json

from app import seed_data as s
from app.repo import policy as policy_repo
from app.services.advisory_service import AdvisoryService
from app.services.nightly_job import NightlyJob

P = 100


def _advisory(session):
    policy = policy_repo.current_policy(session, s.TENANT_ID)
    return AdvisoryService(session, s.TENANT_ID, s.CLOCK_DATE, policy)


def _run(session, force=False):
    outcome = _advisory(session).run(force=force)
    session.commit()
    return outcome


# ==========================================================================
# Stage 2. With no gap the model is never called at all.
# ==========================================================================


def test_a_run_is_written_even_when_there_is_no_gap(session):
    """A run that found nothing is evidence that the layer looked.

    The buffer is raised to absorb the cash and the forecast rather than the
    balance being removed: losing the balance would fail the concentration
    check closed, which is a different state and a different test.
    """
    from app.models import InvestmentPolicy

    for policy in session.query(InvestmentPolicy).all():
        policy.liquidity_buffer_pence = 10_000_000 * P
    session.flush()

    outcome = _run(session)

    # A ladder that is off target is still a gap worth acting on, so the
    # seeded book may report one. Either way there is a run.
    assert outcome.run.id
    assert outcome.run.gap_type in ("NONE", "LADDER_GAP")
    if outcome.run.gap_type == "NONE":
        assert outcome.run.outcome == "NO_GAP"
        assert outcome.recommendation is None
        assert outcome.candidates == [], "With no gap the model is never called."


def test_the_gap_is_the_cash_above_the_buffer_plus_the_forecast(session):
    """8,000,000 of cash plus 2,000,000 forecast to arrive, less a 2,000,000
    buffer that has to stay available."""
    outcome = _run(session)
    assert outcome.run.gap_type == "CASH_SURPLUS"
    assert outcome.run.gap_amount_minor == 8_000_000 * P
    assert outcome.run.gap_currency == "GBP"


def test_the_layer_refuses_without_an_investment_policy(session):
    """The refusal is a feature, because it is also the conversation that
    shapes the customer policy."""
    from app.errors import TreasuryError
    from app.models import InvestmentPolicy

    for policy in session.query(InvestmentPolicy).all():
        policy.superseded_at = "2026-09-02T00:00:00+00:00"
    session.flush()

    try:
        _advisory(session).run()
    except TreasuryError as refusal:
        assert refusal.code.value == "NO_INVESTMENT_POLICY"
        assert "liquidity buffer" in refusal.message
    else:
        raise AssertionError("The layer ran without a policy.")


# ==========================================================================
# Stage 3. The main guardrail.
# ==========================================================================


def test_anything_that_would_fail_the_six_checks_is_excluded_before_ranking(session):
    outcome = _run(session)

    excluded = [c for c in outcome.candidates if c.excluded]
    assert excluded, "Nothing was excluded, so the guardrail was not exercised."
    for candidate in excluded:
        assert candidate.exclusion_reason
        assert candidate.exclusion_reason.startswith("Excluded before ranking.")


def test_an_excluded_candidate_is_never_ranked(session):
    """Document 1 lists this as an invariant the schema cannot hold."""
    outcome = _run(session)
    for candidate in outcome.candidates:
        if candidate.excluded:
            assert candidate.rank is None


def test_the_exclusion_states_the_arithmetic(session):
    """Why was X not picked is the question that gets asked, and the
    exclusion is the guardrail rather than the ranking."""
    outcome = _run(session)
    reasons = " ".join(c.exclusion_reason or "" for c in outcome.candidates)
    assert "£" in reasons


def test_every_figure_in_the_recommendation_was_computed_at_stage_three(session):
    """The model never generates a rate. indicative_rate_bp is where every
    figure in the recommendation comes from."""
    outcome = _run(session)
    chosen = next(
        c for c in outcome.candidates if c.id == outcome.recommendation.candidate_id
    )
    assert chosen.indicative_rate_bp > 0
    assert chosen.amount_pence == outcome.run.gap_amount_minor


def test_a_score_is_computed_on_every_eligible_candidate(session):
    """Whether or not the model runs, so the fallback is always available
    rather than a code path nobody has exercised."""
    outcome = _run(session)
    for candidate in outcome.candidates:
        if not candidate.excluded:
            assert candidate.score_bp != 0


# ==========================================================================
# Stage 5. Validation, and the exit criterion about falling back.
# ==========================================================================


def test_the_three_validation_tests_all_run(session):
    outcome = _run(session)
    assert {row.test for row in outcome.validation} == {
        "ID_IS_REAL",
        "CHECKS_RERUN_CLEAN",
        "FIGURES_AGREE",
    }
    assert all(row.passed for row in outcome.validation)


def test_a_recommendation_that_fails_validation_still_appears(session, monkeypatch):
    """The exit criterion.

    A model that invents a figure is caught, the deterministic pick is shown
    instead, and only the explanation is lost.
    """
    from app.services import ranker as ranker_module

    class Inventing:
        name = "inventing-stub"

        def rank(self, candidates, context):
            best = max(candidates, key=lambda c: c.score_bp)
            return ranker_module.RankedPick(
                candidate_id=best.id,
                # 9.99 per cent was never computed at stage 3.
                rationale="A rate of 9.99 per cent, which nobody quoted.",
                source="MODEL",
            )

    monkeypatch.setattr(ranker_module, "ModelRanker", Inventing)
    outcome = _run(session, force=True)

    figures = next(row for row in outcome.validation if row.test == "FIGURES_AGREE")
    assert not figures.passed
    assert "9.99" in figures.detail

    assert outcome.recommendation is not None, "The recommendation vanished."
    assert outcome.recommendation.source == "RULE_FALLBACK"
    assert outcome.recommendation.rationale is None, "Only the explanation is lost."
    assert outcome.run.outcome == "MODEL_REJECTED_FALLBACK"


def test_a_model_that_names_a_candidate_from_another_run_is_caught(session, monkeypatch):
    from app.services import ranker as ranker_module

    class Inventing:
        name = "inventing-stub"

        def rank(self, candidates, context):
            return ranker_module.RankedPick(
                candidate_id="cnd_not_from_this_run",
                rationale="A name nobody offered.",
                source="MODEL",
            )

    monkeypatch.setattr(ranker_module, "ModelRanker", Inventing)
    outcome = _run(session, force=True)

    identity = next(row for row in outcome.validation if row.test == "ID_IS_REAL")
    assert not identity.passed
    assert outcome.recommendation.source == "RULE_FALLBACK"


def test_a_model_that_raises_falls_back_rather_than_failing(session, monkeypatch):
    """The recommendation always exists. Only the explanation is lost."""
    from app.services import ranker as ranker_module

    class Unreachable:
        name = "unreachable"

        def rank(self, candidates, context):
            raise RuntimeError("The model endpoint timed out")

    monkeypatch.setattr(ranker_module, "ModelRanker", Unreachable)
    outcome = _run(session, force=True)

    assert outcome.recommendation is not None
    assert outcome.recommendation.source == "RULE_FALLBACK"


def test_switching_the_model_off_swaps_the_implementation_and_nothing_else(session):
    """model_enabled is a policy field rather than an environment variable,
    so a customer owns it and can turn it off without a deployment."""
    from app.models import InvestmentPolicy

    for policy in session.query(InvestmentPolicy).all():
        policy.model_enabled = 0
    session.flush()

    outcome = _run(session, force=True)

    assert outcome.recommendation is not None
    assert outcome.recommendation.source == "RULE_FALLBACK"
    assert outcome.recommendation.rationale is None
    assert outcome.run.model_name is None
    assert outcome.run.outcome == "RULE_ONLY"
    # The candidates are unchanged: the same list, priced the same way.
    assert len([c for c in outcome.candidates if not c.excluded]) >= 1


# ==========================================================================
# The dashed edge. Accepting books nothing.
# ==========================================================================


def test_deciding_creates_no_deal(client, session):
    from app.models import Deal

    client.post("/api/v1/jobs/nightly", json={})
    before = session.query(Deal).count()

    card = client.get("/api/v1/advisory/latest").json()
    response = client.post(
        f"/api/v1/advisory/recommendations/{card['recommendation_id']}/decide",
        json={"decision": "ACCEPTED"},
    )
    assert response.status_code == 200
    assert response.json()["ticket"] is not None

    assert session.query(Deal).count() == before, (
        "The advisory layer wrote a deal. The only path into the book runs "
        "through a person and then through the six checks."
    )


def test_the_ticket_is_the_same_five_fields_somebody_would_have_typed(client):
    client.post("/api/v1/jobs/nightly", json={})
    card = client.get("/api/v1/advisory/latest").json()

    ticket = client.post(
        f"/api/v1/advisory/recommendations/{card['recommendation_id']}/decide",
        json={"decision": "ACCEPTED"},
    ).json()["ticket"]

    assert set(ticket) == {
        "counterparty_id",
        "instrument",
        "principal_pence",
        "tenor_months",
        "rate_bp",
    }, "A sixth field would be a result the checks might trust."


def test_accepting_produces_a_deal_with_a_check_run_like_any_other(client, session):
    """The exit criterion.

    The check run behind an accepted recommendation has to be identical in
    shape to one behind a deal somebody typed, because it went through the
    same engine.
    """
    client.post("/api/v1/jobs/nightly", json={})
    card = client.get("/api/v1/advisory/latest").json()

    ticket = client.post(
        f"/api/v1/advisory/recommendations/{card['recommendation_id']}/decide",
        json={"decision": "ACCEPTED"},
    ).json()["ticket"]

    from_advice = client.post(
        "/api/v1/deals",
        json={**ticket, "recommendation_id": card["recommendation_id"]},
    ).json()

    typed = client.post(
        "/api/v1/deals",
        json={
            "counterparty_id": "cp_meridian",
            "instrument": "DEPOSIT",
            "principal_pence": 500_000 * P,
            "tenor_months": 6,
            "rate_bp": 425,
        },
    ).json()

    assert set(from_advice["run"]) == set(typed["run"])
    assert [c["key"] for c in from_advice["run"]["checks"]] == [
        c["key"] for c in typed["run"]["checks"]
    ]
    assert from_advice["run"]["check_run_id"] is not None

    from app.repo import evidence as evidence_repo

    stored = evidence_repo.get_check_run(session, from_advice["run"]["check_run_id"])
    assert stored.purpose == "BOOKING"
    assert stored.policy_version_id == "pol_v1"


def test_the_recommendation_carries_the_deal_only_after_it_was_recorded(
    client, session
):
    """A recommendation may only carry a deal_id for a deal that passed the
    six checks, and the deal endpoint is what writes it."""
    from app.models import Recommendation

    client.post("/api/v1/jobs/nightly", json={})
    card = client.get("/api/v1/advisory/latest").json()

    recommendation = session.get(Recommendation, card["recommendation_id"])
    assert recommendation.deal_id is None

    ticket = client.post(
        f"/api/v1/advisory/recommendations/{card['recommendation_id']}/decide",
        json={"decision": "ACCEPTED"},
    ).json()["ticket"]
    assert session.get(Recommendation, card["recommendation_id"]).deal_id is None, (
        "Deciding set a deal_id, and deciding books nothing."
    )

    booked = client.post(
        "/api/v1/deals",
        json={**ticket, "recommendation_id": card["recommendation_id"]},
    ).json()

    session.expire_all()
    assert (
        session.get(Recommendation, card["recommendation_id"]).deal_id
        == booked["deal"]["id"]
    )


def test_a_rejection_needs_a_reason(client):
    """The disagreement log is the most valuable data this produces."""
    client.post("/api/v1/jobs/nightly", json={})
    card = client.get("/api/v1/advisory/latest").json()

    refused = client.post(
        f"/api/v1/advisory/recommendations/{card['recommendation_id']}/decide",
        json={"decision": "REJECTED"},
    )
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "REJECTION_REASON_REQUIRED"

    allowed = client.post(
        f"/api/v1/advisory/recommendations/{card['recommendation_id']}/decide",
        json={"decision": "REJECTED", "reason": "Holding cash for the VAT payment."},
    )
    assert allowed.status_code == 200
    assert allowed.json()["ticket"] is None


def test_a_recommendation_cannot_be_decided_twice(client):
    client.post("/api/v1/jobs/nightly", json={})
    card = client.get("/api/v1/advisory/latest").json()
    payload = {"decision": "ACCEPTED"}

    assert (
        client.post(
            f"/api/v1/advisory/recommendations/{card['recommendation_id']}/decide",
            json=payload,
        ).status_code
        == 200
    )
    second = client.post(
        f"/api/v1/advisory/recommendations/{card['recommendation_id']}/decide",
        json=payload,
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "ALREADY_DECIDED"


def test_a_recommendation_not_acted_on_expires_when_the_next_run_lands(
    client, session
):
    """Yesterday's advice against today's forecast is worse than no advice."""
    from app.models import Recommendation

    client.post("/api/v1/jobs/nightly", json={})
    first = client.get("/api/v1/advisory/latest").json()["recommendation_id"]

    client.post("/api/v1/admin/clock", json={"today_date": "2026-09-04"})
    client.post("/api/v1/jobs/nightly", json={})

    session.expire_all()
    assert session.get(Recommendation, first).decision == "EXPIRED"


def test_the_decision_names_who_made_it_by_identifier(client, session):
    from app.models import Recommendation

    client.post("/api/v1/jobs/nightly", json={})
    card = client.get("/api/v1/advisory/latest").json()
    client.post(
        f"/api/v1/advisory/recommendations/{card['recommendation_id']}/decide",
        json={"decision": "REJECTED", "reason": "Not this week."},
    )

    session.expire_all()
    recommendation = session.get(Recommendation, card["recommendation_id"])
    assert recommendation.decided_by_user_id == "usr_whitfield"
    assert recommendation.decision_reason == "Not this week."


# ==========================================================================
# The card and the run, as the surface reads them
# ==========================================================================


def test_the_card_is_folded_into_the_one_state_call(client):
    client.post("/api/v1/jobs/nightly", json={})
    card = client.get("/api/v1/state").json()["advisory"]

    assert card is not None
    assert card["gap_type"] == "CASH_SURPLUS"
    assert "£8,000,000" in card["headline"]
    assert card["ticket"]["principal_pence"] == 8_000_000 * P


def test_the_card_disappears_once_somebody_has_decided(client):
    """Null is a valid answer. An empty card would imply something is
    broken."""
    client.post("/api/v1/jobs/nightly", json={})
    card = client.get("/api/v1/state").json()["advisory"]
    client.post(
        f"/api/v1/advisory/recommendations/{card['recommendation_id']}/decide",
        json={"decision": "REJECTED", "reason": "Not this week."},
    )

    assert client.get("/api/v1/state").json()["advisory"] is None
    assert client.get("/api/v1/advisory/latest").json() is None


def test_the_run_panel_shows_the_excluded_candidates_with_their_reasons(client):
    client.post("/api/v1/jobs/nightly", json={})
    card = client.get("/api/v1/advisory/latest").json()

    run = client.get(f"/api/v1/advisory/runs/{card['run_id']}").json()

    assert len(run["candidates"]) == 5
    excluded = [c for c in run["candidates"] if c["excluded"]]
    assert excluded
    assert all(c["exclusion_reason"] for c in excluded)
    assert len(run["validation"]) == 3
    assert run["model_enabled"] is True


def test_an_unknown_run_is_a_404(client):
    response = client.get("/api/v1/advisory/runs/adv_nothing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RUN_NOT_FOUND"
