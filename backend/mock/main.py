"""The mock server.

All forty-four endpoints of document 2, answering from fixtures built out of
the seed. The frontend builds against this from day three of phase zero and
does not wait for a single service to exist.

It is not throwaway. It stays after the real API replaces it, as the fixture
source for the frontend test suite, and the contract tests in phase one run
against both and require identical shapes. That is what catches a drift
before the frontend sees it.

It holds no rules. See mock/fixtures.py for the one marked comparison that
picks between two prepared check fixtures.

    uvicorn mock.main:app --port 8001
"""

from fastapi import APIRouter, FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse

from app import seed_data as s
from app.errors import CATALOGUE, ErrorCode
from app.schemas import requests as rq
from app.schemas.models import (
    AdvisoryRun,
    BreachView,
    CheckResult,
    ConfirmationSummary,
    CurrencyExposureView,
    DealDetail,
    DealSummary,
    ExposureView,
    LimitVersion,
    PolicyConfig,
    QueueItem,
    StateResponse,
)
from mock import fixtures as fx

app = FastAPI(
    title="Treasury Register, mock",
    version="0.1.0",
    description=(
        "Fixtures for every endpoint in document 2, generated from the seed. "
        "No rules run here."
    ),
)

api = APIRouter(prefix="/api/v1")

#: Whoever the mock says is calling. The real API takes this from a bearer
#: token; the mock hands back a token and then ignores it, because it is a
#: fixture source rather than a security boundary. That difference is the one
#: place the mock and the real API deliberately do not match, and it is why
#: nothing is ever demonstrated against the mock.
DEMO_USER = {
    "id": "usr_whitfield",
    "display_name": "A. Whitfield",
    "email": "a.whitfield@northgate.example",
    "roles": ["ANALYST"],
}


@api.post("/auth/token")
def sign_in(body: rq.SignInRequest) -> dict:
    """Any credential is accepted. The shape is the point, not the check."""
    return {"token": "mock-token", "token_type": "bearer", "user": DEMO_USER}


@api.get("/auth/me")
def whoami() -> dict:
    return DEMO_USER


@api.post("/auth/logout")
def sign_out() -> dict:
    return {"ok": True, "note": "The mock stores no session."}


def _error(code: ErrorCode, message: str | None = None, field: str | None = None):
    status, default = CATALOGUE[code]
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code.value, "message": message or default, "field": field}},
    )


# --------------------------------------------------------------------------
# Group 1, state and policy
# --------------------------------------------------------------------------


@api.get("/state", response_model=StateResponse)
def get_state():
    return fx.state()


@api.get("/policy", response_model=PolicyConfig)
def get_policy():
    return fx.policy_config()


@api.get("/investment-policy")
def get_investment_policy():
    """404 here is a real state rather than an error. Without a buffer, a
    ladder and cover targets there is nothing to measure a gap against."""
    return _error(ErrorCode.NO_INVESTMENT_POLICY)


@api.post("/investment-policy", status_code=201)
def set_investment_policy(body: rq.InvestmentPolicyRequest):
    return {"id": "inv_pol_v1", "effective_from": s.CLOCK_DATE, "approved_by": body.approved_by}


# --------------------------------------------------------------------------
# Group 2, deals
# --------------------------------------------------------------------------


@api.post("/deals/check", response_model=CheckResult)
def check_deal(body: rq.CheckRequest):
    """Persists nothing. Called on every pause in typing."""
    if body.counterparty_id not in fx.CP_BY_ID:
        return _error(ErrorCode.COUNTERPARTY_NOT_FOUND, field="counterparty_id")
    return fx.check_result(
        body.counterparty_id, body.instrument, body.principal_pence, body.tenor_months
    )


