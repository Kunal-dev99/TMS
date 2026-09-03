"""Phase 3. Currency exposure and hedging.

Document 5's fourth exit criterion for the phase:

    Coverage moves backwards without an error when an exposure date slips.

That one sentence carries the idea the whole subject area rests on. A
covered exposure becoming partially covered is not a defect and not a
mistake. Nobody did anything wrong; the world moved, and the model has to
allow the status to go back.

The rest of this file is document 4's separation rule, which is a review
item rather than a test item. It is tested anyway, because "no query joins
them" is exactly the kind of rule that holds until somebody is in a hurry.
"""

import inspect

from app import seed_data as s

P = 100
EUR = 100  # minor units in a euro


def _exposure(client, amount=4_000_000 * EUR, direction="PAYABLE", **overrides):
    body = {
        "currency": "EUR",
        "amount_minor": amount,
        "direction": direction,
        "expected_date": s.months_after(s.CLOCK_DATE, 2),
        "source": "PURCHASE_ORDER",
        "source_reference": "PO-2026-4471",
    }
    body.update(overrides)
    return client.post("/api/v1/currency-exposures", json=body).json()


# ==========================================================================
# The register
# ==========================================================================


def test_an_obligation_exists_before_any_hedge(client):
    """It exists before any hedge and often outlives several of them."""
    exposure = _exposure(client)
    assert exposure["status"] == "IDENTIFIED"
    assert exposure["currency"] == "EUR"
    assert exposure["amount_minor"] == 4_000_000 * EUR


def test_every_figure_carries_its_currency(client):
    """There is no default currency on this table. Minor units, and the
    suffix says so."""
    _exposure(client)
    view = client.get("/api/v1/exposure/currency?currency=EUR").json()

    assert view["currency"] == "EUR"
    for row in view["exposures"]:
        assert row["currency"] == "EUR"
        assert "amount_minor" in row
        assert "amount_pence" not in row


def test_inflows_offset_outflows(client):
    """Hedging the gross is buying cover you do not need."""
    _exposure(client, amount=4_000_000 * EUR, direction="PAYABLE")
    _exposure(
        client,
        amount=1_000_000 * EUR,
        direction="RECEIVABLE",
        source_reference="INV-9",
    )

    view = client.get("/api/v1/exposure/currency?currency=EUR").json()
    # Both fall in the same bucket, whichever that is: the point is that the
    # inflow was netted against the outflow rather than added to it.
    net = sum(bucket["net_minor"] for bucket in view["buckets"])
    assert net == 3_000_000 * EUR


# ==========================================================================
# The link is what makes it hedging
# ==========================================================================


