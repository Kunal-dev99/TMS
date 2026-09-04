"""Confirmations and matching. Group 3 of document 2.

Interface I-12, kept separate from I-1 on purpose. They could be one
interface, but matching only works because the two records arrive
independently.

A mismatched confirmation is a 201 with match_status MISMATCHED, not an
error. It was received and stored, so the control worked.
"""

from dataclasses import asdict

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import Caller, Ctx
from app.errors import ErrorCode, TreasuryError
from app.repo import deals as deal_repo
from app.schemas import requests as rq
from app.schemas.models import ConfirmationSummary, MatchDifference
from app.services.confirmation_parser import parse as parse_confirmation
from app.services.match_service import MatchService

router = APIRouter(tags=["Confirmations and matching"])


class ParseConfirmationRequest(BaseModel):
    raw_text: str


@router.post("/confirmations/parse")
def parse_confirmation_endpoint(
    body: ParseConfirmationRequest, ctx: Ctx, caller: Caller
) -> dict:
    """Read a raw confirmation into structured fields, for review.

    Nothing is ingested. The response is the extracted fields for the
    person to edit; ingestion happens through /confirmations as usual.
    That keeps the ingest control at one endpoint and the parser at
    another, so a bad parse cannot land a bad confirmation on the book.
    """
    parsed = parse_confirmation(ctx.session, ctx.tenant_id, body.raw_text)
    return asdict(parsed)


@router.post("/confirmations", status_code=201)
def ingest_confirmation(
    body: rq.IngestConfirmationRequest, ctx: Ctx, caller: Caller
) -> dict:
    """Ingest a confirmation. Attempts a match immediately.

    An unmatched confirmation is not an error. It means the deal has not been
    keyed yet, and the confirmation waits.
    """
    service = MatchService(ctx.session, ctx.tenant_id, ctx.as_of_date)
    outcome = service.ingest(
        message_type=body.message_type,
        reference=body.reference,
        instrument=body.instrument,
        principal_pence=body.principal_pence,
        rate_bp=body.rate_bp,
        value_date=body.value_date,
        maturity_date=body.maturity_date,
        counterparty_id=body.counterparty_id,
        raw_payload=body.raw_payload,
    )
    ctx.session.commit()
    return _payload(outcome)


@router.get("/confirmations", response_model=list[ConfirmationSummary])
def list_confirmations(
    ctx: Ctx, caller: Caller, match_status: str | None = None
) -> list[ConfirmationSummary]:
    """The matching queue is those with a null deal_id."""
    service = MatchService(ctx.session, ctx.tenant_id, ctx.as_of_date)
    return [
        _summary(service, confirmation)
        for confirmation in service.list_confirmations(match_status)
    ]


@router.post("/confirmations/{confirmation_id}/match")
def match_confirmation(
    confirmation_id: str, body: rq.MatchConfirmationRequest, ctx: Ctx, caller: Caller
) -> dict:
    """Match to a deal explicitly.

    For the case the automatic match could not resolve. Runs the same field
    comparison, so a manual match is not a shortcut past it.
    """
    service = MatchService(ctx.session, ctx.tenant_id, ctx.as_of_date)
    confirmation = service.get(confirmation_id)

    deal = deal_repo.get(ctx.session, body.deal_id)
    if deal is None or deal.tenant_id != ctx.tenant_id:
        raise TreasuryError(ErrorCode.DEAL_NOT_FOUND)

    outcome = service.match_to(confirmation, deal)
    ctx.session.commit()
    return _payload(outcome)


def _payload(outcome) -> dict:
    return {
        "confirmation_id": outcome.confirmation.id,
        "match_status": outcome.confirmation.match_status,
        "deal_id": outcome.confirmation.deal_id,
        "differences": [
            {
                "field_name": difference.field_name,
                "keyed_value": difference.keyed_value,
                "confirmed_value": difference.confirmed_value,
            }
            for difference in outcome.differences
        ],
        "queue_item_id": outcome.queue_item_id,
    }


def _summary(service: MatchService, confirmation) -> ConfirmationSummary:
    return ConfirmationSummary(
        id=confirmation.id,
        deal_id=confirmation.deal_id,
        counterparty_id=confirmation.counterparty_id,
        message_type=confirmation.message_type,
        reference=confirmation.reference,
        received_at=confirmation.received_at,
        match_status=confirmation.match_status,
        differences=[
            MatchDifference(
                field_name=difference.field_name,
                keyed_value=difference.keyed_value,
                confirmed_value=difference.confirmed_value,
            )
            for difference in service.differences_for(confirmation.id)
        ],
    )
