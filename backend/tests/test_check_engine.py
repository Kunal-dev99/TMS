"""The phase one test gate.

Document 5 section 5.1 puts three assertions at day nine, before the surface
exists: a group limit failure that passes the entity limit, a tenor failure
at BBB+, and a downgrade that turns a previously compliant deposit amber.
If those three pass, the demonstration works. If they do not, no amount of
frontend polish saves it.

Document 5 names Coutts, Goldman and NatWest. Document 3 uses Meridian and
Northern, and documents 1 to 4 win, so the shapes here are the same and the
names are document 3's.

Everything below runs headless. No HTTP, no browser.
"""

from datetime import datetime, timezone

import pytest

from app import seed_data as s
from app.repo import counterparties as cp_repo
from app.services.check_engine import CheckEngine

P = 100
NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def outcome(result, key):
    """One check out of the six, by key."""
    return next(c for c in result.checks if c.key == key)


# ==========================================================================
# Assertion 1. The group limit fails and the entity limit passes.
# ==========================================================================


def test_ten_million_with_northern_bank_fails_the_group_and_passes_the_entity(
    engine_for,
):
    """Screen 2 of document 3.

    Northern Bank plc holds nothing, so its own limit has room to spare. The
    group check fails, because Northern Treasury Services Ltd is the same
    credit and already holds 18,119,836. Nothing else on the screen connects
    those two names.
    """
    evaluation = engine_for().run("cp_northern", "DEPOSIT", 10_000_000 * P, 6, 425)
    result = evaluation.result

    entity = outcome(result, "ENTITY_LIMIT")
    group = outcome(result, "GROUP_LIMIT")

    assert entity.passed, entity.detail
    assert not group.passed, group.detail

    assert result.outcome == "FAIL"
    assert result.failed_count == 1, [c.key for c in result.checks if not c.passed]


def test_the_group_failure_states_the_arithmetic_rather_than_the_verdict(engine_for):
    group = outcome(
        engine_for().run("cp_northern", "DEPOSIT", 10_000_000 * P, 6, 425).result,
        "GROUP_LIMIT",
    )
    assert "£28,119,836" in group.detail
    assert "£25,000,000" in group.detail
    assert "Northern Group" in group.detail


def test_the_group_failure_names_the_other_holding_individually(engine_for):
    """Not a total the reader cannot decompose."""
    group = outcome(
        engine_for().run("cp_northern", "DEPOSIT", 10_000_000 * P, 6, 425).result,
        "GROUP_LIMIT",
    )
    assert any(
        "Northern Treasury Services Ltd" in line and "£18,119,836" in line
        for line in group.workings
    ), group.workings


def test_the_refusal_offers_the_amount_that_would_fit(engine_for):
    group = outcome(
        engine_for().run("cp_northern", "DEPOSIT", 10_000_000 * P, 6, 425).result,
        "GROUP_LIMIT",
    )
    assert group.resize_to_pence is not None
    assert round(group.resize_to_pence / 100) == 6_880_164


def test_the_offered_amount_passes_all_six(engine_for):
    """Accepting the route forward must not simply move the failure to the
    next row."""
    engine = engine_for()
    failed = outcome(
        engine.run("cp_northern", "DEPOSIT", 10_000_000 * P, 6, 425).result,
        "GROUP_LIMIT",
    )
    resized = engine.run(
        "cp_northern", "DEPOSIT", failed.resize_to_pence, 6, 425
    ).result
    assert resized.outcome == "PASS", [
        c.detail for c in resized.checks if not c.passed
    ]


def test_a_term_failure_carries_no_resize(engine_for):
    """Amount and duration are two independent constraints. No smaller
    amount clears a term that is too long."""
    tenor = outcome(
        engine_for().run("cp_harbour", "DEPOSIT", 1_000_000 * P, 18, 452).result,
        "TENOR_BAND",
    )
    assert not tenor.passed
    assert tenor.resize_to_pence is None


# ==========================================================================
# Assertion 2. An eighteen month deal fails the tenor band at BBB+.
# ==========================================================================


def test_an_eighteen_month_deal_fails_the_tenor_band_at_bbb_plus(engine_for):
    """Harbour and Vale Bank is rated BBB+, where three months is the
    ceiling. The amount is small enough that nothing else objects."""
    result = engine_for().run("cp_harbour", "DEPOSIT", 1_000_000 * P, 18, 452).result

    tenor = outcome(result, "TENOR_BAND")
    assert not tenor.passed
    assert "18 months" in tenor.detail
    assert "maximum of 3" in tenor.detail

    assert [c.key for c in result.checks if not c.passed] == ["TENOR_BAND"]


def test_the_same_deal_at_three_months_passes(engine_for):
    result = engine_for().run("cp_harbour", "DEPOSIT", 1_000_000 * P, 3, 452).result
    assert result.outcome == "PASS", [c.detail for c in result.checks if not c.passed]


# ==========================================================================
# Assertion 3. A downgrade turns a previously compliant deposit amber.
# ==========================================================================


