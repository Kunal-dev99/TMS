import pytest
from app.services.planner_service import (
    Candidate,
    DeploymentPlan,
)
from app.services.planner_narrator import _fallback, narrate


def _sample_plan() -> DeploymentPlan:
    return DeploymentPlan(
        idle_cash_pence=8_000_000_00,
        portfolio_total_pence=50_000_000_00,
        concentration_cap_bp=5000,
        candidates=[
            Candidate(
                kind='BLENDED',
                label='Blended Plan',
                tagline='Balanced across approved buckets',
                weighted_rate_bp=393,
                expected_annual_interest_pence=314_760_00,
                allocations=[],
            ),
            Candidate(
                kind='HIGHER_YIELD',
                label='Higher Yield',
                tagline='Optimised for maximum safe return',
                weighted_rate_bp=397,
                expected_annual_interest_pence=317_160_00,
                allocations=[],
            ),
            Candidate(
                kind='TIGHTER_CONCENTRATION',
                label='Tighter Concentration',
                tagline='Limits single bank exposure to 35%',
                weighted_rate_bp=385,
                expected_annual_interest_pence=308_000_00,
                allocations=[],
            ),
        ],
    )


def test_fallback_point_wise_bullets():
    plan = _sample_plan()
    result = _fallback(plan)

    assert result['recommendation_kind'] == 'HIGHER_YIELD'
    reason = result['recommendation_reason']
    
    # Must contain the four structured bullet headers
    assert '• Cash to Deploy:' in reason
    assert '• Strategy Trade-Offs:' in reason
    assert '• Recommended Pick:' in reason
    assert '• Governance & Safety:' in reason

    # Must contain double newlines separating bullets
    lines = [line.strip() for line in reason.split(chr(10) + chr(10)) if line.strip()]
    assert len(lines) == 4

    # Check that each line begins with a bullet
    for line in lines:
        assert line.startswith('•')

    # Values must be accurately reflected
    assert '£8,000,000' in reason
    assert '3 pre-checked strategies' in reason
    assert '+£2,400/yr extra return' in reason
    assert '50.0%' in reason


def test_fallback_empty_plan():
    empty_plan = DeploymentPlan(
        idle_cash_pence=0,
        portfolio_total_pence=0,
        concentration_cap_bp=5000,
        candidates=[],
    )
    result = _fallback(empty_plan)
    assert result['recommendation_kind'] == ''
    assert result['recommendation_reason'] == ''
    assert result['labels'] == {}


def test_narrate_without_key_uses_point_wise_fallback():
    plan = _sample_plan()
    narrate(plan, None)

    assert plan.recommendation_kind == 'HIGHER_YIELD'
    assert '• Cash to Deploy:' in plan.recommendation_reason
    assert '• Governance & Safety:' in plan.recommendation_reason
