"""The control loop, end to end, through the real API.

One circuit, made visible: approve a counterparty with a limit, propose a
deal, six checks run live, record it, exposure moves, and the next check
reads that exposure. That last clause is the whole of it. A register would
stop after recording.

The journey test at the bottom is the demonstration run sheet from section 12
of document 3, automated, and it runs on every merge from here on.
"""

from app import seed_data as s

P = 100
ACTOR = "A. Whitfield"
SIGNER = "M. Doran"


def outcome(payload: dict, key: str) -> dict:
    return next(c for c in payload["checks"] if c["key"] == key)


# ==========================================================================
# The check endpoint persists nothing
# ==========================================================================


def test_the_check_endpoint_writes_nothing(client, session):
    from app.models import CheckRun, Deal

    before = (session.query(CheckRun).count(), session.query(Deal).count())

    response = client.post(
        "/api/v1/deals/check",
        json={
            "counterparty_id": "cp_northern",
            "instrument": "DEPOSIT",
            "principal_pence": 10_000_000 * P,
            "tenor_months": 6,
            "rate_bp": 425,
        },
    )
    assert response.status_code == 200
    assert response.json()["check_run_id"] is None

    assert (session.query(CheckRun).count(), session.query(Deal).count()) == before


def test_the_check_endpoint_returns_the_screen_two_arithmetic(client):
    response = client.post(
        "/api/v1/deals/check",
        json={
            "counterparty_id": "cp_northern",
            "instrument": "DEPOSIT",
            "principal_pence": 10_000_000 * P,
            "tenor_months": 6,
            "rate_bp": 425,
        },
    )
    body = response.json()

    assert body["outcome"] == "FAIL"
    assert body["failed_count"] == 1
    assert outcome(body, "ENTITY_LIMIT")["passed"] is True

    group = outcome(body, "GROUP_LIMIT")
    assert group["passed"] is False
    assert "£28,119,836" in group["detail"]
    assert round(group["resize_to_pence"] / 100) == 6_880_164


