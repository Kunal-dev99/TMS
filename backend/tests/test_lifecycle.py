"""Phase 3. The deal lifecycle, capture to close.

Document 5 sets four exit criteria:

    A confirmation arriving out of order matches correctly.
    An amendment into a prior period is refused with a distinct code rather
    than silently allowed.
    A deal reaches closed only when three sources agree.
    Coverage moves backwards without an error when an exposure date slips.

The last is in test_currency.py. The first three are here.
"""

from app import seed_data as s

P = 100


def _book(
    client,
    signer,
    counterparty="cp_meridian",
    principal=5_000_000 * P,
    tenor=6,
    rate=425,
    instrument="DEPOSIT",
):
    """A live deal to work against."""
    booked = client.post(
        "/api/v1/deals",
        json={
            "counterparty_id": counterparty,
            "instrument": instrument,
            "principal_pence": principal,
            "tenor_months": tenor,
            "rate_bp": rate,
        },
    ).json()
    signer.post(
        f"/api/v1/deals/{booked['deal']['id']}/approve",
        json={"role": booked["deal"]["required_approver"] or "ANALYST"},
    )
    return booked["deal"]


def _confirm(client, deal, **overrides):
    body = {
        "message_type": "MT320",
        "reference": overrides.pop("reference", "REF-" + deal["id"][-6:]),
        "counterparty_id": deal["counterparty_id"],
        "instrument": deal["instrument"],
        "principal_pence": deal["principal_pence"],
        "rate_bp": deal["rate_bp"],
        "value_date": deal["value_date"],
        "maturity_date": deal["maturity_date"],
    }
    body.update(overrides)
    return client.post("/api/v1/confirmations", json=body).json()


# ==========================================================================
# Exit criterion. A confirmation arriving out of order matches correctly.
# ==========================================================================


def test_a_confirmation_arriving_before_the_deal_waits(client):
    """Not an error. It means the deal has not been keyed yet."""
    outcome = client.post(
        "/api/v1/confirmations",
        json={
            "message_type": "MT320",
            "reference": "EARLY-001",
            "counterparty_id": "cp_meridian",
            "instrument": "DEPOSIT",
            "principal_pence": 5_000_000 * P,
            "rate_bp": 425,
            "value_date": s.CLOCK_DATE,
            "maturity_date": None,
        },
    )
    assert outcome.status_code == 201
    body = outcome.json()
    assert body["match_status"] == "UNMATCHED"
    assert body["deal_id"] is None
    assert body["queue_item_id"] is None


def test_the_waiting_confirmation_matches_when_the_deal_is_keyed(client, signer):
    """The exit criterion. Without this, a confirmation that beat the deal
    would sit unmatched for ever and somebody would have to notice."""
    client.post(
        "/api/v1/confirmations",
        json={
            "message_type": "MT320",
            "reference": "EARLY-002",
            "counterparty_id": "cp_meridian",
            "instrument": "DEPOSIT",
            "principal_pence": 5_000_000 * P,
            "rate_bp": 425,
            "value_date": s.CLOCK_DATE,
            # Agrees on every field, so the test is about matching to the
            # right deal rather than about a difference.
            "maturity_date": s.months_after(s.CLOCK_DATE, 6),
        },
    )
    assert client.get("/api/v1/confirmations?match_status=UNMATCHED").json()

    deal = _book(client, signer)

    matched = client.get("/api/v1/confirmations").json()
    early = next(c for c in matched if c["reference"] == "EARLY-002")
    assert early["match_status"] == "MATCHED"
    assert early["deal_id"] == deal["id"]


def test_a_confirmation_arriving_after_the_deal_matches_immediately(client, signer):
    deal = _book(client, signer)
    body = _confirm(client, deal)

    assert body["match_status"] == "MATCHED"
    assert body["deal_id"] == deal["id"]
    assert body["differences"] == []


def test_a_repeat_returns_the_existing_confirmation(client, signer):
    """A feed that redelivers is a feed, not a second trade."""
    deal = _book(client, signer)
    first = _confirm(client, deal, reference="DUP-001")
    second = _confirm(client, deal, reference="DUP-001")

    assert first["confirmation_id"] == second["confirmation_id"]
    assert len(client.get("/api/v1/confirmations").json()) == 3  # two seeded, one new


