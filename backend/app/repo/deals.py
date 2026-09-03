"""Queries against deals.

`LIVE_STATUSES` is the definition of a position that still consumes headroom.
A matured deal is due but not reconciled, and until it closes the
counterparty's headroom is still consumed, so it is live for exposure. That
is why closing is part of the control system rather than an accounting
formality.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Counterparty, Deal

#: Statuses that consume headroom. Cancelled, blocked and closed do not.
LIVE_STATUSES = ("ACTIVE", "MATURED")


def get(session: Session, deal_id: str) -> Deal | None:
    return session.get(Deal, deal_id)


def live_for_counterparty(session: Session, counterparty_id: str) -> list[Deal]:
    """Read on every keystroke. ix_deal_cp_active exists for this query."""
    return list(
        session.scalars(
            select(Deal)
            .where(Deal.counterparty_id == counterparty_id)
            .where(Deal.status.in_(LIVE_STATUSES))
        )
    )


def live_for_group(session: Session, group_id: str) -> list[Deal]:
    """Every live deal held by any entity in one credit group.

    One join, because the group is the only thing that connects two legal
    entities and the check that reads this is the whole argument.
    """
    return list(
        session.scalars(
            select(Deal)
            .join(Counterparty, Counterparty.id == Deal.counterparty_id)
            .where(Counterparty.group_id == group_id)
            .where(Deal.status.in_(LIVE_STATUSES))
        )
    )


def live_for_tenant(session: Session, tenant_id: str) -> list[Deal]:
    return list(
        session.scalars(
            select(Deal)
            .where(Deal.tenant_id == tenant_id)
            .where(Deal.status.in_(LIVE_STATUSES))
        )
    )


def all_for_tenant(session: Session, tenant_id: str) -> list[Deal]:
    return list(
        session.scalars(
            select(Deal)
            .where(Deal.tenant_id == tenant_id)
            .order_by(Deal.trade_date.desc(), Deal.id)
        )
    )