@api.post("/deals", status_code=201)
def create_deal(body: rq.CreateDealRequest, response: Response):
    """A blocked deal is a 201 with status BLOCKED. The record was created and
    the exception was raised, so the control worked."""
    if body.counterparty_id not in fx.CP_BY_ID:
        return _error(ErrorCode.COUNTERPARTY_NOT_FOUND, field="counterparty_id")
    result = fx.check_result(
        body.counterparty_id, body.instrument, body.principal_pence, body.tenor_months
    )
    blocked = result.outcome == "FAIL"
    summary = fx.deal_summaries()[0].model_copy(
        update={
            "id": "dl_new_001",
            "counterparty_id": body.counterparty_id,
            "counterparty_name": fx.CP_BY_ID[body.counterparty_id]["name"],
            "instrument": body.instrument,
            "principal_pence": body.principal_pence,
            "rate_bp": body.rate_bp,
            "tenor_months": body.tenor_months,
            "status": "BLOCKED" if blocked else "ACTIVE",
            "measured_pence": result.measured_pence,
            "measurement_basis": result.measurement_basis,
            "stage": "blocked" if blocked else "awaiting confirmation",
            "required_approver": result.required_approver,
            "approved_by": None if blocked else DEMO_USER["display_name"],
        }
    )
    return {
        "deal": summary.model_dump(),
        "run": result.model_dump(),
        "queue_item_id": "exc_new_001" if blocked else None,
    }


@api.get("/deals", response_model=list[DealSummary])
def list_deals(status: str | None = None, counterparty_id: str | None = None):
    deals = fx.deal_summaries()
    if status:
        deals = [d for d in deals if d.status == status]
    if counterparty_id:
        deals = [d for d in deals if d.counterparty_id == counterparty_id]
    return deals


@api.get("/deals/{deal_id}", response_model=DealDetail)
def get_deal(deal_id: str):
    """One click, one panel, one call."""
    detail = fx.deal_detail(deal_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="DEAL_NOT_FOUND")
    return detail


@api.post("/deals/{deal_id}/approve")
def approve_deal(deal_id: str, body: rq.ApproveDealRequest):
    return {
        "deal_id": deal_id,
        "approved_by": DEMO_USER["display_name"],
        "role": body.role,
    }


@api.post("/deals/{deal_id}/instruct")
def instruct_deal(deal_id: str, body: rq.InstructDealRequest):
    return {
        "instruction_id": "ins_001",
        "deal_id": deal_id,
        "status": "PENDING",
        "instructed_by": DEMO_USER["display_name"],
    }


@api.post("/deals/{deal_id}/amendments", status_code=201)
def raise_amendment(deal_id: str, body: rq.RaiseAmendmentRequest):
    """Raising records what is proposed. Nothing is recalculated and nothing
    is reversed until apply, which is why these are two calls."""
    return {
        "amendment_id": "amd_001",
        "preview": {
            "accruals_affected": 12,
            "amount_to_reverse_pence": 148_320,
            "periods_affected": ["2026-07", "2026-08"],
            "any_period_closed": True,
        },
    }


@api.post("/amendments/{amendment_id}/apply")
def apply_amendment(amendment_id: str):
    return {
        "reversed_pence": 148_320,
        "reposted_pence": 141_005,
        "periods_reopened": ["2026-07"],
        "deal": fx.deal_summaries()[0].model_dump(),
    }


@api.post("/deals/{deal_id}/settle")
def settle_deal(deal_id: str, body: rq.SettleDealRequest):
    """Two of three agreeing is not enough."""
    return {
        "settlement_id": "stl_001",
        "deal_id": deal_id,
        "match_status": "AGREED",
        "break_detail": None,
        "closed_at": f"{s.CLOCK_DATE}T16:04:00+00:00",
    }


# --------------------------------------------------------------------------
# Group 3, confirmations and matching
# --------------------------------------------------------------------------


@api.post("/confirmations", status_code=201)
def ingest_confirmation(body: rq.IngestConfirmationRequest):
    """A mismatched confirmation is a 201 with match_status MISMATCHED. It was
    received and stored, so the control worked."""
    return {
        "confirmation_id": "cnf_001",
        "match_status": "MATCHED",
        "deal_id": "dl_nts_001",
        "differences": [],
        "queue_item_id": None,
    }


@api.get("/confirmations", response_model=list[ConfirmationSummary])
def list_confirmations(match_status: str | None = None):
    return []


@api.post("/confirmations/{confirmation_id}/match")
def match_confirmation(confirmation_id: str, body: rq.MatchConfirmationRequest):
    return {
        "confirmation_id": confirmation_id,
        "deal_id": body.deal_id,
        "match_status": "MATCHED",
        "differences": [],
    }


