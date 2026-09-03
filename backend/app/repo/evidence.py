"""Queries against the evidence tables: check runs, the queue and breaches.

Nothing here is ever deleted. Resolving a queue item and responding to a
breach are both writes that leave the original row in place, because the
question an auditor asks is what was decided and by whom, not what the
current state happens to be.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Breach, CheckRun, ExceptionItem


# -- check runs ------------------------------------------------------------


def get_check_run(session: Session, check_run_id: str) -> CheckRun | None:
    return session.get(CheckRun, check_run_id)


def latest_run_for_deal(session: Session, deal_id: str) -> CheckRun | None:
    return session.scalars(
        select(CheckRun)
        .where(CheckRun.deal_id == deal_id)
        .order_by(CheckRun.created_at.desc())
        .limit(1)
    ).one_or_none()


# -- the queue -------------------------------------------------------------


def get_queue_item(session: Session, item_id: str) -> ExceptionItem | None:
    return session.get(ExceptionItem, item_id)


def open_queue_items(session: Session, tenant_id: str) -> list[ExceptionItem]:
    return list(
        session.scalars(
            select(ExceptionItem)
            .where(ExceptionItem.tenant_id == tenant_id)
            .where(ExceptionItem.status == "OPEN")
            .order_by(ExceptionItem.raised_at.desc())
        )
    )


def queue_items(session: Session, tenant_id: str, status: str | None = None):
    statement = select(ExceptionItem).where(ExceptionItem.tenant_id == tenant_id)
    if status:
        statement = statement.where(ExceptionItem.status == status)
    return list(session.scalars(statement.order_by(ExceptionItem.raised_at.desc())))


def open_queue_counts(session: Session, tenant_id: str) -> dict[str, int]:
    """Split by cause. One queue with two causes still has to say which kind
    of work is waiting."""
    rows = session.execute(
        select(ExceptionItem.cause, func.count())
        .where(ExceptionItem.tenant_id == tenant_id)
        .where(ExceptionItem.status == "OPEN")
        .group_by(ExceptionItem.cause)
    ).all()
    counts = {cause: count for cause, count in rows}
    return {
        "total": sum(counts.values()),
        "limit_failures": counts.get("LIMIT_FAILURE", 0),
        "confirmation_mismatches": counts.get("CONFIRMATION_MISMATCH", 0),
    }


def open_items_for_deal(session: Session, deal_id: str) -> list[ExceptionItem]:
    return list(
        session.scalars(
            select(ExceptionItem)
            .where(ExceptionItem.deal_id == deal_id)
            .where(ExceptionItem.status == "OPEN")
        )
    )


# -- breaches --------------------------------------------------------------


def get_breach(session: Session, breach_id: str) -> Breach | None:
    return session.get(Breach, breach_id)


def breaches(session: Session, tenant_id: str) -> list[Breach]:
    """Newest first. A breach is never cleared by responding to it, so this
    list only grows within a demonstration."""
    return list(
        session.scalars(
            select(Breach)
            .where(Breach.tenant_id == tenant_id)
            .order_by(Breach.raised_at.desc())
        )
    )


def outstanding_breach_count(session: Session, tenant_id: str) -> int:
    """Every breach. Responding to one does not clear it.

    There is no cleared state and nothing in phase one puts a position back
    inside policy, so this counts rows rather than filtering on status. A
    count that fell when somebody responded would say the problem had gone
    away when only the conversation had.
    """
    return int(
        session.scalar(
            select(func.count()).select_from(Breach).where(Breach.tenant_id == tenant_id)
        )
        or 0
    )


def counterparties_with_breaches(session: Session, tenant_id: str) -> set[str]:
    """Which book rows are tinted. Tinted until the position changes, not
    until somebody answers."""
    return set(
        session.scalars(
            select(Breach.counterparty_id).where(Breach.tenant_id == tenant_id)
        )
    )


def deals_with_breaches(session: Session, tenant_id: str) -> set[str]:
    """Which blotter rows carry a breach pill."""
    return {
        deal_id
        for deal_id in session.scalars(
            select(Breach.deal_id).where(Breach.tenant_id == tenant_id)
        )
        if deal_id
    }


def breaches_for_deal(session: Session, deal_id: str) -> list[Breach]:
    return list(
        session.scalars(
            select(Breach).where(Breach.deal_id == deal_id).order_by(Breach.raised_at.desc())
        )
    )
