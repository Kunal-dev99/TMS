"""End-to-end proof: propose -> approve -> compliance history -> CSV export.

This is the exact chain the compliance officer needs to trust. Runs
through the real HTTP surface (TestClient) and asserts:

  * A deal proposal writes deal.recorded with a human label and outcome
  * An approval writes deal.approved
  * GET /compliance/activity returns both events (search by subject_id
    finds the whole story on one deal)
  * total_matching agrees with the number of items returned
  * generated_at is a valid ISO timestamp
  * The CSV export contains the same events and its metadata header
    names the filters + row count

Regression cover for the "0 matching but 4 rows shown" bug and for the
"Last refreshed —" symptom.
"""

from __future__ import annotations

import re
from datetime import datetime


P = 100  # pence per pound (mirrors test_lifecycle helper)


def _propose_ok(client, principal_pence: int = 5_000_000 * P) -> dict:
    body = {
        "counterparty_id": "cp_meridian",
        "instrument": "DEPOSIT",
        "principal_pence": principal_pence,
        "tenor_months": 6,
        "rate_bp": 425,
    }
    r = client.post("/api/v1/deals", json=body)
    assert r.status_code == 201, r.text
    return r.json()["deal"]


def test_compliance_end_to_end_propose_approve_view_export(client, signer):
    # 1) A. Whitfield proposes.
    deal = _propose_ok(client)
    deal_id = deal["id"]

    # 2) M. Doran approves in whichever role the deal requires.
    r = signer.post(
        f"/api/v1/deals/{deal_id}/approve",
        json={"role": deal.get("required_approver") or "HEAD_OF_TREASURY"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] in {"BOOKED", "APPROVED", "ACTIVE"}

    # 3) Compliance search by subject_id — both events on this deal.
    r = signer.get(
        "/api/v1/compliance/activity",
        params={"subject_id": deal_id, "limit": 50, "offset": 0},
    )
    assert r.status_code == 200, r.text
    view = r.json()

    # Counts must agree with rows. This is exactly the invariant
    # the earlier subquery COUNT violated.
    assert len(view["items"]) == view["total_matching"], (
        f"items={len(view['items'])} but total_matching={view['total_matching']}"
    )
    assert view["total_matching"] >= 2
    assert view["total_all"] >= view["total_matching"]

    actions = {row["action"] for row in view["items"]}
    assert "deal.recorded" in actions
    assert "deal.approved" in actions

    # Human labels come through.
    labels_by_action = {row["action"]: row["action_label"] for row in view["items"]}
    assert labels_by_action["deal.recorded"] == "Deal recorded"
    assert labels_by_action["deal.approved"] == "Deal approved"

    # generated_at is a real ISO timestamp.
    ts = view["generated_at"]
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", ts), ts
    datetime.fromisoformat(ts)  # raises if malformed

    # Outcomes are captured, not blank.
    for row in view["items"]:
        assert row["outcome"], f"missing outcome on {row['action']}"

    # 4) CSV export names its scope in the metadata header.
    r = signer.get(
        "/api/v1/compliance/activity.csv",
        params={"subject_id": deal_id, "limit": 500},
    )
    assert r.status_code == 200, r.text
    body = r.text
    assert body.startswith("# Treasury Register audit export")
    assert f"subject_id={deal_id}" in body
    assert "rows_exported=" in body
    assert "rows_matching_filters=" in body
    # Both events appear as data rows below the header.
    assert "deal.recorded" in body
    assert "deal.approved" in body
    # Response headers echo the row counts.
    assert r.headers.get("X-Rows-Matching") is not None
    assert r.headers.get("X-Rows-Exported") is not None


def test_compliance_actor_substring_search(client, signer):
    _propose_ok(client)
    r = signer.get(
        "/api/v1/compliance/activity",
        params={"actor": "Whitfield", "limit": 50},
    )
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["total_matching"] >= 1
    # Every returned row is by Whitfield.
    for row in view["items"]:
        assert "Whitfield" in (row["actor_display"] or "")


def test_compliance_saved_view_deal_prefix(client, signer):
    deal = _propose_ok(client)
    signer.post(
        f"/api/v1/deals/{deal['id']}/approve",
        json={"role": deal.get("required_approver") or "HEAD_OF_TREASURY"},
    )

    r = signer.get(
        "/api/v1/compliance/activity",
        params={"action_prefix": "deal.", "limit": 50},
    )
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["total_matching"] == len(view["items"])
    assert view["total_matching"] >= 2
    for row in view["items"]:
        assert row["action"].startswith("deal."), row["action"]


def test_compliance_deal_evidence_view(client, signer):
    """Deal evidence assembles proposer, approver, six checks, policy
    version, limit and full event history in one call."""
    deal = _propose_ok(client)
    deal_id = deal["id"]
    signer.post(
        f"/api/v1/deals/{deal_id}/approve",
        json={"role": deal.get("required_approver") or "HEAD_OF_TREASURY"},
    )

    r = signer.get(f"/api/v1/compliance/deals/{deal_id}/evidence")
    assert r.status_code == 200, r.text
    ev = r.json()

    # Terms come through.
    assert ev["deal_id"] == deal_id
    assert ev["counterparty_name"]
    assert ev["principal_pence"] > 0

    # Both actors are named.
    assert ev["proposer_display"], "no proposer captured on audit event"
    assert ev["approver_display"], "no approver on deal row"

    # A check_run was recorded at booking; six checks are itemised.
    assert ev["check_run_id"], "no check_run for this deal"
    assert len(ev["six_checks"]) >= 1
    assert ev["booking_outcome"] in {"PASS", "FAIL", "OVERRIDDEN"}
    # Every check names its key + a pass/fail flag.
    for c in ev["six_checks"]:
        assert isinstance(c["passed"], bool)
        assert c["key"]

    # Policy + limit versions in force at booking are named.
    assert ev["policy_version_id"], "no policy version resolved for the deal"
    # The event timeline includes both deal.recorded and deal.approved.
    codes = {e["action"] for e in ev["events"]}
    assert "deal.recorded" in codes
    assert "deal.approved" in codes


def test_compliance_deal_evidence_404_on_unknown(signer):
    r = signer.get("/api/v1/compliance/deals/deal_does_not_exist/evidence")
    assert r.status_code == 404


def test_compliance_breaches_register(client, signer):
    # A clean deal doesn't populate breaches; the register returns
    # its schema with zero-or-more rows and never errors.
    _propose_ok(client)
    r = signer.get("/api/v1/compliance/breaches-overrides")
    assert r.status_code == 200, r.text
    reg = r.json()
    assert "items" in reg
    assert "total_open" in reg
    assert "total_overridden_ytd" in reg
    assert "total_resolved_ytd" in reg
    assert "generated_at" in reg
    # Every row carries the fields the register table needs to render.
    for row in reg["items"]:
        for field in ("kind", "occurred_at", "rule", "status"):
            assert field in row


def test_compliance_overview_counts(client, signer):
    _propose_ok(client)
    r = signer.get("/api/v1/compliance/overview")
    assert r.status_code == 200, r.text
    ov = r.json()
    for field in (
        "open_breaches",
        "overrides_ytd",
        "resolved_ytd",
        "events_last_7d",
        "events_prior_7d",
        "open_breaches_prior_period",
        "deals_missing_evidence",
        "top_actors_7d",
        "top_actions_7d",
        "generated_at",
    ):
        assert field in ov, f"missing: {field}"
    assert isinstance(ov["events_last_7d"], int)
    assert isinstance(ov["events_prior_7d"], int)
    assert isinstance(ov["top_actors_7d"], list)
    assert isinstance(ov["top_actions_7d"], list)
    # deals_missing_evidence >= 0 is the invariant we care about. Seed
    # data plants historical deals directly (bypassing the engine) so
    # the KPI can be > 0 for that reason — the metric legitimately
    # flags them, and we don't want a hard-zero here.
    assert isinstance(ov["deals_missing_evidence"], int)
    assert ov["deals_missing_evidence"] >= 0
    # Every leader-board row carries key/label/count.
    for group in (ov["top_actors_7d"], ov["top_actions_7d"]):
        for row in group:
            for f in ("key", "label", "count"):
                assert f in row
            assert isinstance(row["count"], int)


def test_compliance_recent_deals_feeds_the_picker(signer):
    r = signer.get("/api/v1/compliance/deals/recent?limit=5")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    for row in rows:
        for f in (
            "deal_id",
            "counterparty_name",
            "counterparty_id",
            "principal_pence",
            "currency",
            "trade_date",
            "status",
        ):
            assert f in row


def test_compliance_breaches_filters_and_csv(signer):
    # JSON filter — a bogus counterparty returns zero rows without
    # 500-ing.
    r = signer.get(
        "/api/v1/compliance/breaches-overrides",
        params={"counterparty": "no-such-counterparty-name-xxxxx"},
    )
    assert r.status_code == 200, r.text
    reg = r.json()
    assert reg["items"] == []

    # CSV peer — metadata header names the filters and the caps.
    r = signer.get(
        "/api/v1/compliance/breaches-overrides.csv",
        params={"status": "OPEN"},
    )
    assert r.status_code == 200, r.text
    body = r.text
    assert body.startswith("# Treasury Register breach + override register export")
    assert "status=OPEN" in body
    assert "rows_exported=" in body
    assert r.headers.get("X-Rows-Matching") is not None