def test_only_a_forward_can_cover_an_obligation(client):
    """A deposit does not deliver currency on a date, so linking one would
    say something is covered when nothing is."""
    exposure = _exposure(client)
    response = client.post(
        f"/api/v1/currency-exposures/{exposure['id']}/hedges",
        json={"deal_id": "dl_nts_001", "covered_amount_minor": 1_000_000 * EUR},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NOT_AN_FX_FORWARD"


def test_a_link_that_would_over_cover_is_refused_with_the_amounts(client):
    """Document 1 lists this as an invariant the schema cannot hold, because
    it is a sum across rows."""
    exposure = _exposure(client, amount=4_000_000 * EUR)
    response = client.post(
        f"/api/v1/currency-exposures/{exposure['id']}/hedges",
        json={"deal_id": "dl_har_001", "covered_amount_minor": 4_600_000 * EUR},
    )
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "HEDGE_EXCEEDS_EXPOSURE"
    assert "4,600,000" in body["message"]
    assert "4,000,000" in body["message"]


def test_linking_moves_the_status_to_partially_covered(client):
    exposure = _exposure(client, amount=4_000_000 * EUR)
    linked = client.post(
        f"/api/v1/currency-exposures/{exposure['id']}/hedges",
        json={"deal_id": "dl_har_001", "covered_amount_minor": 3_000_000 * EUR},
    ).json()

    assert linked["status"] == "PARTIALLY_COVERED"
    assert linked["covered_amount_minor"] == 3_000_000 * EUR


def test_covering_the_whole_obligation_moves_it_to_covered(client):
    exposure = _exposure(client, amount=3_000_000 * EUR)
    linked = client.post(
        f"/api/v1/currency-exposures/{exposure['id']}/hedges",
        json={"deal_id": "dl_har_001", "covered_amount_minor": 3_000_000 * EUR},
    ).json()
    assert linked["status"] == "COVERED"


def test_the_hedge_appears_under_the_exposure_it_covers(client):
    """Without the link you own forwards and cannot say anything is
    covered."""
    exposure = _exposure(client)
    client.post(
        f"/api/v1/currency-exposures/{exposure['id']}/hedges",
        json={"deal_id": "dl_har_001", "covered_amount_minor": 3_000_000 * EUR},
    )

    view = client.get("/api/v1/exposure/currency?currency=EUR").json()
    row = next(r for r in view["exposures"] if r["id"] == exposure["id"])
    assert len(row["hedges"]) == 1
    assert row["hedges"][0]["deal_id"] == "dl_har_001"
    assert row["hedges"][0]["currency"] == "EUR"


# ==========================================================================
# Exit criterion. Coverage moves backwards without an error.
# ==========================================================================


def test_coverage_moves_backwards_when_a_link_is_broken(client):
    """The exit criterion.

    A covered exposure becoming partially covered when a delivery slips is
    correct behaviour, not a defect. Nobody made a mistake. The world moved.
    """
    exposure = _exposure(client, amount=4_000_000 * EUR)

    first = client.post(
        f"/api/v1/currency-exposures/{exposure['id']}/hedges",
        json={"deal_id": "dl_har_001", "covered_amount_minor": 2_000_000 * EUR},
    ).json()
    second = client.post(
        f"/api/v1/currency-exposures/{exposure['id']}/hedges",
        json={"deal_id": "dl_har_001", "covered_amount_minor": 2_000_000 * EUR},
    ).json()
    assert second["status"] == "COVERED"

    unlinked = client.post(
        f"/api/v1/hedge-links/{first['hedge_link_id']}/unlink",
        json={"reason": "ROLLED"},
    )

    assert unlinked.status_code == 200, "Coverage moving backwards was an error."
    body = unlinked.json()
    assert body["status"] == "PARTIALLY_COVERED"
    assert body["covered_amount_minor"] == 2_000_000 * EUR


def test_unlinking_every_hedge_returns_it_to_identified(client):
    exposure = _exposure(client, amount=2_000_000 * EUR)
    link = client.post(
        f"/api/v1/currency-exposures/{exposure['id']}/hedges",
        json={"deal_id": "dl_har_001", "covered_amount_minor": 2_000_000 * EUR},
    ).json()

    body = client.post(
        f"/api/v1/hedge-links/{link['hedge_link_id']}/unlink",
        json={"reason": "EXPOSURE_CANCELLED"},
    ).json()
    assert body["status"] == "IDENTIFIED"


def test_unlinking_requires_a_reason(client):
    exposure = _exposure(client)
    link = client.post(
        f"/api/v1/currency-exposures/{exposure['id']}/hedges",
        json={"deal_id": "dl_har_001", "covered_amount_minor": 1_000_000 * EUR},
    ).json()

    response = client.post(
        f"/api/v1/hedge-links/{link['hedge_link_id']}/unlink", json={}
    )
    assert response.status_code == 422


def test_a_link_cannot_be_broken_twice(client):
    exposure = _exposure(client)
    link = client.post(
        f"/api/v1/currency-exposures/{exposure['id']}/hedges",
        json={"deal_id": "dl_har_001", "covered_amount_minor": 1_000_000 * EUR},
    ).json()
    payload = {"reason": "ROLLED"}

    assert (
        client.post(
            f"/api/v1/hedge-links/{link['hedge_link_id']}/unlink", json=payload
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/hedge-links/{link['hedge_link_id']}/unlink", json=payload
        ).status_code
        == 409
    )


def test_a_broken_link_frees_the_amount_for_another_hedge(client):
    """Coverage is recomputed rather than remembered, so the freed amount is
    available again without anything having to reset it."""
    exposure = _exposure(client, amount=3_000_000 * EUR)
    link = client.post(
        f"/api/v1/currency-exposures/{exposure['id']}/hedges",
        json={"deal_id": "dl_har_001", "covered_amount_minor": 3_000_000 * EUR},
    ).json()
    client.post(
        f"/api/v1/hedge-links/{link['hedge_link_id']}/unlink",
        json={"reason": "REALLOCATED"},
    )

    again = client.post(
        f"/api/v1/currency-exposures/{exposure['id']}/hedges",
        json={"deal_id": "dl_har_001", "covered_amount_minor": 3_000_000 * EUR},
    )
    assert again.status_code == 201


# ==========================================================================
# Coverage against the policy target
# ==========================================================================


def test_coverage_is_measured_against_the_policy_target(client):
    """80 per cent for the euro, from the currency cover target in the
    investment policy."""
    _exposure(client, amount=4_000_000 * EUR)
    client.post(
        "/api/v1/currency-exposures/"
        + client.get("/api/v1/exposure/currency?currency=EUR").json()["exposures"][0][
            "id"
        ]
        + "/hedges",
        json={"deal_id": "dl_har_001", "covered_amount_minor": 3_200_000 * EUR},
    )

    view = client.get("/api/v1/exposure/currency?currency=EUR").json()
    bucket = next(b for b in view["buckets"] if b["net_minor"] > 0)
    assert bucket["target_cover_bp"] == 8000
    assert bucket["covered_bp"] == 8000


def test_the_view_carries_the_warning_in_the_interface(client):
    """The warning is in the interface rather than only in the
    documentation, because the interface is where somebody would try it."""
    view = client.get("/api/v1/exposure/currency").json()
    assert "never netted" in view["warning"]
    assert "opposite directions" in view["warning"]


# ==========================================================================
# The separation rule. A review item, tested anyway.
# ==========================================================================


def test_there_is_no_endpoint_that_returns_both_exposures(client):
    """Making a combined figure impossible to ask for is cheaper than
    documenting that it should not be asked for."""
    from app.main import app

    paths = {r.path for r in app.routes if hasattr(r, "methods")}
    assert "/api/v1/exposure" not in paths
    assert "/api/v1/exposure/counterparty" in paths
    assert "/api/v1/exposure/currency" in paths


def test_currency_exposure_has_no_counterparty(client):
    """An obligation to a supplier is not an obligation to a bank, and there
    is no key that would let the two be joined."""
    from app.models import CurrencyExposure

    columns = set(CurrencyExposure.__table__.columns.keys())
    assert "counterparty_id" not in columns
    assert "amount_pence" not in columns
    assert "amount_minor" in columns


def test_the_two_exposures_never_share_a_unit(client):
    counterparty = client.get("/api/v1/exposure/counterparty").json()
    currency = client.get("/api/v1/exposure/currency").json()

    assert "portfolio_total_pence" in counterparty
    assert not any("minor" in key for key in counterparty)
    assert not any(key.endswith("_pence") for key in currency)


def test_the_hedge_service_never_reads_counterparty_exposure(client):
    """A forward increases one and reduces the other. A file that read both
    would be one refactor away from netting them."""
    from app.services import hedge_service

    source = inspect.getsource(hedge_service)
    for forbidden in ("ExposureCalculator", "ExposureService", "portfolio_total"):
        assert forbidden not in source, f"hedge_service reads {forbidden}"


def test_a_forward_is_an_ordinary_deal_on_both_sides(client):
    """It increases counterparty exposure and reduces currency exposure, and
    it is one row in the deal table either way. That is why there is no
    separate hedge table."""
    exposure = _exposure(client, amount=3_000_000 * EUR)
    client.post(
        f"/api/v1/currency-exposures/{exposure['id']}/hedges",
        json={"deal_id": "dl_har_001", "covered_amount_minor": 3_000_000 * EUR},
    )

    counterparty = client.get("/api/v1/exposure/counterparty").json()
    harbour = next(
        row for row in counterparty["by_group"] if row["key"] == "grp_harbour"
    )
    assert harbour["used_pence"] == 300_000 * P, (
        "The forward still counts against the counterparty, measured at the "
        "add on rather than its notional."
    )
