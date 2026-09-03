"""Phase 2, accounting.

Two things matter here and neither is obvious.

The daily figures sum to the measured accrual. Each day is written as the
difference between the interest accrued to that day and to the day before,
so the cumulative on any row equals what ExposureCalculator measures on the
same date. If those two ever drift, the book and the ledger disagree about
the same deal and nothing on screen says which is right.

Running the job twice for one date writes once. Document 5 makes that an
exit criterion, because a nightly job that double counts is worse than one
that does not run.
"""

from app import seed_data as s
from app.measurement import accrued_interest_pence
from app.repo import policy as policy_repo
from app.services.accrual_service import AccrualService
from app.services.exposure_calculator import ExposureCalculator
from app.services.journal_service import ACCOUNT_MAP, JournalService
from app.services.nightly_job import NightlyJob

P = 100


def _job(session):
    policy = policy_repo.current_policy(session, s.TENANT_ID)
    return NightlyJob(session, s.TENANT_ID, s.CLOCK_DATE, policy)


# ==========================================================================
# Exit criterion. Twice for one date writes accruals once.
# ==========================================================================


def test_the_nightly_job_run_twice_for_one_date_writes_accruals_once(session):
    from app.models import Accrual

    first = _job(session).run()
    session.commit()
    after_first = session.query(Accrual).count()

    second = _job(session).run()
    session.commit()
    after_second = session.query(Accrual).count()

    assert first.accrual_rows_written > 0
    assert second.accrual_rows_written == 0
    assert second.accrual_rows_already_present == first.accrual_rows_written
    assert after_second == after_first


def test_the_job_builds_a_journal_once_per_accrual(session):
    from app.models import Accrual, Journal

    _job(session).run()
    session.commit()
    _job(session).run()
    session.commit()

    accruals = session.query(Accrual).count()
    journals = session.query(Journal).count()
    assert journals == accruals


# ==========================================================================
# The accrual agrees with the measure
# ==========================================================================


def test_the_cumulative_equals_what_exposure_measures_on_the_same_date(session):
    """The property everything else rests on.

    If these drift, the book and the ledger disagree about the same deal and
    nothing on screen says which is right.
    """
    _job(session).run()
    session.commit()

    policy = policy_repo.current_policy(session, s.TENANT_ID)
    calculator = ExposureCalculator(session, s.TENANT_ID, s.CLOCK_DATE, policy)
    service = AccrualService(session, s.TENANT_ID, s.CLOCK_DATE)

    from app.repo import deals as deal_repo

    for deal in deal_repo.live_for_tenant(session, s.TENANT_ID):
        if deal.instrument == "FX_FORWARD":
            continue
        _today, cumulative = service.summary_for_deal(deal.id)
        measured = calculator.measure(deal).amount_pence
        assert measured == deal.principal_pence + cumulative, (
            f"{deal.id} measures {measured} but has accrued {cumulative}"
        )


def test_the_seeded_northern_position_accrues_to_the_run_sheet_figure(session):
    _job(session).run()
    session.commit()

    _today, cumulative = AccrualService(
        session, s.TENANT_ID, s.CLOCK_DATE
    ).summary_for_deal("dl_nts_001")

    assert round((18_000_000 * P + cumulative) / 100) == 18_119_836


def test_each_day_carries_the_rate_that_applied_on_it(session):
    _job(session).run()
    session.commit()

    rows = AccrualService(session, s.TENANT_ID, s.CLOCK_DATE).for_deal("dl_nts_001")
    assert rows
    assert all(row.rate_bp == 405 for row in rows)
    assert all(row.day_count == 1 for row in rows)


def test_the_daily_figures_sum_to_the_cumulative_on_the_last_row(session):
    _job(session).run()
    session.commit()

    rows = AccrualService(session, s.TENANT_ID, s.CLOCK_DATE).for_deal("dl_cal_001")
    assert sum(row.amount_pence for row in rows) == rows[-1].cumulative_pence


def test_a_forward_does_not_accrue_interest(session):
    """A forward is revalued rather than accrued, and revaluation is a
    different journal type that phase two does not build."""
    _job(session).run()
    session.commit()

    assert AccrualService(session, s.TENANT_ID, s.CLOCK_DATE).for_deal("dl_har_001") == []


def test_catching_up_writes_every_missed_day(session):
    """A deal booked a week ago on a system nobody ran the job on gets seven
    rows, not one."""
    _job(session).run()
    session.commit()

    rows = AccrualService(session, s.TENANT_ID, s.CLOCK_DATE).for_deal("dl_nts_001")
    assert len(rows) == 60, "Sixty days between the value date and the clock."


