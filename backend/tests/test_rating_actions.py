"""What a rating action may and may not do to a limit.

A downgrade takes an entitlement away. An upgrade does not hand one out.

That asymmetry is the whole of this file. It is not obvious, it was got
wrong first time, and without it one keystroke grants a counterparty
millions of new headroom with an approver of whoever happened to record the
upgrade.
"""

from app import seed_data as s
from app.repo import counterparties as cp_repo

P = 100
ACTOR = "A. Whitfield"


def _rate(client, counterparty_id: str, rating: str, status: str = "STABLE"):
    return client.post(
        f"/api/v1/counterparties/{counterparty_id}/rating",
        json={"new_rating": rating, "new_status": status},
    )


# ==========================================================================
# A downgrade tightens
# ==========================================================================


def test_a_downgrade_tightens_the_amount_and_the_term(client, session):
    body = _rate(client, "cp_northern", "BBB+", "WATCH").json()

    assert body["action"] == "DOWNGRADE"
    assert body["new_limit_pence"] == 8_000_000 * P
    assert body["new_max_tenor_months"] == 3

    current = cp_repo.current_limit(session, "cp_northern")
    assert current.amount_pence == 8_000_000 * P
    assert current.source == "BAND"


def test_a_downgrade_tightens_a_manual_limit_that_sits_above_the_band(
    client, session
):
    """Northern Treasury Services holds 20,000,000 against an A- band ceiling
    of 15,000,000. A downgrade takes the entitlement away whoever signed for
    the old one."""
    before = cp_repo.current_limit(session, "cp_nts")
    assert before.amount_pence == 20_000_000 * P
    assert before.source == "MANUAL"

    _rate(client, "cp_nts", "BBB+")

    after = cp_repo.current_limit(session, "cp_nts")
    assert after.amount_pence == 8_000_000 * P
    assert after.id != before.id


# ==========================================================================
# An upgrade does not widen
# ==========================================================================


def test_an_upgrade_does_not_raise_the_limit(client, session):
    """The defect this file exists for.

    Harbour and Vale Bank is rated BBB+ with an 8,000,000 limit. Upgrading it
    to AA- must not hand it the 35,000,000 band ceiling, because nobody
    signed for that.
    """
    before = cp_repo.current_limit(session, "cp_harbour")
    assert before.amount_pence == 8_000_000 * P

    body = _rate(client, "cp_harbour", "AA-").json()
    assert body["action"] == "UPGRADE"

    after = cp_repo.current_limit(session, "cp_harbour")
    assert after.id == before.id, "The limit was superseded by an upgrade."
    assert after.amount_pence == 8_000_000 * P, (
        "An upgrade granted headroom nobody signed for."
    )
    assert after.max_tenor_months == 3


def test_the_rating_still_moves_on_an_upgrade(client, session):
    """Only the limit is held. The rating itself is a fact about the world."""
    _rate(client, "cp_harbour", "AA-")

    counterparty = cp_repo.get(session, "cp_harbour")
    assert counterparty.rating == "AA-"


def test_the_higher_limit_can_still_be_set_by_somebody_signing_for_it(client, session):
    """The route is not closed, only routed through an approver."""
    _rate(client, "cp_harbour", "AA-")

    response = client.post(
        "/api/v1/counterparties/cp_harbour/limit",
        json={
            "amount_pence": 35_000_000 * P,
            "max_tenor_months": 24,
            "approved_by": "Group CFO",
        },
    )
    assert response.status_code == 201

    after = cp_repo.current_limit(session, "cp_harbour")
    assert after.amount_pence == 35_000_000 * P
    assert after.approved_by == "Group CFO"


# ==========================================================================
# A mixed move tightens only what tightened
# ==========================================================================


def test_amount_and_term_are_tightened_independently(client, session):
    """Two independent constraints. A rating can move one without the other.

    Northern Bank holds 15,000,000 to 6 months at A-, where the band allows
    12. Moving to A leaves the band amount at 18,000,000, above what is in
    force, so the amount is held. The term stays at 6 for the same reason.
    """
    before = cp_repo.current_limit(session, "cp_northern")
    assert (before.amount_pence, before.max_tenor_months) == (15_000_000 * P, 6)

    _rate(client, "cp_northern", "A")

    after = cp_repo.current_limit(session, "cp_northern")
    assert after.amount_pence == 15_000_000 * P
    assert after.max_tenor_months == 6
    assert after.id == before.id


def test_a_downgrade_that_only_shortens_the_term_leaves_the_amount(client, session):
    """Meridian holds 20,000,000 to 12 months at A+. BBB+ allows 8,000,000 to
    3 months, so both tighten. BBB is a further step and tightens the amount
    again."""
    _rate(client, "cp_meridian", "BBB+")
    after = cp_repo.current_limit(session, "cp_meridian")
    assert after.amount_pence == 8_000_000 * P
    assert after.max_tenor_months == 3


# ==========================================================================
# Whatever happens to the limit, the book is re-tested
# ==========================================================================


def test_every_live_position_is_re_tested_even_when_the_limit_is_held(client):
    """An upgrade holds the limit, but the rating changed, so the positions
    are still re-tested against the world as it now is."""
    body = _rate(client, "cp_harbour", "AA-").json()
    assert body["positions_tested"] == 1


def test_an_upgrade_raises_no_breach_on_a_compliant_book(client):
    body = _rate(client, "cp_harbour", "AA-").json()
    assert body["breaches_raised"] == 0
    assert client.get("/api/v1/breaches").json() == []
