"""Queries against counterparties, their groups, their instruments and their
limits.

`current_limit` returns the one row with no superseded_at. A counterparty
with no limit in force is a real state and not an error here: it is the
difference between a limit of nothing and the absence of one, and the
interface shows an em dash for the second.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Counterparty, CounterpartyInstrument, CpGroup, CpLimit


def get(session: Session, counterparty_id: str) -> Counterparty | None:
    return session.get(Counterparty, counterparty_id)


def list_all(session: Session, tenant_id: str) -> list[Counterparty]:
    return list(
        session.scalars(
            select(Counterparty)
            .where(Counterparty.tenant_id == tenant_id)
            .order_by(Counterparty.name)
        )
    )


def group(session: Session, group_id: str) -> CpGroup | None:
    return session.get(CpGroup, group_id)


def list_groups(session: Session, tenant_id: str) -> list[CpGroup]:
    return list(
        session.scalars(select(CpGroup).where(CpGroup.tenant_id == tenant_id))
    )


def counterparty_ids_in_group(session: Session, group_id: str) -> list[str]:
    return list(
        session.scalars(
            select(Counterparty.id).where(Counterparty.group_id == group_id)
        )
    )


def permitted_instruments(session: Session, counterparty_id: str) -> list[str]:
    return list(
        session.scalars(
            select(CounterpartyInstrument.instrument)
            .where(CounterpartyInstrument.counterparty_id == counterparty_id)
            .where(CounterpartyInstrument.enabled == 1)
        )
    )


def current_limit(session: Session, counterparty_id: str) -> CpLimit | None:
    """The limit in force. None means no limit in force, which is not zero."""
    return session.scalars(
        select(CpLimit)
        .where(CpLimit.counterparty_id == counterparty_id)
        .where(CpLimit.superseded_at.is_(None))
    ).one_or_none()


def limit_by_id(session: Session, limit_id: str) -> CpLimit | None:
    """A superseded version, for re-deriving a historic check run."""
    return session.get(CpLimit, limit_id)


def limit_history(session: Session, counterparty_id: str) -> list[CpLimit]:
    return list(
        session.scalars(
            select(CpLimit)
            .where(CpLimit.counterparty_id == counterparty_id)
            .order_by(CpLimit.effective_from.desc())
        )
    )
