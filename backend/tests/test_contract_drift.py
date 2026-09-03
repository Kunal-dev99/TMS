"""Mock against real, shape for shape.

Document 5 section 11 makes this the API workstream's job: the mock and the
real API must return identical shapes for every endpoint, and this is what
stops the two drifting while the frontend builds against one of them.

Shapes, not figures. The mock picks between two prepared fixtures and the
engine does arithmetic, so the two agree on the seeded book and will not
agree on every input. A test that demanded equal values would be asserting
that the mock is a second rule engine, which is the one thing it must never
become.
"""

from app import seed_data as s
from app.schemas.models import CheckResult
from app.services.check_engine import CheckEngine
from mock import fixtures as fx

P = 100


def _shape(model) -> set[str]:
    return set(model.model_dump().keys())


def test_both_return_the_same_top_level_fields(engine_for):
    real = engine_for().run("cp_northern", "DEPOSIT", 10_000_000 * P, 6, 425).result
    mocked = fx.check_result("cp_northern", "DEPOSIT", 10_000_000 * P, 6)

    assert _shape(real) == _shape(mocked) == set(CheckResult.model_fields)


def test_both_return_six_checks_in_the_same_order(engine_for):
    real = engine_for().run("cp_northern", "DEPOSIT", 10_000_000 * P, 6, 425).result
    mocked = fx.check_result("cp_northern", "DEPOSIT", 10_000_000 * P, 6)

    assert [c.key for c in real.checks] == [c.key for c in mocked.checks]
    assert len(real.checks) == 6


def test_both_name_the_checks_identically(engine_for):
    """The panel renders the name the server sends. Two spellings of the same
    check is a visible defect the day the mock is retired."""
    real = engine_for().run("cp_meridian", "DEPOSIT", 1_000_000 * P, 6, 425).result
    mocked = fx.check_result("cp_meridian", "DEPOSIT", 1_000_000 * P, 6)

    assert {c.key: c.name for c in real.checks} == {c.key: c.name for c in mocked.checks}


def test_both_agree_on_the_seeded_book(engine_for):
    """On the figures the demonstration turns on, they do have to agree,
    because both are derived from the same seed through the same
    measurement module."""
    real = engine_for().run("cp_northern", "DEPOSIT", 10_000_000 * P, 6, 425).result
    mocked = fx.check_result("cp_northern", "DEPOSIT", 10_000_000 * P, 6)

    assert real.outcome == mocked.outcome == "FAIL"

    real_group = next(c for c in real.checks if c.key == "GROUP_LIMIT")
    mock_group = next(c for c in mocked.checks if c.key == "GROUP_LIMIT")

    assert not real_group.passed and not mock_group.passed
    assert real_group.resize_to_pence == mock_group.resize_to_pence
    assert "£28,119,836" in real_group.detail
    assert "£28,119,836" in mock_group.detail


def test_the_engine_and_the_mock_measure_a_forward_the_same_way(engine_for):
    real = engine_for().run("cp_harbour", "FX_FORWARD", 3_000_000 * P, 3, 11740).result
    mocked = fx.check_result("cp_harbour", "FX_FORWARD", 3_000_000 * P, 3)

    assert real.measured_pence == mocked.measured_pence == 300_000 * P
    assert real.measurement_basis == mocked.measurement_basis


def test_the_evaluate_step_needs_no_database(engine_for):
    """Guards the property the reproducibility test rests on.

    If `evaluate` ever reaches for a session, a historic run stops
    re-deriving and starts re-reading, and the difference is invisible until
    somebody changes a threshold.
    """
    import ast
    import inspect
    import textwrap

    # Parsed rather than grepped, so the prose in the docstring above
    # `evaluate` cannot pass or fail this test on the strength of a word.
    tree = ast.parse(textwrap.dedent(inspect.getsource(CheckEngine.evaluate)))
    function = tree.body[0]
    if ast.get_docstring(function):
        function.body = function.body[1:]
    body = ast.unparse(function)

    for forbidden in ("session", "_repo.", "select(", "self."):
        assert forbidden not in body, f"evaluate reaches for {forbidden}"

    inputs = engine_for().gather_inputs(
        "cp_northern", "DEPOSIT", 10_000_000 * P, 6, 425
    )
    assert len(CheckEngine.evaluate(inputs)) == 6


def test_the_inputs_carry_every_version_the_run_read(engine_for):
    """What makes the stored run evidence rather than a note."""
    inputs = engine_for().gather_inputs("cp_northern", "DEPOSIT", 1_000_000 * P, 6, 425)

    assert inputs["as_of_date"] == s.CLOCK_DATE
    assert inputs["policy"]["id"]
    assert inputs["limit"]["id"]
    assert inputs["band"]["rating"] == "A-"
    assert inputs["proposed_measure_basis"]
