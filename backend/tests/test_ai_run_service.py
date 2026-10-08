"""Stage 3 acceptance: every LLM call writes an ai_run row (Q-004).

Uses the DeterministicLLM adapter (default when no key is present) so
tests never touch the network. Asserts the service records a row per
call, the compliance endpoint reads it back, and the fx_narrator flow
persists a run when it invokes the model.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app import seed_data as s
from app.connector import ports, registry
from app.models import AiRun


@pytest.fixture(autouse=True)
def _reset_registry():
    registry.reset()
    yield
    registry.reset()


def test_ai_run_service_writes_one_row_per_call(session, monkeypatch):
    # Force the deterministic LLM so we don't need a key.
    monkeypatch.setenv("LLM_PROVIDER", "deterministic")
    registry.reset()

    from app.services import ai_run_service

    result = ai_run_service.chat(
        session=session,
        tenant_id=s.TENANT_ID,
        endpoint="test.smoke",
        system="You are a test.",
        user="Say something short.",
    )
    session.commit()

    assert result.ai_run_id is not None
    assert result.fallback_used is True  # deterministic returns fallback=True
    count = session.scalar(select(func.count()).select_from(AiRun))
    assert count == 1
    row = session.get(AiRun, result.ai_run_id)
    assert row is not None
    assert row.endpoint == "test.smoke"
    assert row.fallback_used == "true"
    assert row.model == "deterministic"
    # Full prompt is stored (Q-004 recommendation).
    assert row.prompt_text and "You are a test." in row.prompt_text


def test_record_decision_updates_outcome(session, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deterministic")
    registry.reset()
    from app.services import ai_run_service

    r = ai_run_service.chat(
        session=session,
        tenant_id=s.TENANT_ID,
        endpoint="test.record",
        system="s",
        user="u",
    )
    session.commit()

    ai_run_service.record_decision(session, r.ai_run_id, "accepted")
    session.commit()

    row = session.get(AiRun, r.ai_run_id)
    assert row.outcome == "accepted"


def test_compliance_ai_activity_endpoint_refused_to_analyst(client):
    # Whitfield (client) holds ANALYST; VIEW_AUDIT + MANAGE_USERS both
    # missing. The guard should refuse.
    r = client.get("/api/v1/compliance/ai-activity")
    assert r.status_code in (401, 403)


def test_compliance_ai_activity_endpoint_returns_rows_to_cfo(session, cfo):
    from datetime import datetime, timezone

    session.add(
        AiRun(
            id="run_cfo_1",
            tenant_id=s.TENANT_ID,
            occurred_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            endpoint="test.cfo",
            model="deterministic",
            prompt_hash="1" * 64,
            prompt_text="p",
            response_text="r",
            response_ms=17,
            tokens_prompt=1,
            tokens_completion=2,
            fallback_used="false",
            subject_type="deal",
            subject_id="deal_xyz",
            human_decision_id=None,
            outcome=None,
        )
    )
    session.commit()

    r = cfo.get("/api/v1/compliance/ai-activity")
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["total_matching"] >= 1
    assert any(row["endpoint"] == "test.cfo" for row in view["items"])
    assert "test.cfo" in view["endpoints_seen"]
    assert "deterministic" in view["models_seen"]


def test_fx_narrator_narrate_writes_an_ai_run(session, monkeypatch):
    """The fx_narrator migration path — proving one real caller is
    now wired through the recorder. Deterministic LLM returns a
    fallback response, and the deterministic briefing path is used;
    the ai_run row is still written."""
    monkeypatch.setenv("LLM_PROVIDER", "deterministic")
    registry.reset()

    from app.repo import policy as policy_repo
    from app.services.fx_narrator import narrate

    policy = policy_repo.current_policy(session, s.TENANT_ID)
    narrate(session, s.TENANT_ID, s.CLOCK_DATE, policy)
    session.commit()

    matches = session.scalars(
        select(AiRun).where(AiRun.endpoint == "fx.narrate")
    ).all()
    assert len(matches) >= 1
    assert matches[0].fallback_used == "true"  # no real model bound
