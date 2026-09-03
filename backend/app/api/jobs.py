"""Jobs and the Oracle boundary. Group 9a of document 2.

Only the instruction list is live in phase one. The nightly job runs accrual
and then the advisory layer, and both of those are phase two.

An instruction is written to a table rather than sent. The platform describes
what should happen and hands over, and nothing in the book depends on the
handover succeeding.
"""

from fastapi import APIRouter

from fastapi import Response

from app.api.deps import Caller, Ctx
from app.repo import oracle as oracle_repo
from app.schemas import requests as rq
from app.services.nightly_job import NightlyJob

router = APIRouter(tags=["Jobs and the Oracle boundary"])


@router.post("/jobs/nightly", status_code=202)
def nightly(body: rq.NightlyJobRequest, ctx: Ctx, caller: Caller) -> dict:
    """Accrual, then journals, then advisory.

    202 because the caller is a scheduler and does not wait. Idempotent by
    clock date: running it twice for the same date writes accruals once.
    """
    result = NightlyJob(
        ctx.session, ctx.tenant_id, ctx.as_of_date, ctx.policy
    ).run(as_of=body.as_of, force=body.force)
    ctx.session.commit()
    return {
        "accepted": True,
        "as_of": result.as_of,
        "accrual_rows_written": result.accrual_rows_written,
        "accrual_rows_already_present": result.accrual_rows_already_present,
        "journals_built": result.journals_built,
        "advisory_run_id": result.advisory_run_id,
        "advisory_outcome": result.advisory_outcome,
        "advisory_skipped": result.advisory_skipped,
        "steps": result.steps,
    }


@router.get("/instructions")
def list_instructions(ctx: Ctx, caller: Caller) -> list[dict]:
    """What has been handed to Oracle. Interface I-4."""
    return [
        {
            "id": instruction.id,
            "deal_id": instruction.deal_id,
            "type": instruction.type,
            "amount_pence": instruction.amount_pence,
            "currency": instruction.currency,
            "value_date": instruction.value_date,
            "status": instruction.status,
            "oracle_reference": instruction.oracle_reference,
            "created_at": instruction.created_at,
        }
        for instruction in oracle_repo.instructions(ctx.session, ctx.tenant_id)
    ]