def test_an_unknown_counterparty_is_refused_with_a_code(client):
    response = client.post(
        "/api/v1/deals/check",
        json={
            "counterparty_id": "cp_nobody",
            "instrument": "DEPOSIT",
            "principal_pence": 100 * P,
            "tenor_months": 3,
            "rate_bp": 400,
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "COUNTERPARTY_NOT_FOUND"
    assert response.json()["error"]["field"] == "counterparty_id"


def test_a_malformed_request_comes_back_in_the_standard_error_body(client):
    """Pydantic's 422, reshaped. Two shapes of error would mean two shapes of
    error handling in the client, and the client would get one of them
    wrong."""
    response = client.post(
        "/api/v1/deals/check",
        json={
            "counterparty_id": "cp_meridian",
            "instrument": "DEPOSIT",
            "principal_pence": -5,
            "tenor_months": 6,
            "rate_bp": 400,
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INVALID_REQUEST"
    assert body["error"]["field"] == "principal_pence"


# ==========================================================================
# Recording a deal
# ==========================================================================


def _record(client, counterparty_id, principal_pence, tenor_months, **extra):
    return client.post(
        "/api/v1/deals",
        json={
            "counterparty_id": counterparty_id,
            "instrument": "DEPOSIT",
            "principal_pence": principal_pence,
            "tenor_months": tenor_months,
            "rate_bp": 425,
            **extra,
        },
    )


def test_a_passing_deal_is_recorded_with_the_versions_it_was_tested_against(
    client, session
):
    response = _record(client, "cp_meridian", 5_000_000 * P, 6)
    assert response.status_code == 201

    body = response.json()
    assert body["deal"]["status"] == "PROPOSED"
    assert body["queue_item_id"] is None
    assert body["run"]["check_run_id"] is not None

    from app.repo import deals as deal_repo

    deal = deal_repo.get(session, body["deal"]["id"])
    assert deal.policy_version_id == "pol_v1"
    assert deal.limit_id_at_booking == "lim_meridian_1"
    assert deal.check_run_id == body["run"]["check_run_id"]
    assert deal.capture_source == "KEYED"


def test_the_control_run_is_written_with_its_inputs_and_its_results(client, session):
    body = _record(client, "cp_meridian", 5_000_000 * P, 6).json()

    from app.repo import evidence as evidence_repo

    run = evidence_repo.get_check_run(session, body["run"]["check_run_id"])
    assert run.purpose == "BOOKING"
    assert run.outcome == "PASS"
    assert run.policy_version_id == "pol_v1"

    import json

    inputs = json.loads(run.inputs_json)
    results = json.loads(run.results_json)
    assert len(results) == 6
    assert inputs["policy"]["id"] == "pol_v1"

    from app.services.check_engine import CheckEngine

    re_derived = CheckEngine.evaluate(inputs)
    assert [c.passed for c in re_derived] == [r["passed"] for r in results]


def test_a_blocked_deal_is_a_201_and_raises_a_queue_item(client, session):
    """The record was created and the exception was raised. The control
    worked, so this is not an error."""
    response = _record(client, "cp_northern", 10_000_000 * P, 6)
    assert response.status_code == 201

    body = response.json()
    assert body["deal"]["status"] == "BLOCKED"
    assert body["deal"]["stage"] == "blocked"
    assert body["queue_item_id"] is not None

    queue = client.get("/api/v1/queue").json()
    assert len(queue) == 1
    assert queue[0]["cause"] == "LIMIT_FAILURE"
    assert queue[0]["reason_code"] == "GROUP_LIMIT"
    assert "£28,119,836" in queue[0]["detail"]
    assert "£6,880,164 would fit" in queue[0]["detail"]


def test_a_blocked_deal_consumes_no_headroom(client):
    """A refused deal is evidence, not a position."""
    before = _group_used(client, "cp_northern")
    _record(client, "cp_northern", 10_000_000 * P, 6)
    assert _group_used(client, "cp_northern") == before


def test_an_override_is_refused_under_a_hard_block(client):
    response = _record(
        client, "cp_northern", 10_000_000 * P, 6, override_reason="Board approved."
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OVERRIDE_NOT_ALLOWED"


def test_an_override_is_recorded_under_a_warning_policy(client, session):
    """Screen 3. The same six results, a different consequence."""
    assert (
        client.post(
            "/api/v1/admin/enforcement", json={"enforcement": "WARN_WITH_OVERRIDE"}
        ).status_code
        == 200
    )

    response = _record(
        client,
        "cp_northern",
        10_000_000 * P,
        6,
        override_reason="Group parent guarantee signed this morning.",
    )
    assert response.status_code == 201

    body = response.json()
    assert body["deal"]["status"] == "PROPOSED"
    assert body["run"]["outcome"] == "OVERRIDDEN"

    from app.repo import evidence as evidence_repo

    run = evidence_repo.get_check_run(session, body["run"]["check_run_id"])
    assert run.outcome == "OVERRIDDEN"

    # The reason is the evidence, so the item exists even though nobody has
    # to act on it.
    assert client.get("/api/v1/queue").json() == []
    item = session.query(
        __import__("app.models", fromlist=["ExceptionItem"]).ExceptionItem
    ).one()
    assert item.resolution == "OVERRIDDEN"
    assert "guarantee" in item.resolution_reason


def test_changing_enforcement_writes_a_new_policy_version(client, session):
    """A rule that changed in place would make every run recorded under the
    old one unreproducible."""
    from app.models import PolicyVersion

    client.post("/api/v1/admin/enforcement", json={"enforcement": "WARN_WITH_OVERRIDE"})

    versions = session.query(PolicyVersion).all()
    assert len(versions) == 2
    current = [v for v in versions if v.superseded_at is None]
    assert len(current) == 1
    assert current[0].enforcement == "WARN_WITH_OVERRIDE"


# ==========================================================================
# Approval, and the exposure moving
# ==========================================================================


def test_approving_puts_the_deal_on_the_book_and_moves_the_exposure(client, signer):
    """The clause that makes this a control system rather than a register:
    the next check reads the exposure this one created."""
    before = _entity_used(client, "cp_meridian")

    deal = _record(client, "cp_meridian", 5_000_000 * P, 6).json()["deal"]
    assert _entity_used(client, "cp_meridian") == before, (
        "A proposed deal is not yet on the book."
    )

    response = signer.post(
        f"/api/v1/deals/{deal['id']}/approve",
        json={"role": "HEAD_OF_TREASURY"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ACTIVE"

    assert _entity_used(client, "cp_meridian") == before + 5_000_000 * P


def test_the_next_check_reads_the_exposure_the_last_one_created(client, signer):
    first = _record(client, "cp_meridian", 5_000_000 * P, 6).json()["deal"]
    signer.post(
        f"/api/v1/deals/{first['id']}/approve",
        json={"role": "HEAD_OF_TREASURY"},
    )

    body = client.post(
        "/api/v1/deals/check",
        json={
            "counterparty_id": "cp_meridian",
            "instrument": "DEPOSIT",
            "principal_pence": 12_000_000 * P,
            "tenor_months": 6,
            "rate_bp": 425,
        },
    ).json()

    entity = outcome(body, "ENTITY_LIMIT")
    assert entity["passed"] is False
    assert "£21,009,205" in entity["detail"]


def test_a_deal_cannot_be_signed_twice(client, signer):
    deal = _record(client, "cp_meridian", 5_000_000 * P, 6).json()["deal"]
    payload = {"role": "HEAD_OF_TREASURY"}
    assert signer.post(
        f"/api/v1/deals/{deal['id']}/approve", json=payload).status_code == 200
    second = signer.post(
        f"/api/v1/deals/{deal['id']}/approve", json=payload)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "DEAL_ALREADY_APPROVED"


def test_a_blocked_deal_cannot_be_signed_while_its_queue_item_is_open(client, signer):
    body = _record(client, "cp_northern", 10_000_000 * P, 6).json()
    response = signer.post(
        f"/api/v1/deals/{body['deal']['id']}/approve",
        json={"role": "HEAD_OF_TREASURY"},
    )
    assert response.status_code == 409


def test_an_unapproved_deal_cannot_be_instructed(client):
    deal = _record(client, "cp_meridian", 5_000_000 * P, 6).json()["deal"]
    response = client.post(
        f"/api/v1/deals/{deal['id']}/instruct", json={}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DEAL_NOT_APPROVED"


def test_instructing_writes_to_the_oracle_boundary_rather_than_sending(client, signer):
    deal = _record(client, "cp_meridian", 5_000_000 * P, 6).json()["deal"]
    signer.post(
        f"/api/v1/deals/{deal['id']}/approve",
        json={"role": "HEAD_OF_TREASURY"},
    )
    response = client.post(
        f"/api/v1/deals/{deal['id']}/instruct", json={}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "PENDING"

    instructions = client.get("/api/v1/instructions").json()
    assert len(instructions) == 1
    assert instructions[0]["deal_id"] == deal["id"]


# ==========================================================================
# The queue
# ==========================================================================


def test_resizing_cancels_the_refused_deal_and_closes_the_item(client, session):
    body = _record(client, "cp_northern", 10_000_000 * P, 6).json()

    response = client.post(
        f"/api/v1/queue/{body['queue_item_id']}/resolve",
        json={"resolution": "RESIZED"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "RESOLVED"

    assert client.get("/api/v1/queue").json() == []

    from app.repo import deals as deal_repo

    assert deal_repo.get(session, body["deal"]["id"]).status == "CANCELLED"


def test_an_item_cannot_be_resolved_twice(client):
    body = _record(client, "cp_northern", 10_000_000 * P, 6).json()
    payload = {"resolution": "RESIZED"}
    client.post(f"/api/v1/queue/{body['queue_item_id']}/resolve", json=payload)
    second = client.post(f"/api/v1/queue/{body['queue_item_id']}/resolve", json=payload)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "QUEUE_ITEM_ALREADY_RESOLVED"


def test_a_mismatch_resolution_is_refused_on_a_limit_failure(client):
    """CORRECTED belongs to the confirmation cause. Applying it here is a
    defect, not a preference."""
    body = _record(client, "cp_northern", 10_000_000 * P, 6).json()
    response = client.post(
        f"/api/v1/queue/{body['queue_item_id']}/resolve",
        json={"resolution": "CORRECTED"},
    )
    assert response.status_code == 404
    assert "confirmation mismatch" in response.json()["error"]["message"]


# ==========================================================================
# The rating action and the re-test
# ==========================================================================


def test_a_downgrade_resets_the_limit_and_re_tests_the_book(client, session, signer):
    """Screen 4. One call in, an unknown number of breaches out."""
    deal = _record(client, "cp_northern", 6_880_164 * P, 6).json()["deal"]
    signer.post(
        f"/api/v1/deals/{deal['id']}/approve",
        json={"role": "HEAD_OF_TREASURY"},
    )

    response = client.post(
        "/api/v1/counterparties/cp_northern/rating",
        json={"new_rating": "BBB+", "new_status": "WATCH"},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["action"] == "DOWNGRADE"
    assert body["previous_rating"] == "A-"
    assert body["new_limit_pence"] == 8_000_000 * P
    assert body["new_max_tenor_months"] == 3
    assert body["positions_tested"] == 1
    assert body["breaches_raised"] == 1


def test_the_breach_is_on_the_term_and_not_on_the_amount(client, signer):
    """The instinct is to say the deal is too big. It is not. The amount is
    still inside the new limit and it is the term that broke."""
    deal = _record(client, "cp_northern", 6_880_164 * P, 6).json()["deal"]
    signer.post(
        f"/api/v1/deals/{deal['id']}/approve",
        json={"role": "HEAD_OF_TREASURY"},
    )
    client.post(
        "/api/v1/counterparties/cp_northern/rating",
        json={"new_rating": "BBB+", "new_status": "WATCH"},
    )

    breaches = client.get("/api/v1/breaches").json()
    assert len(breaches) == 1
    assert breaches[0]["type"] == "TENOR"
    assert breaches[0]["deal_id"] == deal["id"]
    assert "compliant when booked" in breaches[0]["detail"]


def test_the_re_test_does_not_count_a_position_against_itself(client, signer):
    """The position under test is already inside the held total. Without
    excluding it, every deal is counted twice and everything looks like a
    breach the moment anything is downgraded."""
    deal = _record(client, "cp_meridian", 5_000_000 * P, 3).json()["deal"]
    signer.post(
        f"/api/v1/deals/{deal['id']}/approve",
        json={"role": "HEAD_OF_TREASURY"},
    )

    response = client.post(
        "/api/v1/counterparties/cp_meridian/rating",
        json={"new_rating": "A+", "new_status": "STABLE"},
    )
    assert response.json()["breaches_raised"] == 0
    assert client.get("/api/v1/breaches").json() == []


def test_responding_to_a_breach_does_not_clear_it(client, signer):
    deal = _record(client, "cp_northern", 6_880_164 * P, 6).json()["deal"]
    signer.post(
        f"/api/v1/deals/{deal['id']}/approve",
        json={"role": "HEAD_OF_TREASURY"},
    )
    client.post(
        "/api/v1/counterparties/cp_northern/rating",
        json={"new_rating": "BBB+", "new_status": "WATCH"},
    )

    breach = client.get("/api/v1/breaches").json()[0]
    before = client.get("/api/v1/state").json()["breach_count"]

    response = client.post(
        f"/api/v1/breaches/{breach['id']}/respond",
        json={
            "response": "HOLD_TO_MATURITY",
            "reason": "Matures inside the quarter.",
        },
    )
    assert response.status_code == 200
    assert response.json()["cleared"] is False

    after = client.get("/api/v1/state").json()
    assert after["breach_count"] == before, (
        "The position is still outside policy. A count that fell would say the "
        "problem had gone away when only the conversation had."
    )
    assert any(row["has_open_breach"] for row in after["book"])


def test_an_unknown_rating_is_refused_rather_than_guessed(client):
    response = client.post(
        "/api/v1/counterparties/cp_northern/rating",
        json={"new_rating": "ZZ", "new_status": "STABLE"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNKNOWN_RATING"


def test_the_superseded_limit_survives_the_downgrade(client):
    client.post(
        "/api/v1/counterparties/cp_northern/rating",
        json={"new_rating": "BBB+", "new_status": "WATCH"},
    )
    limits = client.get("/api/v1/counterparties/cp_northern/limits").json()
    assert len(limits) == 2
    current = [limit for limit in limits if limit["superseded_at"] is None]
    assert len(current) == 1
    assert current[0]["amount_pence"] == 8_000_000 * P


# ==========================================================================
# Onboarding
# ==========================================================================


def test_onboarding_is_four_separately_refusable_steps(client):
    created = client.post(
        "/api/v1/counterparties",
        json={"name": "Sterling Union Bank"},
    )
    assert created.status_code == 201
    cp_id = created.json()["counterparty_id"]
    assert created.json()["status"] == "DRAFT"

    # Cannot activate a draft.
    assert (
        client.post(
            f"/api/v1/counterparties/{cp_id}/activate", json={}
        ).status_code
        == 409
    )

    verified = client.post(
        f"/api/v1/counterparties/{cp_id}/verify",
        json={
            "legal_entity_identifier": "213800STERLING000001",
            "group_parent_name": "Sterling Union Holdings plc",
            "rating": "A",
            "country": "GB",
            "instruments": ["DEPOSIT"],
        },
    )
    assert verified.status_code == 200
    assert verified.json()["proposed_limit_pence"] == 18_000_000 * P

    limit = client.post(
        f"/api/v1/counterparties/{cp_id}/limit",
        json={
            "amount_pence": 10_000_000 * P,
            "max_tenor_months": 12,
            "approved_by": "Head of Treasury",
        },
    )
    assert limit.status_code == 201

    activated = client.post(
        f"/api/v1/counterparties/{cp_id}/activate", json={}
    )
    assert activated.status_code == 200
    assert activated.json()["status"] == "ACTIVE"

    assert any(row["counterparty_id"] == cp_id for row in client.get("/api/v1/state").json()["book"])


def test_a_limit_nobody_signed_is_refused(client):
    created = client.post(
        "/api/v1/counterparties", json={"name": "Nowhere Bank"}
    ).json()
    client.post(
        f"/api/v1/counterparties/{created['counterparty_id']}/verify",
        json={
            "legal_entity_identifier": "213800NOWHERE0000001",
            "group_parent_name": "Nowhere Holdings",
            "rating": "A",
            "country": "GB",
            "instruments": ["DEPOSIT"],
        },
    )
    response = client.post(
        f"/api/v1/counterparties/{created['counterparty_id']}/limit",
        json={"amount_pence": 100 * P, "max_tenor_months": 3, "approved_by": "   "},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "APPROVER_REQUIRED"


def test_a_limit_above_the_band_needs_a_reason(client):
    """The seeded book has exactly one of these, and it is the reason the
    book opens with nothing in breach."""
    created = client.post(
        "/api/v1/counterparties", json={"name": "Above Band Bank"}
    ).json()
    cp_id = created["counterparty_id"]
    client.post(
        f"/api/v1/counterparties/{cp_id}/verify",
        json={
            "legal_entity_identifier": "213800ABOVEBAND00001",
            "group_parent_name": "Above Band Holdings",
            "rating": "BBB+",
            "country": "GB",
            "instruments": ["DEPOSIT"],
        },
    )
    refused = client.post(
        f"/api/v1/counterparties/{cp_id}/limit",
        json={
            "amount_pence": 20_000_000 * P,
            "max_tenor_months": 3,
            "approved_by": "Group CFO",
        },
    )
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "LIMIT_REASON_REQUIRED"

    allowed = client.post(
        f"/api/v1/counterparties/{cp_id}/limit",
        json={
            "amount_pence": 20_000_000 * P,
            "max_tenor_months": 3,
            "approved_by": "Group CFO",
            "reason": "Parent guarantee in place.",
        },
    )
    assert allowed.status_code == 201
    assert allowed.json()["source"] == "MANUAL"


# ==========================================================================
# The state call
# ==========================================================================


def test_the_state_call_opens_the_book_with_nothing_in_breach(client):
    body = client.get("/api/v1/state").json()

    assert len(body["book"]) == 9
    assert len(body["deals"]) == 4
    assert body["breach_count"] == 0
    assert body["queue_counts"] == {
        "total": 0,
        "limit_failures": 0,
        "confirmation_mismatches": 0,
    }
    assert round(body["portfolio_total_pence"] / 100) == 50_633_699
    assert body["uninvested_cash_pence"] == 8_000_000 * P
    for row in body["book"]:
        assert row["used_pence"] <= row["limit_pence"]


def test_the_blotter_carries_the_measurement_basis(client):
    deals = client.get("/api/v1/state").json()["deals"]
    forward = next(d for d in deals if d["instrument"] == "FX_FORWARD")
    assert forward["measured_pence"] < forward["principal_pence"]
    assert "add on to notional" in forward["measurement_basis"]


def test_a_healthy_row_carries_no_flag(client):
    for deal in client.get("/api/v1/state").json()["deals"]:
        assert deal["flag"] is None


def test_moving_the_clock_moves_every_derived_figure(client):
    """Everything derives from the clock."""
    before = client.get("/api/v1/state").json()

    client.post("/api/v1/admin/clock", json={"today_date": "2026-12-03"})
    after = client.get("/api/v1/state").json()

    assert after["as_of_date"] == "2026-12-03"
    assert after["portfolio_total_pence"] > before["portfolio_total_pence"], (
        "Three more months of accrued interest is three more months of exposure."
    )


def test_reset_puts_the_book_back(client):
    _record(client, "cp_northern", 10_000_000 * P, 6)
    assert client.get("/api/v1/queue").json() != []

    # The reset endpoint now returns the fresh state directly, which
    # cuts a round trip out of the demo Reset flow. The assertion is
    # the same but reads it from the reset response rather than a
    # follow-up state call.
    body = client.post("/api/v1/admin/reset").json()
    assert body["queue_counts"]["total"] == 0
    assert len(body["deals"]) == 4


# ==========================================================================
# The journey. Section 12 of document 3, automated.
# ==========================================================================


def test_the_demonstration_run_sheet(client, signer):
    """Fourteen clicks, two amounts typed, no page loads.

    Every assertion below is a line the presenter says out loud.
    """
    # 0:00  Nine counterparties, four live deals. Every figure computed.
    state = client.get("/api/v1/state").json()
    assert len(state["book"]) == 9
    assert len(state["deals"]) == 4
    assert state["breach_count"] == 0

    # 1:25  Type 10,000,000, choose Northern Bank plc.
    #       Five green, one red. Nothing on this screen said these two names
    #       were the same credit. Check four is the only thing that did.
    typed = client.post(
        "/api/v1/deals/check",
        json={
            "counterparty_id": "cp_northern",
            "instrument": "DEPOSIT",
            "principal_pence": 10_000_000 * P,
            "tenor_months": 6,
            "rate_bp": 425,
        },
    ).json()
    assert [c["passed"] for c in typed["checks"]].count(True) == 5
    assert outcome(typed, "GROUP_LIMIT")["passed"] is False

    # 2:00  Press Resize to £6,880,164. Green while you watch.
    resize_to = outcome(typed, "GROUP_LIMIT")["resize_to_pence"]
    assert round(resize_to / 100) == 6_880_164

    resized = client.post(
        "/api/v1/deals/check",
        json={
            "counterparty_id": "cp_northern",
            "instrument": "DEPOSIT",
            "principal_pence": resize_to,
            "tenor_months": 6,
            "rate_bp": 425,
        },
    ).json()
    assert resized["outcome"] == "PASS"
    assert resized["required_approver"] == "HEAD_OF_TREASURY"

    # 2:10  Record deal. Booked.
    booked = client.post(
        "/api/v1/deals",
        json={
            "counterparty_id": "cp_northern",
            "instrument": "DEPOSIT",
            "principal_pence": resize_to,
            "tenor_months": 6,
            "rate_bp": 425,
        },
    ).json()
    assert booked["deal"]["status"] == "PROPOSED"
    deal_id = booked["deal"]["id"]

    signed = signer.post(
        f"/api/v1/deals/{deal_id}/approve",
        json={"role": "HEAD_OF_TREASURY"},
    ).json()
    assert signed["status"] == "ACTIVE"

    # The group lands at exactly its limit.
    row = _book_row(client, "cp_northern")
    assert row["group_used_pence"] == row["group_limit_pence"]
    assert row["group_utilisation_bp"] == 10000

    # 3:15  Ratings and policy, Northern Bank plc, BBB+, apply.
    #       The limit drops, the book is re-tested, and something that was
    #       compliant when it was booked is now not.
    action = client.post(
        "/api/v1/counterparties/cp_northern/rating",
        json={"new_rating": "BBB+", "new_status": "WATCH"},
    ).json()
    assert action["new_limit_pence"] == 8_000_000 * P
    assert action["new_max_tenor_months"] == 3
    assert action["breaches_raised"] >= 1

    # 3:50  The amount is still inside the new limit. It is the term that
    #       broke. Amount and duration are two independent constraints.
    breach = next(
        b for b in client.get("/api/v1/breaches").json() if b["deal_id"] == deal_id
    )
    assert breach["type"] == "TENOR"

    after = client.get("/api/v1/state").json()
    assert after["breach_count"] >= 1
    row = _book_row(client, "cp_northern")
    assert row["has_open_breach"] is True
    assert row["rating"] == "BBB+"
    assert row["rating_status"] == "WATCH"
    assert row["limit_pence"] == 8_000_000 * P
    assert row["used_pence"] < row["limit_pence"]

    # 4:05  Show the check it passed. The six checks as they stood on the
    #       day, the limit in force, and the name that signed it.
    assert breach["original_check_run_id"] is not None

    flagged = next(d for d in after["deals"] if d["id"] == deal_id)
    assert flagged["flag"] == "breach"


# -- helpers ---------------------------------------------------------------


def _book_row(client, counterparty_id: str) -> dict:
    return next(
        row
        for row in client.get("/api/v1/state").json()["book"]
        if row["counterparty_id"] == counterparty_id
    )


def _entity_used(client, counterparty_id: str) -> int:
    return _book_row(client, counterparty_id)["used_pence"]


def _group_used(client, counterparty_id: str) -> int:
    return _book_row(client, counterparty_id)["group_used_pence"]
