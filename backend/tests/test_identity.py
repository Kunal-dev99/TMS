"""Phase 1.5. The exit criteria, as tests.

Document 5 section 6 sets three:

    No endpoint accepts an actor in a request body.
    A user cannot approve a deal they proposed.
    Every evidence record names a user identifier rather than typed text.

Document 4 section 10 says why it is a gate rather than a task inside phase
two: with the advisory layer added, the same person could accept a
recommendation and then approve the deal it produced, which is the same hole
twice.
"""

import inspect

from app.schemas import requests as rq

P = 100

#: Names a request body must never carry again.
ACTOR_FIELDS = {
    "created_by",
    "instructed_by",
    "verified_by",
    "activated_by",
    "recorded_by",
    "resolved_by",
    "responded_by",
    "raised_by",
    "settled_by",
    "who",
}


# ==========================================================================
# Exit criterion 1. No endpoint accepts an actor in a request body.
# ==========================================================================


def test_no_request_body_carries_an_actor():
    """Checked against every model in the module rather than a list, so a
    body added later cannot quietly reintroduce one."""
    offenders = []
    for name, model in vars(rq).items():
        if not inspect.isclass(model) or not issubclass(model, rq.BaseModel):
            continue
        if model is rq.BaseModel:
            continue
        for field in model.model_fields:
            if field in ACTOR_FIELDS:
                offenders.append(f"{name}.{field}")
    assert offenders == [], f"actor fields are back: {offenders}"


def test_approved_by_survives_only_where_it_is_not_an_actor():
    """A limit records who signed for it, which can be somebody other than
    whoever keyed it. That is an approver, not a caller, and the caller is
    recorded separately."""
    assert "approved_by" in rq.SetLimitRequest.model_fields
    assert "approved_by" not in rq.ApproveDealRequest.model_fields
    assert "approved_by" not in rq.CreateDealRequest.model_fields


def test_every_endpoint_except_signing_in_needs_a_token(anonymous):
    """The surface reads state before anything else, so if this leaks
    anywhere it leaks everywhere."""
    for method, path in [
        ("GET", "/api/v1/state"),
        ("GET", "/api/v1/policy"),
        ("GET", "/api/v1/queue"),
        ("GET", "/api/v1/breaches"),
        ("GET", "/api/v1/deals"),
        ("GET", "/api/v1/exposure/counterparty"),
        ("GET", "/api/v1/instructions"),
        ("POST", "/api/v1/deals/check"),
        ("POST", "/api/v1/deals"),
        ("POST", "/api/v1/admin/reset"),
    ]:
        response = anonymous.request(method, path, json={})
        assert response.status_code == 401, f"{method} {path} answered without a token"
        assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


def test_a_forged_token_is_refused(anonymous):
    anonymous.headers.update({"Authorization": "Bearer not.a.token"})
    assert anonymous.get("/api/v1/state").status_code == 401


def test_a_tampered_token_is_refused(anonymous):
    """The payload is base64, so it is readable and editable. The signature
    is what makes editing it useless."""
    from app.security import issue_token

    token = issue_token("usr_whitfield", "ten_demo")
    body, signature = token.split(".")
    forged = f"{body}x.{signature}"

    anonymous.headers.update({"Authorization": f"Bearer {forged}"})
    assert anonymous.get("/api/v1/state").status_code == 401


def test_an_expired_token_is_refused(anonymous):
    from app.security import issue_token

    expired = issue_token("usr_whitfield", "ten_demo", ttl_seconds=-1)
    anonymous.headers.update({"Authorization": f"Bearer {expired}"})
    assert anonymous.get("/api/v1/state").status_code == 401


def test_a_wrong_password_is_refused_the_same_way_as_a_wrong_address(anonymous):
    """Saying which of the two was wrong tells somebody who is guessing which
    half they already have."""
    wrong_password = anonymous.post(
        "/api/v1/auth/token",
        json={"email": "a.whitfield@northgate.example", "password": "nope"},
    )
    wrong_address = anonymous.post(
        "/api/v1/auth/token",
        json={"email": "nobody@northgate.example", "password": "treasury"},
    )
    assert wrong_password.status_code == wrong_address.status_code == 401
    assert wrong_password.json() == wrong_address.json()