def test_an_unknown_message_type_is_refused(client):
    response = client.post(
        "/api/v1/confirmations",
        json={
            "message_type": "MT999",
            "reference": "X",
            "instrument": "DEPOSIT",
            "principal_pence": 100,
            "rate_bp": 400,
            "value_date": s.CLOCK_DATE,
        },
    )
    assert response.status_code == 422


# ==========================================================================
# Matching, field by field
# ==========================================================================


def test_a_mismatch_names_the_field_and_both_values(client, signer):
    """The rate was keyed at 4.30 and confirmed at 4.28, rather than
    reporting that something differs."""
    deal = _book(client, signer, rate=430)
    body = _confirm(client, deal, rate_bp=428)

    assert body["match_status"] == "MISMATCHED"
    assert body["queue_item_id"] is not None

    difference = next(d for d in body["differences"] if d["field_name"] == "rate_bp")
    assert difference["keyed_value"] == "4.30 per cent"
    assert difference["confirmed_value"] == "4.28 per cent"


def test_a_forward_mismatch_reads_as_an_exchange_rate_not_a_percentage(
    client, signer
):
    """`rate_bp` holds an interest rate for a deposit and an exchange rate for
    a forward. Rendered as a percentage, a forward keyed at 1.1740 is reported
    as 117.40 per cent: wrong by two orders of magnitude, and wrong in a way
    that still looks like a rate, so nobody queries it.
    """
    deal = _book(
        client,
        signer,
        counterparty="cp_harbour",
        principal=1_000_000 * P,
        tenor=3,
        rate=11740,
        instrument="FX_FORWARD",
    )
    body = _confirm(client, deal, rate_bp=11700)

    assert body["match_status"] == "MISMATCHED"
    difference = next(d for d in body["differences"] if d["field_name"] == "rate_bp")
    assert difference["keyed_value"] == "1.1740"
    assert difference["confirmed_value"] == "1.1700"
    assert "per cent" not in difference["keyed_value"]


def test_a_mismatch_lands_in_the_same_queue_with_a_reason_code(client, signer):
    """One queue, two causes. One strip entry rather than two."""
    deal = _book(client, signer, rate=430)
    _confirm(client, deal, rate_bp=428)

    queue = client.get("/api/v1/queue").json()
    assert len(queue) == 1
    assert queue[0]["cause"] == "CONFIRMATION_MISMATCH"
    assert queue[0]["reason_code"] == "RATE_BP"
    assert "keyed at 4.30 per cent" in queue[0]["detail"]
    assert "confirmed at 4.28 per cent" in queue[0]["detail"]

    counts = client.get("/api/v1/state").json()["queue_counts"]
    assert counts == {"total": 1, "limit_failures": 0, "confirmation_mismatches": 1}


def test_correcting_takes_the_confirmed_terms_and_reruns_the_checks(
    client, signer, session
):
    """A corrected rate changes the accrual and can change the measured
    exposure, so this is a new decision about a position rather than a data
    fix."""
    deal = _book(client, signer, rate=430)
    body = _confirm(client, deal, rate_bp=428)

    client.post(
        f"/api/v1/queue/{body['queue_item_id']}/resolve",
        json={"resolution": "CORRECTED"},
    )

    from app.repo import deals as deal_repo
    from app.repo import evidence as evidence_repo

    session.expire_all()
    corrected = deal_repo.get(session, deal["id"])
    assert corrected.rate_bp == 428

    run = evidence_repo.get_check_run(session, corrected.check_run_id)
    assert run.purpose == "CORRECTION"

    detail = client.get(f"/api/v1/deals/{deal['id']}").json()
    assert detail["confirmation"]["match_status"] == "MATCHED"


def test_challenging_leaves_the_deal_alone_and_the_item_open(
    client, signer, session
):
    """Somebody is talking to the bank. Closing the item would say the
    disagreement was settled when only the conversation had started."""
    deal = _book(client, signer, rate=430)
    body = _confirm(client, deal, rate_bp=428)

    client.post(
        f"/api/v1/queue/{body['queue_item_id']}/resolve",
        json={"resolution": "CHALLENGED", "reason": "Rang the desk."},
    )

    from app.repo import deals as deal_repo

    session.expire_all()
    assert deal_repo.get(session, deal["id"]).rate_bp == 430
    assert len(client.get("/api/v1/queue").json()) == 1

    detail = client.get(f"/api/v1/deals/{deal['id']}").json()
    assert detail["confirmation"]["match_status"] == "DISPUTED"


