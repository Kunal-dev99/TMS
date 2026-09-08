"""Accounting and settlement. Group 4 of document 2.

Three endpoints in phase two. Settlement belongs to this group and arrives
in phase three.

Posting is idempotent per journal rather than per batch: a partial failure
leaves the successful entries posted, because Oracle already has them.
"""

from fastapi import APIRouter

from app.api.deps import Caller, Ctx
from app.errors import ErrorCode, TreasuryError
from app.repo import deals as deal_repo
from app.schemas import requests as rq
from app.schemas.models import AccrualRow
from app.services.accrual_service import AccrualService
from app.services.journal_service import JournalService

router = APIRouter(tags=["Accounting and settlement"])


@router.get("/deals/{deal_id}/accruals", response_model=list[AccrualRow])
def list_accruals(deal_id: str, ctx: Ctx, caller: Caller) -> list[AccrualRow]:
    """The daily rows for one deal.

    Includes reversals, which carry the amendment that caused them.
    """
    deal = deal_repo.get(ctx.session, deal_id)
    if deal is None or deal.tenant_id != ctx.tenant_id:
        raise TreasuryError(ErrorCode.DEAL_NOT_FOUND)
    service = AccrualService(ctx.session, ctx.tenant_id, ctx.as_of_date)
    return [
        AccrualRow(
            id=row.id,
            accrual_date=row.accrual_date,
            day_count=row.day_count,
            rate_bp=row.rate_bp,
            amount_pence=row.amount_pence,
            cumulative_pence=row.cumulative_pence,
            reversal_of=row.reversal_of,
            amendment_id=row.amendment_id,
        )
        for row in service.for_deal(deal_id)
    ]


@router.get("/journals")
def list_journals(
    ctx: Ctx,
    caller: Caller,
    period: str | None = None,
    status: str | None = None,
    deal_id: str | None = None,
) -> list[dict]:
    """The unposted set in an open period is the useful query."""
    service = JournalService(ctx.session, ctx.tenant_id, ctx.as_of_date)
    return [
        {
            "id": journal.id,
            "deal_id": journal.deal_id,
            "accrual_id": journal.accrual_id,
            "type": journal.type,
            "period": journal.period,
            "debit_account": journal.debit_account,
            "credit_account": journal.credit_account,
            "amount_pence": journal.amount_pence,
            "status": journal.status,
            "posted_at": journal.posted_at,
            "oracle_reference": journal.oracle_reference,
        }
        for journal in service.list_journals(period, status, deal_id)
    ]


@router.post("/journals/post")
def post_journals(body: rq.PostJournalsRequest, ctx: Ctx, caller: Caller) -> dict:
    """Post built journals to Oracle. Interface I-6."""
    service = JournalService(ctx.session, ctx.tenant_id, ctx.as_of_date)
    service.require_open_period(body.period)
    result = service.post_period(body.period)
    ctx.session.commit()
    return {
        "period": result.period,
        "posted": result.posted,
        "skipped": result.skipped,
        "failed": result.failed,
        "references": result.references,
    }


# ==========================================================================
# Accounting-event catalogue (Anil's "everything config-driven" ask).
# ==========================================================================

from app.services import accounting_events as _events  # noqa: E402


@router.get("/accounting/events")
def get_accounting_events(caller: Caller) -> dict:
    return _events.as_dict(_events.get_settings())


@router.put("/accounting/events")
def put_accounting_events(patch: dict, caller: Caller) -> dict:
    return _events.as_dict(_events.update_settings(patch))


@router.post("/accounting/events/reset")
def reset_accounting_events(caller: Caller) -> dict:
    return _events.as_dict(_events.reset_defaults())