# --------------------------------------------------------------------------
# Group 4, accounting and settlement
# --------------------------------------------------------------------------


@api.get("/deals/{deal_id}/accruals")
def list_accruals(deal_id: str):
    return []


@api.get("/journals")
def list_journals(period: str | None = None, status: str | None = None, deal_id: str | None = None):
    return []


@api.post("/journals/post")
def post_journals(body: rq.PostJournalsRequest):
    """Idempotent per journal. A retry after a partial failure posts only what
    did not land, because Oracle already has the rest."""
    return {"period": body.period, "posted": 0, "skipped": 0, "failed": 0, "references": []}


# --------------------------------------------------------------------------
# Group 5, counterparties
# --------------------------------------------------------------------------


@api.post("/counterparties", status_code=201)
def create_counterparty(body: rq.CreateCounterpartyRequest):
    return {"counterparty_id": "cp_new_001", "name": body.name, "status": "DRAFT"}


@api.post("/counterparties/{counterparty_id}/verify")
def verify_counterparty(counterparty_id: str, body: rq.VerifyCounterpartyRequest):
    band = fx.BAND_BY_RATING.get(body.rating)
    if band is None:
        return _error(ErrorCode.UNKNOWN_RATING, field="rating")
    return {
        "counterparty_id": counterparty_id,
        "status": "VERIFIED",
        "proposed_limit_pence": band["max_limit_pence"],
        "proposed_max_tenor_months": band["max_tenor_months"],
    }


@api.post("/counterparties/{counterparty_id}/limit", status_code=201)
def set_limit(counterparty_id: str, body: rq.SetLimitRequest):
    if not body.approved_by:
        return _error(ErrorCode.APPROVER_REQUIRED, field="approved_by")
    return {"limit_id": "lim_new_001", "counterparty_id": counterparty_id, "status": "APPROVED"}


@api.post("/counterparties/{counterparty_id}/activate")
def activate_counterparty(counterparty_id: str, body: rq.ActivateCounterpartyRequest):
    return {"counterparty_id": counterparty_id, "status": "ACTIVE"}


@api.get("/counterparties/{counterparty_id}/limits", response_model=list[LimitVersion])
def list_limits(counterparty_id: str):
    version = fx.limit_version(counterparty_id)
    return [version] if version else []


@api.post("/counterparties/{counterparty_id}/rating")
def record_rating_action(counterparty_id: str, body: rq.RatingActionRequest):
    """One call in, an unknown number of breaches out."""
    return {
        "rating_event_id": "rte_001",
        "counterparty_id": counterparty_id,
        "new_rating": body.new_rating,
        "new_limit_pence": fx.BAND_BY_RATING.get(body.new_rating, {}).get("max_limit_pence"),
        "new_max_tenor_months": fx.BAND_BY_RATING.get(body.new_rating, {}).get("max_tenor_months"),
        "positions_tested": len([d for d in s.DEALS if d["counterparty_id"] == counterparty_id]),
        "breaches_raised": 0,
        "policy_version_id": fx.POLICY["id"],
    }


# --------------------------------------------------------------------------
# Group 6, the queue and breaches
# --------------------------------------------------------------------------


@api.get("/queue", response_model=list[QueueItem])
def get_queue(status: str = "OPEN"):
    return fx.queue_items()


@api.post("/queue/{item_id}/resolve")
def resolve_queue_item(item_id: str, body: rq.ResolveQueueItemRequest):
    if body.resolution == "OVERRIDDEN" and not body.reason:
        return _error(ErrorCode.OVERRIDE_REASON_REQUIRED, field="reason")
    return {"queue_item_id": item_id, "status": "RESOLVED", "resolution": body.resolution}


@api.get("/breaches", response_model=list[BreachView])
def get_breaches():
    return fx.breaches()


@api.post("/breaches/{breach_id}/respond")
def respond_to_breach(breach_id: str, body: rq.RespondToBreachRequest):
    """Records the decision. Does not clear the breach and does not change the
    deal, because the position is still outside policy."""
    return {"breach_id": breach_id, "status": "RESPONDED", "response": body.response}


# --------------------------------------------------------------------------
# Group 7, the advisory layer
# --------------------------------------------------------------------------


