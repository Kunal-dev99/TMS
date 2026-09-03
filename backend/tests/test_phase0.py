"""Phase zero exit criteria, as tests.

Four of the five criteria are checkable here. The fifth, that the frontend
shell renders against the mock with no backend running, is checked by
starting it.

The three demonstration assertions of phase one are deliberately absent.
They belong to the CheckEngine, which phase zero does not build.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app import seed_data as s  # noqa: E402
from app.errors import CATALOGUE, ErrorCode  # noqa: E402
from mock import fixtures as fx  # noqa: E402
from mock.main import app  # noqa: E402

client = TestClient(app)


# --------------------------------------------------------------------------
# The contract
# --------------------------------------------------------------------------


def test_the_catalogue_holds_every_documented_code_and_the_identity_ones():
    """Thirty-eight from document 2, plus three the documents cannot list
    because they describe a system with no identity."""
    from app.errors import DOCUMENTED_CODES, IDENTITY_CODES

    assert len(ErrorCode) == DOCUMENTED_CODES + IDENTITY_CODES
    assert len(CATALOGUE) == len(ErrorCode)


def test_the_mock_answers_every_documented_endpoint_and_the_identity_ones():
    paths = {
        (sorted(r.methods - {"HEAD", "OPTIONS"})[0], r.path)
        for r in app.routes
        if hasattr(r, "methods") and r.path.startswith("/api/v1")
    }
    # Forty-four from document 2, plus the three sign in endpoints phase 1.5
    # added. The mock hands back a token and then ignores it: it is a fixture
    # source, not a security boundary.
    assert len(paths) == 44 + 3


# --------------------------------------------------------------------------
# The seeded book
# --------------------------------------------------------------------------


def test_the_book_opens_with_no_counterparty_in_breach():
    """The one thing that makes this true is the manual limit on Northern
    Treasury Services Ltd, which sits above its A- band ceiling."""
    for row in fx.book_rows():
        assert row.limit_pence is not None, f"{row.name} has no limit in force"
        assert row.used_pence <= row.limit_pence, f"{row.name} is over its entity limit"
        assert row.group_used_pence <= row.group_limit_pence, f"{row.name} is over its group limit"


def test_no_position_is_outside_its_own_term_limit_on_open():
    """The amount is only half of it.

    Amount and duration are two independent constraints, so a book where
    every position is inside its limit can still open in breach on the term.
    Nothing shows it until something re-tests the book, which is exactly when
    it is least welcome.
    """
    limits = {limit["counterparty_id"]: limit for limit in s.CP_LIMITS}
    for deal in s.DEALS:
        if deal["status"] != "ACTIVE":
            continue
        limit = limits[deal["counterparty_id"]]
        assert deal["tenor_months"] <= limit["max_tenor_months"], (
            f"{deal['id']} runs {deal['tenor_months']} months against a limit of "
            f"{limit['max_tenor_months']}"
        )


def test_no_position_is_outside_the_band_its_rating_allows():
    """A limit may be held tighter than the band. It may not be looser
    without somebody having signed for it, and the seed has exactly one of
    those, which is called out in its own test below."""
    bands = {rating: (lim, ten) for _id, rating, _o, lim, ten in s.RATING_BANDS}
    by_id = {cp["id"]: cp for cp in s.COUNTERPARTIES}
    for deal in s.DEALS:
        if deal["status"] != "ACTIVE":
            continue
        rating = by_id[deal["counterparty_id"]]["rating"]
        assert deal["tenor_months"] <= bands[rating][1], (
            f"{deal['id']} runs longer than the {rating} band allows"
        )


def test_no_group_breaches_the_concentration_cap_on_open():
    total = fx.portfolio_total_pence()
    cap = fx.POLICY["concentration_cap_bp"]
    for group_id, used in fx.used_by_group().items():
        share = round(used * 10_000 / total)
        assert share <= cap, f"{group_id} holds {share} basis points of the portfolio"


def test_the_northern_position_measures_the_figure_the_run_sheet_quotes():
    """18,000,000 at 4.05 per cent for 60 days, rounded to the pound."""
    nts = next(d for d in fx.deal_summaries() if d.counterparty_id == "cp_nts")
    assert round(nts.measured_pence / 100) == round(s.EXPECTED["nts_measured_pence"] / 100)


def test_a_forward_is_never_read_as_its_notional():
    forward = next(d for d in fx.deal_summaries() if d.instrument == "FX_FORWARD")
    assert forward.measured_pence < forward.principal_pence
    assert "add on" in forward.measurement_basis


# --------------------------------------------------------------------------
# The screen 2 arithmetic
# --------------------------------------------------------------------------


def test_ten_million_with_northern_bank_fails_the_group_check_and_nothing_else():
    result = fx.check_result("cp_northern", "DEPOSIT", 10_000_000 * 100, 6)
    failed = [c for c in result.checks if not c.passed]
    assert len(failed) == 1
    assert failed[0].key == "GROUP_LIMIT"
    assert "28,119,836" in failed[0].detail
    assert "25,000,000" in failed[0].detail


def test_the_failed_group_check_offers_the_amount_that_would_fit():
    result = fx.check_result("cp_northern", "DEPOSIT", 10_000_000 * 100, 6)
    failed = next(c for c in result.checks if not c.passed)
    assert round(failed.resize_to_pence / 100) == round(s.EXPECTED["resize_to_pence"] / 100)


def test_the_resized_amount_passes_all_six():
    resize_to = fx.check_result("cp_northern", "DEPOSIT", 10_000_000 * 100, 6)
    amount = next(c for c in resize_to.checks if not c.passed).resize_to_pence
    result = fx.check_result("cp_northern", "DEPOSIT", amount, 6)
    assert result.outcome == "PASS"
    assert result.failed_count == 0


def test_the_verdict_names_who_has_to_sign_before_the_user_commits():
    result = fx.check_result("cp_meridian", "DEPOSIT", 8_000_000 * 100, 6)
    assert result.required_approver == "HEAD_OF_TREASURY"
    assert "sign" in result.verdict


# --------------------------------------------------------------------------
# Every endpoint answers
# --------------------------------------------------------------------------

BODIES = {
    "check": {
        "counterparty_id": "cp_meridian",
        "instrument": "DEPOSIT",
        "principal_pence": 500_000_000,
        "tenor_months": 6,
        "rate_bp": 425,
    },
}


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/v1/state", None),
        ("GET", "/api/v1/policy", None),
        ("GET", "/api/v1/investment-policy", None),
        (
            "POST",
            "/api/v1/investment-policy",
            {
                "liquidity_buffer_pence": 500_000_000,
                "buffer_horizon_days": 30,
                "priority_order": "SECURITY,LIQUIDITY,YIELD",
                "model_enabled": True,
                "approved_by": "Group CFO",
                "ladder_targets": [],
                "currency_cover_targets": [],
            },
        ),
        ("POST", "/api/v1/deals/check", BODIES["check"]),
        ("POST", "/api/v1/deals", BODIES["check"]),
        ("GET", "/api/v1/deals", None),
        ("GET", "/api/v1/deals/dl_nts_001", None),
        ("POST", "/api/v1/deals/dl_nts_001/approve", {"role": "HEAD_OF_TREASURY"}),
        ("POST", "/api/v1/deals/dl_nts_001/instruct", {}),
        (
            "POST",
            "/api/v1/deals/dl_nts_001/amendments",
            {
                "type": "CORRECTION",
                "effective_date": s.CLOCK_DATE,
                "reason": "Rate corrected against the confirmation.",
                "raised_by": "A. Whitfield",
            },
        ),
        ("POST", "/api/v1/amendments/amd_001/apply", None),
        ("POST", "/api/v1/deals/dl_nts_001/settle", {"statement_line_id": "bsl_001", "settled_by": "A. Whitfield"}),
        (
            "POST",
            "/api/v1/confirmations",
            {
                "message_type": "MT320",
                "reference": "NTS-88213",
                "instrument": "DEPOSIT",
                "principal_pence": 1_800_000_000,
                "rate_bp": 405,
                "value_date": s.CLOCK_DATE,
            },
        ),
        ("GET", "/api/v1/confirmations", None),
        ("POST", "/api/v1/confirmations/cnf_001/match", {"deal_id": "dl_nts_001"}),
        ("GET", "/api/v1/deals/dl_nts_001/accruals", None),
        ("GET", "/api/v1/journals", None),
        ("POST", "/api/v1/journals/post", {"period": "2026-08"}),
        ("POST", "/api/v1/counterparties", {"name": "New Bank plc", "created_by": "A. Whitfield"}),
        (
            "POST",
            "/api/v1/counterparties/cp_meridian/verify",
            {
                "legal_entity_identifier": "213800NEW00000000001",
                "group_parent_name": "New Holdings plc",
                "rating": "A+",
                "country": "GB",
                "instruments": ["DEPOSIT"],
                "verified_by": "A. Whitfield",
            },
        ),
        (
            "POST",
            "/api/v1/counterparties/cp_meridian/limit",
            {"amount_pence": 500_000_000, "max_tenor_months": 12, "approved_by": "Head of Treasury"},
        ),
        ("POST", "/api/v1/counterparties/cp_meridian/activate", {"activated_by": "Head of Treasury"}),
        ("GET", "/api/v1/counterparties/cp_meridian/limits", None),
        (
            "POST",
            "/api/v1/counterparties/cp_northern/rating",
            {"new_rating": "BBB+", "new_status": "WATCH", "recorded_by": "A. Whitfield"},
        ),
        ("GET", "/api/v1/queue", None),
        ("POST", "/api/v1/queue/exc_001/resolve", {"resolution": "RESIZED", "resolved_by": "A. Whitfield"}),
        ("GET", "/api/v1/breaches", None),
        (
            "POST",
            "/api/v1/breaches/brc_001/respond",
            {"response": "HOLD_TO_MATURITY", "responded_by": "M. Doran"},
        ),
        ("GET", "/api/v1/advisory/latest", None),
        ("GET", "/api/v1/advisory/runs/adv_run_001", None),
        ("POST", "/api/v1/advisory/runs", {}),
        ("POST", "/api/v1/advisory/recommendations/rec_001/decide", {"decision": "ACCEPTED"}),
        ("GET", "/api/v1/exposure/counterparty", None),
        ("GET", "/api/v1/exposure/currency", None),
        (
            "POST",
            "/api/v1/currency-exposures",
            {
                "currency": "EUR",
                "amount_minor": 400_000_000,
                "direction": "PAYABLE",
                "expected_date": s.CLOCK_DATE,
                "source": "PURCHASE_ORDER",
            },
        ),
        (
            "POST",
            "/api/v1/currency-exposures/cxp_001/hedges",
            {"deal_id": "dl_har_001", "covered_amount_minor": 300_000_000},
        ),
        ("POST", "/api/v1/hedge-links/hl_001/unlink", {"reason": "ROLLED"}),
        ("POST", "/api/v1/jobs/nightly", {}),
        (
            "POST",
            "/api/v1/statements",
            {"account_name": "Group operating account", "amount_pence": 100, "value_date": s.CLOCK_DATE},
        ),
        ("GET", "/api/v1/instructions", None),
        ("POST", "/api/v1/admin/clock", {"today_date": s.CLOCK_DATE}),
        ("POST", "/api/v1/admin/enforcement", {"enforcement": "WARN_WITH_OVERRIDE"}),
        ("POST", "/api/v1/admin/reset", None),
    ],
)
def test_every_endpoint_answers(method, path, body):
    response = client.request(method, path, json=body)
    assert response.status_code < 500, f"{method} {path} returned {response.status_code}: {response.text[:200]}"


# --------------------------------------------------------------------------
# Migrations
# --------------------------------------------------------------------------


def test_migrations_build_every_phase_one_table_from_empty(tmp_path):
    db = tmp_path / "scratch.db"
    env = {"TREASURY_DATABASE_URL": f"sqlite:///{db}"}
    import os

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    import sqlite3

    names = {
        row[0]
        for row in sqlite3.connect(db).execute(
            "select name from sqlite_master where type='table'"
        )
    }
    from app.models import PHASE_ONE_TABLES

    for model in PHASE_ONE_TABLES:
        assert model.__tablename__ in names