def test_a_confirmation_cannot_match_a_deal_for_another_counterparty(
    client, signer
):
    """Document 1 lists this as an invariant the schema cannot hold."""
    deal = _book(client, signer, counterparty="cp_meridian")
    early = client.post(
        "/api/v1/confirmations",
        json={
            "message_type": "MT320",
            "reference": "WRONG-CP",
            "counterparty_id": "cp_caledonia",
            "instrument": "DEPOSIT",
            "principal_pence": 5_000_000 * P,
            "rate_bp": 425,
            "value_date": s.CLOCK_DATE,
        },
    ).json()

    response = client.post(
        f"/api/v1/confirmations/{early['confirmation_id']}/match",
        json={"deal_id": deal["id"]},
    )
    assert response.status_code == 404
    assert "same counterparty" in response.json()["error"]["message"]


# ==========================================================================
# Exit criterion. An amendment into a prior period is refused distinctly.
# ==========================================================================


def test_an_amendment_needs_a_reason(client, signer):
    deal = _book(client, signer)
    response = client.post(
        f"/api/v1/deals/{deal['id']}/amendments",
        json={"type": "CORRECTION", "effective_date": s.CLOCK_DATE, "reason": "  "},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AMENDMENT_REASON_REQUIRED"


def test_an_amendment_cannot_take_effect_before_the_deal_started(client, signer):
    deal = _book(client, signer)
    response = client.post(
        f"/api/v1/deals/{deal['id']}/amendments",
        json={
            "type": "CORRECTION",
            "effective_date": "2026-01-01",
            "reason": "Backdated.",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EFFECTIVE_DATE_BEFORE_VALUE_DATE"


def test_raising_changes_nothing_and_says_what_it_would(client, session):
    """Raising and applying are two calls on purpose."""
    client.post("/api/v1/jobs/nightly", json={})

    from app.models import Accrual

    before = session.query(Accrual).count()

    raised = client.post(
        "/api/v1/deals/dl_nts_001/amendments",
        json={
            "type": "CORRECTION",
            "effective_date": s.days_ago(10),
            "reason": "Rate corrected against the confirmation.",
            "new_rate_bp": 410,
        },
    ).json()

    # Eleven days, because on or after the effective date includes it.
    assert raised["preview"]["accruals_affected"] == 11
    assert raised["preview"]["amount_to_reverse_pence"] > 0
    assert session.query(Accrual).count() == before, "Raising changed the ledger."


def test_an_amendment_into_a_posted_period_is_refused_with_its_own_code(
    client, session
):
    """The exit criterion.

    Whether a closed period can be reopened is an accounting policy decision
    rather than a technical one. It is surfaced as a distinct refusal rather
    than decided in code.
    """
    client.post("/api/v1/jobs/nightly", json={})

    period = s.days_ago(10)[:7]
    client.post("/api/v1/journals/post", json={"period": period})

    raised = client.post(
        "/api/v1/deals/dl_nts_001/amendments",
        json={
            "type": "CORRECTION",
            "effective_date": s.days_ago(10),
            "reason": "Rate corrected against the confirmation.",
            "new_rate_bp": 410,
        },
    ).json()
    assert raised["preview"]["any_period_closed"] is True

    response = client.post(f"/api/v1/amendments/{raised['amendment_id']}/apply")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CLOSED_PERIOD_LOCKED"
    assert period in response.json()["error"]["message"]


def test_applying_reverses_what_was_recognised_and_reposts(client, session):
    """Recalculating is the easy half. Knowing what was already recognised is
    the hard half, and it is only possible because accrual is stored per
    day."""
    client.post("/api/v1/jobs/nightly", json={})

    effective = s.days_ago(10)
    raised = client.post(
        "/api/v1/deals/dl_nts_001/amendments",
        json={
            "type": "CORRECTION",
            "effective_date": effective,
            "reason": "Rate corrected against the confirmation.",
            "new_rate_bp": 410,
        },
    ).json()

    applied = client.post(f"/api/v1/amendments/{raised['amendment_id']}/apply").json()
    assert applied["reversed_pence"] > 0
    assert applied["reposted_pence"] > applied["reversed_pence"], (
        "4.10 per cent is more than 4.05, so the reposted amount is larger."
    )

    from app.models import Accrual

    session.expire_all()
    reversals = (
        session.query(Accrual).filter(Accrual.reversal_of.isnot(None)).all()
    )
    assert len(reversals) == 11
    assert all(row.amendment_id == raised["amendment_id"] for row in reversals)
    assert all(row.amount_pence < 0 for row in reversals)


def test_the_original_accruals_survive_an_amendment(client, session):
    """A correction is an entry, not an edit."""
    client.post("/api/v1/jobs/nightly", json={})

    from app.models import Accrual

    originals = {
        row.id
        for row in session.query(Accrual).filter(Accrual.deal_id == "dl_nts_001")
    }

    raised = client.post(
        "/api/v1/deals/dl_nts_001/amendments",
        json={
            "type": "CORRECTION",
            "effective_date": s.days_ago(10),
            "reason": "Rate corrected.",
            "new_rate_bp": 410,
        },
    ).json()
    client.post(f"/api/v1/amendments/{raised['amendment_id']}/apply")

    session.expire_all()
    still_there = {
        row.id
        for row in session.query(Accrual).filter(Accrual.deal_id == "dl_nts_001")
    }
    assert originals <= still_there, "An original accrual row was removed."


def test_an_amendment_cannot_be_applied_twice(client):
    client.post("/api/v1/jobs/nightly", json={})
    raised = client.post(
        "/api/v1/deals/dl_nts_001/amendments",
        json={
            "type": "CORRECTION",
            "effective_date": s.days_ago(5),
            "reason": "Rate corrected.",
            "new_rate_bp": 410,
        },
    ).json()

    assert client.post(f"/api/v1/amendments/{raised['amendment_id']}/apply").status_code == 200
    second = client.post(f"/api/v1/amendments/{raised['amendment_id']}/apply")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "AMENDMENT_ALREADY_APPLIED"


# ==========================================================================
# Exit criterion. Closed only when three sources agree.
# ==========================================================================


def _statement(client, amount_pence, reference="STMT-1"):
    return client.post(
        "/api/v1/statements",
        json={
            "account_name": "Group operating account",
            "amount_pence": amount_pence,
            "value_date": s.CLOCK_DATE,
            "reference": reference,
        },
    ).json()["statement_line_id"]


def test_all_three_agreeing_closes_the_deal(client, session):
    client.post("/api/v1/jobs/nightly", json={})

    detail = client.get("/api/v1/deals/dl_nts_001").json()
    expected = detail["deal"]["measured_pence"]
    line = _statement(client, expected)

    response = client.post(
        "/api/v1/deals/dl_nts_001/settle", json={"statement_line_id": line}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["match_status"] == "AGREED"
    assert body["closed_at"] is not None

    from app.repo import deals as deal_repo

    session.expire_all()
    assert deal_repo.get(session, "dl_nts_001").status == "CLOSED"


def test_closing_returns_the_headroom_to_the_book(client):
    """Until a deal closes the counterparty's headroom is still consumed and
    the next deal may be blocked for no reason. That is why closing is part
    of the control system rather than an accounting formality."""
    client.post("/api/v1/jobs/nightly", json={})

    before = next(
        row
        for row in client.get("/api/v1/state").json()["book"]
        if row["counterparty_id"] == "cp_nts"
    )

    detail = client.get("/api/v1/deals/dl_nts_001").json()
    line = _statement(client, detail["deal"]["measured_pence"])
    client.post("/api/v1/deals/dl_nts_001/settle", json={"statement_line_id": line})

    after = next(
        row
        for row in client.get("/api/v1/state").json()["book"]
        if row["counterparty_id"] == "cp_nts"
    )
    assert before["used_pence"] > 0
    assert after["used_pence"] == 0
    assert after["headroom_pence"] > before["headroom_pence"]


def test_two_of_three_agreeing_is_not_enough(client, session):
    """The rule that is easy to get wrong and expensive to explain
    afterwards. If the record and the confirmation agree but the statement
    differs, the money did not arrive as promised."""
    client.post("/api/v1/jobs/nightly", json={})

    detail = client.get("/api/v1/deals/dl_nts_001").json()
    expected = detail["deal"]["measured_pence"]
    line = _statement(client, expected - 500_000 * P)

    response = client.post(
        "/api/v1/deals/dl_nts_001/settle", json={"statement_line_id": line}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["match_status"] == "BREAK"
    assert body["closed_at"] is None
    assert "did not arrive as promised" in body["break_detail"]

    from app.repo import deals as deal_repo

    session.expire_all()
    assert deal_repo.get(session, "dl_nts_001").status != "CLOSED"


def test_the_break_names_which_two_agree_and_by_how_much(client):
    client.post("/api/v1/jobs/nightly", json={})
    detail = client.get("/api/v1/deals/dl_nts_001").json()
    line = _statement(client, detail["deal"]["measured_pence"] - 500_000 * P)

    body = client.post(
        "/api/v1/deals/dl_nts_001/settle", json={"statement_line_id": line}
    ).json()
    assert "£500,000 out" in body["break_detail"]


def test_a_deal_with_no_confirmation_does_not_close_on_two_sources(client, signer):
    """Meridian is seeded without a confirmation. Closing on the record and
    the statement alone is exactly the shortcut this control prevents."""
    client.post("/api/v1/jobs/nightly", json={})

    detail = client.get("/api/v1/deals/dl_mer_001").json()
    assert detail["confirmation"] is None

    line = _statement(client, detail["deal"]["measured_pence"])
    body = client.post(
        "/api/v1/deals/dl_mer_001/settle", json={"statement_line_id": line}
    ).json()

    assert body["match_status"] == "PENDING"
    assert body["closed_at"] is None
    assert "not a three way match" in body["break_detail"]


# ==========================================================================
# Maturity, and the panel
# ==========================================================================


def test_a_deal_past_its_maturity_date_becomes_matured_not_closed(client, session):
    """Matured means due. Closed means three sources agreed."""
    client.post("/api/v1/admin/clock", json={"today_date": "2027-01-05"})
    client.post("/api/v1/jobs/nightly", json={})

    from app.repo import deals as deal_repo

    session.expire_all()
    meridian = deal_repo.get(session, "dl_mer_001")
    assert meridian.status == "MATURED"
    assert meridian.closed_at is None


def test_the_deal_panel_carries_the_confirmation_and_the_amendments(client):
    client.post("/api/v1/jobs/nightly", json={})
    raised = client.post(
        "/api/v1/deals/dl_nts_001/amendments",
        json={
            # A correction rather than a roll. This fixture said ROLL and
            # moved only the rate, which is not a roll: a roll extends the
            # deal. The panel is what is under test, and a correction is the
            # amendment that actually matches these terms.
            "type": "CORRECTION",
            "effective_date": s.days_ago(5),
            "reason": "Rate corrected against the confirmation.",
            "new_rate_bp": 415,
        },
    ).json()
    client.post(f"/api/v1/amendments/{raised['amendment_id']}/apply")

    detail = client.get("/api/v1/deals/dl_nts_001").json()
    assert detail["confirmation"]["match_status"] == "MATCHED"
    assert len(detail["amendments"]) == 1
    assert detail["amendments"][0]["status"] == "APPLIED"

    keys = [event["key"] for event in detail["timeline"]]
    assert "confirmed" in keys
    assert "three_way" in keys
    assert any(key.startswith("amendment_") for key in keys)


def test_the_blotter_says_awaiting_confirmation_until_one_arrives(client):
    """The gap between capture and confirmation is the window the whole
    matching control exists for, so the blotter names it."""
    deals = {d["id"]: d["stage"] for d in client.get("/api/v1/state").json()["deals"]}
    assert deals["dl_mer_001"] == "awaiting confirmation"
    assert "accruing" in deals["dl_nts_001"] or "matures" in deals["dl_nts_001"]


# ==========================================================================
# The amendment gate.
#
# An amendment is a new decision about a position, not a data fix. Without a
# gate it is the way round the whole control system: raise a partial
# drawdown, put the principal up rather than down, and the deal lands at any
# size with no check run, no queue item and no breach.
# ==========================================================================


def test_an_amendment_cannot_raise_a_principal_past_its_limit(client, signer):
    """The hole this closes. Harbour's limit is £8m and this asks for £500m."""
    before = client.get("/api/v1/state").json()
    harbour = next(r for r in before["book"] if r["counterparty_id"] == "cp_harbour")

    raised = client.post(
        "/api/v1/deals/dl_har_001/amendments",
        json={
            "type": "CORRECTION",
            "effective_date": s.CLOCK_DATE,
            "reason": "Principal raised far past the limit.",
            "new_principal_pence": 500_000_000 * P,
        },
    ).json()

    response = client.post(f"/api/v1/amendments/{raised['amendment_id']}/apply")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AMENDMENT_FAILS_CHECKS"

    after = client.get("/api/v1/state").json()
    still = next(r for r in after["book"] if r["counterparty_id"] == "cp_harbour")
    assert still["used_pence"] == harbour["used_pence"], "nothing was applied"
    assert still["headroom_pence"] >= 0

    # The refusal is evidence, not just an error body.
    assert after["queue_counts"]["limit_failures"] == 1


def test_a_refused_amendment_writes_the_run_it_was_tested_against(
    client, signer, session
):
    """A refusal with no evidence is one somebody has to take on trust."""
    from app.models import CheckRun

    raised = client.post(
        "/api/v1/deals/dl_har_001/amendments",
        json={
            "type": "CORRECTION",
            "effective_date": s.CLOCK_DATE,
            "reason": "Too large.",
            "new_principal_pence": 500_000_000 * P,
        },
    ).json()
    client.post(f"/api/v1/amendments/{raised['amendment_id']}/apply")

    runs = [
        r
        for r in session.query(CheckRun).all()
        if r.deal_id == "dl_har_001" and r.purpose == "AMENDMENT"
    ]
    assert len(runs) == 1
    assert runs[0].outcome == "FAIL"
    assert runs[0].failed_count >= 1


def test_an_amendment_that_stays_inside_the_limit_still_applies(client, signer):
    """The gate refuses what breaches and nothing else. A deal being amended
    is not counted twice against its own limit."""
    client.post("/api/v1/jobs/nightly", json={})
    raised = client.post(
        "/api/v1/deals/dl_nts_001/amendments",
        json={
            "type": "PARTIAL_DRAWDOWN",
            "effective_date": s.days_ago(5),
            "reason": "Client drew less than committed.",
            "new_principal_pence": 12_000_000 * P,
        },
    ).json()

    response = client.post(f"/api/v1/amendments/{raised['amendment_id']}/apply")
    assert response.status_code == 200, response.json()
    assert response.json()["deal"]["principal_pence"] == 12_000_000 * P


def test_a_partial_drawdown_cannot_increase_the_principal(client, signer):
    """The type is not decoration. A drawdown that grows is not a drawdown,
    and the word in the audit trail has to describe what happened."""
    response = client.post(
        "/api/v1/deals/dl_har_001/amendments",
        json={
            "type": "PARTIAL_DRAWDOWN",
            "effective_date": s.CLOCK_DATE,
            "reason": "Growing a drawdown.",
            "new_principal_pence": 900_000_000 * P,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AMENDMENT_TYPE_INVALID"


def test_a_roll_has_to_extend_the_deal(client, signer):
    response = client.post(
        "/api/v1/deals/dl_nts_001/amendments",
        json={
            "type": "ROLL",
            "effective_date": s.CLOCK_DATE,
            "reason": "A roll that rolls nowhere.",
            "new_rate_bp": 415,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AMENDMENT_TYPE_INVALID"


def test_a_roll_past_the_tenor_band_is_refused_by_the_gate(client, signer):
    """A roll changes the maturity, so the tenor is re-derived rather than
    carried over. Harbour is a BBB+ name capped at three months."""
    raised = client.post(
        "/api/v1/deals/dl_har_001/amendments",
        json={
            "type": "ROLL",
            "effective_date": s.CLOCK_DATE,
            "reason": "Rolled well past the band.",
            "new_maturity_date": "2028-11-04",
        },
    ).json()

    response = client.post(f"/api/v1/amendments/{raised['amendment_id']}/apply")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AMENDMENT_FAILS_CHECKS"
    message = response.json()["error"]["message"]
    assert "27 months" in message, "the tenor is re-derived from the new maturity"
    assert "maximum of 3" in message
