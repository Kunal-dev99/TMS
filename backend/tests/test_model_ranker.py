"""Stage 4, with a real model behind it.

None of these call the network. The guardrail is not that the model behaves;
it is that nothing it returns is trusted, so what is worth testing is the
handling of every way it can misbehave.

Document 4 lists four failures the design makes structurally impossible. The
first three are tested here by making a ranker produce exactly that failure
and asserting it never reaches the recommendation. The fourth, a confident
wrong answer, is `test_advisory.py`.
"""

import json

import pytest

from app.services.ranker import (
    GroqRanker,
    ModelRanker,
    WeightedScoreRanker,
    ranker_for,
)


class FakeCandidate:
    def __init__(self, id, score_bp=100, rate=432, tenor=6, amount=800_000_000):
        self.id = id
        self.counterparty_id = "cp_meridian"
        self.score_bp = score_bp
        self.indicative_rate_bp = rate
        self.tenor_months = tenor
        self.amount_pence = amount


CONTEXT = {
    "names": {"cp_meridian": "Meridian Bank plc"},
    "ratings": {"cp_meridian": "A+"},
    "gap_type": "CASH_SURPLUS",
    "priority_order": "SECURITY,LIQUIDITY,YIELD",
}


# ==========================================================================
# Which ranker runs
# ==========================================================================


def test_the_policy_switch_wins_over_the_key(monkeypatch):
    """model_enabled is a policy field a customer owns. A key in the
    environment must not turn the model back on behind their back."""
    monkeypatch.setenv("TREASURY_MODEL_API_KEY", "not-a-real-key")
    assert isinstance(ranker_for(False), WeightedScoreRanker)


def test_the_stub_runs_when_no_key_is_configured(monkeypatch):
    """The prototype works with nothing set up, and the interface is
    identical either way."""
    monkeypatch.delenv("TREASURY_MODEL_API_KEY", raising=False)
    assert isinstance(ranker_for(True), ModelRanker)


def test_the_real_model_runs_when_a_key_is_configured(monkeypatch):
    monkeypatch.setenv("TREASURY_MODEL_API_KEY", "not-a-real-key")
    ranker = ranker_for(True)
    assert isinstance(ranker, GroqRanker)
    assert ranker.name.startswith("groq/")


def test_the_model_name_is_configurable(monkeypatch):
    monkeypatch.setenv("TREASURY_MODEL_API_KEY", "not-a-real-key")
    monkeypatch.setenv("TREASURY_MODEL_NAME", "openai/gpt-oss-20b")
    assert ranker_for(True).name == "groq/openai/gpt-oss-20b"


def test_an_empty_key_counts_as_no_key(monkeypatch):
    """A variable set to the empty string is how a shell says nothing, and
    it must not be read as a key."""
    monkeypatch.setenv("TREASURY_MODEL_API_KEY", "   ")
    assert not GroqRanker.configured()


# ==========================================================================
# What the model is given
# ==========================================================================


def test_the_brief_contains_only_the_candidates_offered(monkeypatch):
    """No counterparty it could pick that is not listed, and no figure it
    needs that is not given."""
    monkeypatch.setenv("TREASURY_MODEL_API_KEY", "not-a-real-key")
    brief = GroqRanker()._brief([FakeCandidate("cnd_one")], CONTEXT)

    assert "cnd_one" in brief
    assert "Meridian Bank plc" in brief
    assert "4.32" in brief
    assert "SECURITY,LIQUIDITY,YIELD" in brief


def test_the_system_prompt_forbids_inventing_a_figure(monkeypatch):
    """The prompt says so. The prompt is not what enforces it, and the
    docstring on GroqRanker says which stage does."""
    monkeypatch.setenv("TREASURY_MODEL_API_KEY", "not-a-real-key")
    prompt = GroqRanker.SYSTEM_PROMPT.lower()
    assert "never invent" in prompt
    assert "never state a number" in prompt
    assert "json" in prompt