def _downgrade_northern_bank_to_bbb_plus(session):
    """What RetestService will do at step 6, done by hand here.

    The limit is superseded rather than edited, and the new one comes from
    the BBB+ band: 8,000,000 and three months, down from 15,000,000 and six.
    Screen 4 of document 3.
    """
    counterparty = cp_repo.get(session, "cp_northern")
    counterparty.rating = "BBB+"
    counterparty.rating_status = "WATCH"

    old = cp_repo.current_limit(session, "cp_northern")
    old.superseded_at = NOW

    from app.models import CpLimit
    from app.repo import policy as policy_repo

    band = policy_repo.band_for_rating(session, s.TENANT_ID, "BBB+")
    session.add(
        CpLimit(
            id="lim_northern_2",
            tenant_id=s.TENANT_ID,
            counterparty_id="cp_northern",
            amount_pence=band.max_limit_pence,
            max_tenor_months=band.max_tenor_months,
            source="BAND",
            effective_from=s.CLOCK_DATE,
            superseded_at=None,
            reason="Rating action to BBB+. Limit reset to the band.",
            approved_by="Head of Treasury",
            approved_at=NOW,
        )
    )
    session.flush()
    return band


def test_a_deal_compliant_when_booked_is_not_compliant_after_a_downgrade(
    session, engine_for
):
    """The point of screen 4.

    A six month deposit of 6,880,164 is booked and passes. Northern Bank plc
    then moves to BBB+ and the limit drops to 8,000,000 and three months. The
    amount is still inside the new limit. It is the term that broke.
    """
    booked_principal = 6_880_164 * P

    before = engine_for().run("cp_northern", "DEPOSIT", booked_principal, 6, 425).result
    assert before.outcome == "PASS", [c.detail for c in before.checks if not c.passed]

    _downgrade_northern_bank_to_bbb_plus(session)

    after = engine_for().run("cp_northern", "DEPOSIT", booked_principal, 6, 425).result

    entity = outcome(after, "ENTITY_LIMIT")
    tenor = outcome(after, "TENOR_BAND")

    assert entity.passed, (
        "The amount is inside the new limit. Saying the deal is too big is the "
        f"instinct this screen exists to correct. {entity.detail}"
    )
    assert not tenor.passed, tenor.detail
    assert "6 months" in tenor.detail
    assert "maximum of 3" in tenor.detail


def test_the_downgrade_moves_the_limit_by_superseding_it_rather_than_editing(session):
    _downgrade_northern_bank_to_bbb_plus(session)

    history = cp_repo.limit_history(session, "cp_northern")
    assert len(history) == 2
    current = cp_repo.current_limit(session, "cp_northern")
    assert current.amount_pence == 8_000_000 * P
    assert current.max_tenor_months == 3

    superseded = [limit for limit in history if limit.superseded_at is not None]
    assert len(superseded) == 1
    assert superseded[0].amount_pence == 15_000_000 * P, (
        "The old limit must survive, so a deal booked under it can still be "
        "re-derived against the version that was in force."
    )


# ==========================================================================
# Failing closed
# ==========================================================================


def test_the_concentration_check_fails_when_no_balance_has_been_fed(
    session, engine_for
):
    """Document 4's worked example.

    Losing the Oracle balance feed leaves the concentration check with no
    denominator. It fails rather than passes, which blocks every deal. That
    is correct for a control and disruptive in practice, and it is the single
    most disruptive failure in the system by design.
    """
    from app.models import OracleBalance

    session.query(OracleBalance).delete()
    session.flush()

    result = engine_for().run("cp_meridian", "DEPOSIT", 1_000_000 * P, 6, 425).result

    concentration = outcome(result, "CONCENTRATION")
    assert not concentration.passed
    assert "fails rather than passes" in concentration.detail

    assert [c.key for c in result.checks if not c.passed] == ["CONCENTRATION"]


def test_a_counterparty_with_no_limit_in_force_fails_two_checks_closed(
    session, engine_for
):
    """No limit in force is not a limit of nothing, and neither of them is a
    reason to let a deal through."""
    limit = cp_repo.current_limit(session, "cp_meridian")
    limit.superseded_at = NOW
    session.flush()

    result = engine_for().run("cp_meridian", "DEPOSIT", 1_000_000 * P, 6, 425).result

    assert not outcome(result, "ENTITY_LIMIT").passed
    assert not outcome(result, "TENOR_BAND").passed
    assert "no limit in force" in outcome(result, "ENTITY_LIMIT").detail


def test_a_counterparty_that_is_not_active_fails_the_first_check(session, engine_for):
    cp_repo.get(session, "cp_meridian").status = "APPROVED"
    session.flush()

    result = engine_for().run("cp_meridian", "DEPOSIT", 1_000_000 * P, 6, 425).result
    assert not outcome(result, "COUNTERPARTY_ACTIVE").passed


def test_an_instrument_the_name_is_not_approved_for_fails(engine_for):
    """Northern Treasury Services Ltd is approved for deposits only."""
    result = engine_for().run("cp_nts", "MMF", 1_000_000 * P, 6, 425).result
    permitted = outcome(result, "INSTRUMENT_PERMITTED")
    assert not permitted.passed
    assert "deposit" in " ".join(permitted.workings)