def test_signing_in_returns_a_token_and_the_roles_held(anonymous):
    response = anonymous.post(
        "/api/v1/auth/token",
        json={"email": "m.doran@northgate.example", "password": "treasury"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token"]
    assert body["user"]["display_name"] == "M. Doran"
    assert "HEAD_OF_TREASURY" in body["user"]["roles"]


def test_the_token_says_who_is_calling(client):
    body = client.get("/api/v1/auth/me").json()
    assert body["display_name"] == "A. Whitfield"
    assert body["roles"] == ["ANALYST"]


# ==========================================================================
# Exit criterion 2. A user cannot approve a deal they proposed.
# ==========================================================================


def _propose(client, counterparty_id="cp_meridian", principal_pence=500_000 * P):
    return client.post(
        "/api/v1/deals",
        json={
            "counterparty_id": counterparty_id,
            "instrument": "DEPOSIT",
            "principal_pence": principal_pence,
            "tenor_months": 6,
            "rate_bp": 425,
        },
    ).json()


def test_the_proposer_cannot_sign_their_own_deal(client):
    """The hole document 4 names, closed.

    A. Whitfield holds ANALYST and the amount is inside the analyst
    threshold, so the only thing standing in the way is that she proposed it.
    """
    booked = _propose(client)

    response = client.post(
        f"/api/v1/deals/{booked['deal']['id']}/approve", json={"role": "ANALYST"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SEGREGATION_OF_DUTIES"
    assert "A. Whitfield" in response.json()["error"]["message"]


def test_somebody_else_can_sign_it(client, signer):
    booked = _propose(client)

    response = signer.post(
        f"/api/v1/deals/{booked['deal']['id']}/approve", json={"role": "ANALYST"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ACTIVE"
    assert response.json()["approved_by"] == "M. Doran"


def test_a_signer_must_hold_the_role_they_sign_under(client, cfo):
    """R. Sethi holds CFO and nothing else, so she cannot sign as an
    analyst even though CFO outranks it. The role on the request is a claim
    about what she holds, not a level she may borrow."""
    booked = _propose(client)

    response = cfo.post(
        f"/api/v1/deals/{booked['deal']['id']}/approve", json={"role": "ANALYST"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROLE_NOT_HELD"


def test_a_role_below_the_threshold_cannot_sign(client, signer):
    """The approval router named the CFO. The Head of Treasury holds
    HEAD_OF_TREASURY, which is not enough for this amount."""
    # Meridian has the headroom for this, so the only thing in the way is
    # the threshold. A blocked deal would fail for a different reason and
    # prove nothing about roles.
    booked = _propose(client, "cp_meridian", 12_000_000 * P)
    assert booked["deal"]["status"] == "PROPOSED"
    assert booked["deal"]["required_approver"] == "CFO"

    response = signer.post(
        f"/api/v1/deals/{booked['deal']['id']}/approve",
        json={"role": "HEAD_OF_TREASURY"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROLE_NOT_HELD"
    assert "the cfo to sign" in response.json()["error"]["message"].lower()


def test_the_cfo_can_sign_what_the_head_of_treasury_cannot(client, cfo):
    booked = _propose(client, "cp_meridian", 12_000_000 * P)

    response = cfo.post(
        f"/api/v1/deals/{booked['deal']['id']}/approve", json={"role": "CFO"}
    )
    assert response.status_code == 200


def test_signing_re_runs_the_checks(client, signer):
    """A deal proposed this morning and signed this afternoon has sat outside
    the gate in between. Signing is the moment it goes on the book, so it is
    the moment that has to be true."""
    booked = _propose(client, "cp_northern", 6_000_000 * P)

    # The world moves: Northern Bank is downgraded, and six months is now
    # longer than its rating allows.
    client.post(
        "/api/v1/counterparties/cp_northern/rating",
        json={"new_rating": "BBB+", "new_status": "WATCH"},
    )

    response = signer.post(
        f"/api/v1/deals/{booked['deal']['id']}/approve",
        json={"role": "HEAD_OF_TREASURY"},
    )
    assert response.status_code == 409
    assert "The world moved" in response.json()["error"]["message"]


# ==========================================================================
# Exit criterion 3. Every evidence record names a user identifier.
# ==========================================================================


def test_a_deal_names_the_proposer_and_the_signer_by_identifier(
    client, signer, session
):
    booked = _propose(client)
    signer.post(
        f"/api/v1/deals/{booked['deal']['id']}/approve", json={"role": "ANALYST"}
    )

    from app.repo import deals as deal_repo

    deal = deal_repo.get(session, booked["deal"]["id"])
    assert deal.created_by_user_id == "usr_whitfield"
    assert deal.approved_by_user_id == "usr_doran"
    assert deal.approved_role == "ANALYST"
    assert deal.created_by_user_id != deal.approved_by_user_id


def test_a_check_run_names_who_ran_it_by_identifier(client, session):
    booked = _propose(client)

    from app.repo import evidence as evidence_repo

    run = evidence_repo.get_check_run(session, booked["run"]["check_run_id"])
    assert run.created_by_user_id == "usr_whitfield"
    assert run.created_by == "A. Whitfield"


def test_a_queue_resolution_names_who_resolved_it_by_identifier(client, session):
    booked = _propose(client, "cp_northern", 10_000_000 * P)
    client.post(
        f"/api/v1/queue/{booked['queue_item_id']}/resolve",
        json={"resolution": "RESIZED"},
    )

    from app.repo import evidence as evidence_repo

    item = evidence_repo.get_queue_item(session, booked["queue_item_id"])
    assert item.resolved_by_user_id == "usr_whitfield"


def test_a_rating_event_names_who_recorded_it_by_identifier(client, session):
    client.post(
        "/api/v1/counterparties/cp_northern/rating",
        json={"new_rating": "BBB+", "new_status": "WATCH"},
    )

    from app.models import RatingEvent

    event = session.query(RatingEvent).one()
    assert event.recorded_by_user_id == "usr_whitfield"


def test_a_breach_response_names_who_responded_by_identifier(client, session):
    client.post(
        "/api/v1/counterparties/cp_nts/rating",
        json={"new_rating": "BBB+", "new_status": "WATCH"},
    )
    breach = client.get("/api/v1/breaches").json()[0]
    client.post(
        f"/api/v1/breaches/{breach['id']}/respond",
        json={"response": "HOLD_TO_MATURITY"},
    )

    from app.repo import evidence as evidence_repo

    stored = evidence_repo.get_breach(session, breach["id"])
    assert stored.responded_by_user_id == "usr_whitfield"


def test_an_instruction_names_who_handed_it_over(client, signer, session):
    booked = _propose(client)
    signer.post(
        f"/api/v1/deals/{booked['deal']['id']}/approve", json={"role": "ANALYST"}
    )
    client.post(f"/api/v1/deals/{booked['deal']['id']}/instruct", json={})

    from app.models import OracleInstruction

    instruction = session.query(OracleInstruction).one()
    assert instruction.created_by_user_id == "usr_whitfield"


def test_onboarding_names_the_caller_at_every_step(client, session):
    created = client.post(
        "/api/v1/counterparties", json={"name": "Sterling Union Bank"}
    ).json()
    cp_id = created["counterparty_id"]

    client.post(
        f"/api/v1/counterparties/{cp_id}/verify",
        json={
            "legal_entity_identifier": "213800STERLING000001",
            "group_parent_name": "Sterling Union Holdings plc",
            "rating": "A",
            "country": "GB",
            "instruments": ["DEPOSIT"],
        },
    )
    client.post(
        f"/api/v1/counterparties/{cp_id}/limit",
        json={
            "amount_pence": 10_000_000 * P,
            "max_tenor_months": 12,
            "approved_by": "M. Doran",
        },
    )
    client.post(f"/api/v1/counterparties/{cp_id}/activate", json={})

    from app.repo import counterparties as cp_repo

    counterparty = cp_repo.get(session, cp_id)
    assert counterparty.created_by_user_id == "usr_whitfield"
    assert counterparty.activated_by_user_id == "usr_whitfield"

    limit = cp_repo.current_limit(session, cp_id)
    assert limit.recorded_by_user_id == "usr_whitfield"
    assert limit.approved_by == "M. Doran", (
        "Who signed and who keyed are two different questions."
    )


# ==========================================================================
# Passwords
# ==========================================================================


def test_a_password_is_never_stored_in_the_clear(session):
    from app.models import AppUser

    for user in session.query(AppUser).all():
        assert user.password_hash.startswith("pbkdf2_sha256$")
        assert "treasury" not in user.password_hash


def test_the_same_password_hashes_differently_for_two_people(session):
    from app.models import AppUser

    hashes = {user.password_hash for user in session.query(AppUser).all()}
    assert len(hashes) == 3, "A shared salt would make two identical hashes."