# ==========================================================================
# What happens when it misbehaves
# ==========================================================================


def _ranker_answering(monkeypatch, payload):
    """A GroqRanker whose client returns `payload`, without a network call."""
    monkeypatch.setenv("TREASURY_MODEL_API_KEY", "not-a-real-key")
    ranker = GroqRanker()

    class Message:
        content = json.dumps(payload)

    class Choice:
        message = Message()

    class Completion:
        choices = [Choice()]

    class Completions:
        def create(self, **kwargs):
            return Completion()

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    monkeypatch.setattr(
        "groq.Groq", lambda *args, **kwargs: Client(), raising=False
    )
    return ranker


def test_a_good_answer_is_returned_as_a_model_pick(monkeypatch):
    ranker = _ranker_answering(
        monkeypatch,
        {"candidate_id": "cnd_one", "rationale": "The best of the three."},
    )
    pick = ranker.rank([FakeCandidate("cnd_one")], CONTEXT)

    assert pick.candidate_id == "cnd_one"
    assert pick.source == "MODEL"
    assert pick.rationale == "The best of the three."


def test_an_invented_candidate_is_refused_at_the_boundary(monkeypatch):
    """Caught here so it never reaches the recommendation, and caught again
    at stage 5, which is the one that counts."""
    ranker = _ranker_answering(
        monkeypatch, {"candidate_id": "cnd_invented", "rationale": "Trust me."}
    )
    with pytest.raises(ValueError, match="not a candidate"):
        ranker.rank([FakeCandidate("cnd_one")], CONTEXT)


def test_an_unreadable_answer_raises_rather_than_guessing(monkeypatch):
    ranker = _ranker_answering(monkeypatch, {"nothing": "useful"})
    with pytest.raises(Exception):
        ranker.rank([FakeCandidate("cnd_one")], CONTEXT)


def test_an_answer_with_no_prose_is_still_a_valid_pick(monkeypatch):
    """The identifier is the decision. The prose is the explanation, and a
    missing explanation is not a missing recommendation."""
    ranker = _ranker_answering(monkeypatch, {"candidate_id": "cnd_one"})
    pick = ranker.rank([FakeCandidate("cnd_one")], CONTEXT)

    assert pick.candidate_id == "cnd_one"
    assert pick.rationale is None


# ==========================================================================
# An outage is not the same as being switched off
# ==========================================================================


def test_an_unreachable_model_is_recorded_as_a_rejection_not_as_rule_only(
    session, monkeypatch
):
    """A model that has been failing for a week looks exactly like one that
    is switched off unless the run says which happened."""
    from app import seed_data as s
    from app.repo import policy as policy_repo
    from app.services import ranker as ranker_module
    from app.services.advisory_service import AdvisoryService

    class Unreachable:
        name = "unreachable"

        def rank(self, candidates, context):
            raise RuntimeError("The model endpoint timed out")

    monkeypatch.setattr(ranker_module, "ModelRanker", Unreachable)

    policy = policy_repo.current_policy(session, s.TENANT_ID)
    outcome = AdvisoryService(session, s.TENANT_ID, s.CLOCK_DATE, policy).run(
        force=True
    )
    session.commit()

    assert outcome.run.outcome == "MODEL_REJECTED_FALLBACK"
    assert outcome.recommendation.source == "RULE_FALLBACK"


def test_switching_the_model_off_is_recorded_as_rule_only(session):
    from app import seed_data as s
    from app.models import InvestmentPolicy
    from app.repo import policy as policy_repo
    from app.services.advisory_service import AdvisoryService

    for investment in session.query(InvestmentPolicy).all():
        investment.model_enabled = 0
    session.flush()

    policy = policy_repo.current_policy(session, s.TENANT_ID)
    outcome = AdvisoryService(session, s.TENANT_ID, s.CLOCK_DATE, policy).run(
        force=True
    )
    session.commit()

    assert outcome.run.outcome == "RULE_ONLY"
    assert outcome.run.model_name is None