# ==========================================================================
# Reproducibility
# ==========================================================================


def test_a_run_re_derives_the_same_verdict_from_its_stored_inputs(engine_for):
    """The test worth writing early and never deleting.

    Document 5 section 11. Reproducibility is the reason the policy version
    was made versioned in revision B, and it is the sort of property that
    quietly stops holding. Nothing in `evaluate` touches the database, so
    this is a real re-derivation rather than a second read.
    """
    evaluation = engine_for().run("cp_northern", "DEPOSIT", 10_000_000 * P, 6, 425)

    re_derived = CheckEngine.evaluate(evaluation.inputs)

    assert [(c.key, c.passed, c.detail) for c in re_derived] == [
        (c.key, c.passed, c.detail) for c in evaluation.result.checks
    ]


def test_a_stored_run_is_unaffected_by_the_world_moving_on(session, engine_for):
    """The stored inputs are the whole of the evidence.

    A limit that is superseded after the run, or a rating that moves, must
    not change what a historic run says. Otherwise every audit answer is the
    answer as of today, dressed as the answer as of then.
    """
    evaluation = engine_for().run("cp_northern", "DEPOSIT", 10_000_000 * P, 6, 425)
    before = [(c.key, c.passed) for c in evaluation.result.checks]

    _downgrade_northern_bank_to_bbb_plus(session)

    assert [(c.key, c.passed) for c in CheckEngine.evaluate(evaluation.inputs)] == before


def test_every_run_records_the_versions_it_read(engine_for):
    evaluation = engine_for().run("cp_northern", "DEPOSIT", 1_000_000 * P, 6, 425)

    assert evaluation.result.policy_version_id == "pol_v1"
    assert evaluation.result.limit_id == "lim_northern_1"
    assert evaluation.result.as_of_date == s.CLOCK_DATE
    assert evaluation.inputs["policy"]["id"] == "pol_v1"
    assert evaluation.inputs["limit"]["id"] == "lim_northern_1"


# ==========================================================================
# The verdict and the approver
# ==========================================================================


@pytest.mark.parametrize(
    "principal_pence,expected",
    [
        (500_000 * P, "ANALYST"),
        (1_000_000 * P, "ANALYST"),
        (1_000_001 * P, "HEAD_OF_TREASURY"),
        (8_000_000 * P, "HEAD_OF_TREASURY"),
        (10_000_000 * P, "HEAD_OF_TREASURY"),
        (10_000_001 * P, "CFO"),
    ],
)
def test_the_approver_comes_from_the_thresholds_in_the_policy_version(
    engine_for, principal_pence, expected
):
    from app.services.approval_router import ApprovalRouter

    engine = engine_for()
    assert ApprovalRouter(engine.policy).required_approver(principal_pence) == expected


def test_the_verdict_names_who_has_to_sign_before_the_deal_is_committed(engine_for):
    """The run sheet at 1:05. Routed to the Head of Treasury by threshold."""
    result = engine_for().run("cp_meridian", "DEPOSIT", 8_000_000 * P, 6, 428).result

    assert result.outcome == "PASS", [c.detail for c in result.checks if not c.passed]
    assert result.required_approver == "HEAD_OF_TREASURY"
    assert "The Head of Treasury has to sign." in result.verdict


def test_a_failed_verdict_says_what_the_policy_allows(engine_for):
    result = engine_for().run("cp_northern", "DEPOSIT", 10_000_000 * P, 6, 425).result
    assert "1 of six checks failed" in result.verdict
    assert "hard block" in result.verdict
    assert result.required_approver is None


def test_the_verdict_states_the_measurement_basis(engine_for):
    """A forward is never read as its notional."""
    result = engine_for().run("cp_harbour", "FX_FORWARD", 3_000_000 * P, 3, 11740).result

    assert result.measured_pence == 300_000 * P
    assert "add on to notional" in result.measurement_basis
    assert "£300,000" in result.verdict


# ==========================================================================
# Measurement, which everything above rests on
# ==========================================================================


def test_a_forward_resize_is_offered_as_a_principal_not_as_a_headroom(
    session, engine_for
):
    """Headroom is expressed in measured exposure. The ticket takes a
    principal, and for a forward the two are not the same number. Offering
    the headroom would offer a tenth of what fits."""
    limit = cp_repo.current_limit(session, "cp_harbour")
    limit.amount_pence = 500_000 * P  # leaves 200,000 of measured headroom
    session.flush()

    result = engine_for().run("cp_harbour", "FX_FORWARD", 9_000_000 * P, 3, 11740).result
    entity = outcome(result, "ENTITY_LIMIT")

    assert not entity.passed
    # 200,000 of headroom at a 10 per cent add on is 2,000,000 of notional.
    assert entity.resize_to_pence == 2_000_000 * P


def test_the_seeded_book_measures_what_the_run_sheet_quotes(engine_for):
    engine = engine_for()
    by_counterparty = engine.exposure.exposure_by_counterparty()

    assert round(by_counterparty["cp_nts"] / 100) == 18_119_836
    assert by_counterparty["cp_northern"] == 0
    assert round(engine.exposure.portfolio_total_pence() / 100) == 50_633_699