@api.get("/advisory/latest")
def advisory_latest():
    """Null is a valid answer and not a 404."""
    return fx.advisory_card()


@api.get("/advisory/runs/{run_id}", response_model=AdvisoryRun)
def advisory_run(run_id: str):
    if run_id != "adv_run_001":
        return _error(ErrorCode.RUN_NOT_FOUND)
    return fx.advisory_run()


@api.post("/advisory/runs")
def trigger_advisory_run(body: rq.RunAdvisoryRequest):
    return {"run_id": "adv_run_001", "outcome": "MODEL_ACCEPTED", "recommendation_id": "rec_001"}


@api.post("/advisory/recommendations/{recommendation_id}/decide")
def decide_recommendation(recommendation_id: str, body: rq.DecideRecommendationRequest):
    """Records a decision and returns a ticket. It books nothing.

    The deal is created by POST /deals like any other and passes the same six
    checks. That is the whole guardrail, expressed as an API shape.
    """
    if body.decision == "REJECTED" and not body.reason:
        return _error(ErrorCode.REJECTION_REASON_REQUIRED, field="reason")
    card = fx.advisory_card()
    return {
        "ok": True,
        "ticket": None if body.decision == "REJECTED" else card.ticket.model_dump(),
    }


# --------------------------------------------------------------------------
# Group 8, currency risk
# --------------------------------------------------------------------------


@api.get("/exposure/counterparty", response_model=ExposureView)
def exposure_counterparty():
    return fx.exposure_counterparty()


@api.get("/exposure/currency", response_model=CurrencyExposureView)
def exposure_currency(currency: str = "EUR"):
    """A separate endpoint from counterparty exposure. There is deliberately
    no endpoint that returns both."""
    return fx.exposure_currency()


@api.post("/currency-exposures", status_code=201)
def create_currency_exposure(body: rq.CreateCurrencyExposureRequest):
    return {
        "id": "cxp_new_001",
        "currency": body.currency,
        "amount_minor": body.amount_minor,
        "status": "IDENTIFIED",
    }


@api.post("/currency-exposures/{exposure_id}/hedges", status_code=201)
def link_hedge(exposure_id: str, body: rq.LinkHedgeRequest):
    return {
        "hedge_link_id": "hl_new_001",
        "currency_exposure_id": exposure_id,
        "deal_id": body.deal_id,
        "covered_amount_minor": body.covered_amount_minor,
        "status": "PARTIALLY_COVERED",
    }


@api.post("/hedge-links/{link_id}/unlink")
def unlink_hedge(link_id: str, body: rq.UnlinkHedgeRequest):
    """Coverage is recomputed and the status can move backwards. A covered
    exposure becoming partially covered when a delivery slips is correct."""
    return {"hedge_link_id": link_id, "unlink_reason": body.reason, "status": "PARTIALLY_COVERED"}


# --------------------------------------------------------------------------
# Group 9, jobs, the Oracle boundary and administration
# --------------------------------------------------------------------------


@api.post("/jobs/nightly", status_code=202)
def nightly_job(body: rq.NightlyJobRequest):
    """Accrual, then advisory. Returns 202 because the caller is a scheduler
    and does not wait. Idempotent by clock date."""
    return {"accepted": True, "as_of": body.as_of or s.CLOCK_DATE}


@api.post("/statements", status_code=201)
def ingest_statement(body: rq.StatementLineRequest):
    return {"statement_line_id": "bsl_001", "reference": body.reference}


@api.get("/instructions")
def list_instructions():
    return []


@api.post("/admin/clock")
def set_clock(body: rq.SetClockRequest):
    return {"today_date": body.today_date}


@api.post("/admin/enforcement")
def set_enforcement(body: rq.SetEnforcementRequest):
    """Switching this live is the fastest way to settle which policy the
    business wants."""
    return {"enforcement": body.enforcement}


@api.post("/admin/reset")
def reset():
    return {"reset": True, "counterparties": len(s.COUNTERPARTIES), "deals": len(s.DEALS)}


app.include_router(api)


@app.get("/health")
def health():
    return {"ok": True, "server": "mock", "as_of": s.CLOCK_DATE}