# ==========================================================================
# Journals
# ==========================================================================


def test_a_journal_carries_the_account_the_instrument_maps_to(session):
    _job(session).run()
    session.commit()

    service = JournalService(session, s.TENANT_ID, s.CLOCK_DATE)
    journal = service.list_journals(deal_id="dl_nts_001")[0]

    debit, credit = ACCOUNT_MAP["DEPOSIT"]
    assert journal.debit_account == debit
    assert journal.credit_account == credit
    assert journal.type == "ACCRUAL"
    assert journal.period == journal.posted_at is None or journal.status == "BUILT"


def test_posting_is_idempotent_per_journal(session):
    """A partial failure must leave the successful entries posted, because
    Oracle already has them. A retry posts only what did not land."""
    _job(session).run()
    session.commit()

    service = JournalService(session, s.TENANT_ID, s.CLOCK_DATE)
    period = service.list_journals()[0].period

    first = service.post_period(period)
    session.commit()
    second = service.post_period(period)
    session.commit()

    assert first.posted > 0
    assert second.posted == 0
    assert second.skipped == first.posted


def test_a_posted_journal_keeps_the_reference_oracle_returned(session):
    """The only evidence that the entry landed."""
    _job(session).run()
    session.commit()

    service = JournalService(session, s.TENANT_ID, s.CLOCK_DATE)
    period = service.list_journals()[0].period
    service.post_period(period)
    session.commit()

    posted = service.list_journals(period=period, status="POSTED")
    assert posted
    assert all(journal.oracle_reference for journal in posted)
    assert all(journal.posted_at for journal in posted)


def test_a_failing_adapter_leaves_the_entry_retriable(session):
    """Nothing in the book depends on the handover succeeding."""

    class Broken:
        name = "broken"

        def post(self, journal):
            raise RuntimeError("Fusion is unreachable")

    _job(session).run()
    session.commit()

    service = JournalService(session, s.TENANT_ID, s.CLOCK_DATE, adapter=Broken())
    period = service.list_journals()[0].period
    result = service.post_period(period)
    session.commit()

    assert result.posted == 0
    assert result.failed > 0
    assert all(
        journal.status == "FAILED"
        for journal in service.list_journals(period=period)
    )

    # And a working adapter afterwards posts them.
    healthy = JournalService(session, s.TENANT_ID, s.CLOCK_DATE)
    retry = healthy.post_period(period)
    session.commit()
    assert retry.posted == result.failed


# ==========================================================================
# The order inside the job
# ==========================================================================


def test_accrual_runs_before_advisory(session):
    """The advisory layer reads live positions, and a stale accrual
    mis-states the ladder it is measuring a gap against."""
    result = _job(session).run()
    session.commit()

    assert result.steps[0].startswith("Accrued")
    assert result.steps[-1].startswith("Advisory")


def test_the_advisory_refusal_does_not_take_the_accrual_down_with_it(session):
    """The layer refusing to run without an investment policy is a feature.
    It must not stop the ledger.

    The policy is superseded rather than removed, because nothing in this
    system deletes and a superseded policy is exactly the state a customer
    who has not written their next one is in.
    """
    from app.models import InvestmentPolicy

    for policy in session.query(InvestmentPolicy).all():
        policy.superseded_at = "2026-09-02T00:00:00+00:00"
    session.flush()

    result = _job(session).run()
    session.commit()

    assert result.accrual_rows_written > 0
    assert result.journals_built > 0
    assert result.advisory_run_id is None
    assert "liquidity buffer" in result.advisory_skipped


# ==========================================================================
# The blotter
# ==========================================================================


def test_the_stage_label_carries_the_daily_figure(client, session):
    client.post("/api/v1/jobs/nightly", json={})

    deals = client.get("/api/v1/state").json()["deals"]
    accruing = [deal for deal in deals if "accruing" in deal["stage"]]

    assert accruing, "No deal reported a daily figure."
    for deal in accruing:
        assert deal["accrual_today_pence"] > 0
        assert deal["accrual_cumulative_pence"] > 0
        assert "a day" in deal["stage"]


def test_the_deal_panel_shows_the_accruals_and_the_journals(client):
    client.post("/api/v1/jobs/nightly", json={})

    detail = client.get("/api/v1/deals/dl_nts_001").json()
    assert len(detail["accruals"]) == 60
    assert detail["journals"]
    assert detail["journals"][0]["status"] == "BUILT"


def test_the_nightly_endpoint_returns_202(client):
    """The caller is a scheduler and does not wait."""
    response = client.post("/api/v1/jobs/nightly", json={})
    assert response.status_code == 202
    assert response.json()["accepted"] is True
