"""Queries against the Oracle boundary tables.

Interface I-3 in this build is an adapter over `oracle_balance`. The adapter
interface is the deliverable; the table behind it is the stub.

`uninvested_cash_pence` returns None rather than zero when there is no
balance for the date. The difference matters: zero is a balance, None is the
absence of one, and the concentration check has no denominator without it.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import OracleBalance, OracleInstruction


def latest_balance_date(
    session: Session, tenant_id: str, not_after: str | None = None
) -> str | None:
    """The most recent date a balance was fed for, on or before a date.

    Balances arrive nightly and are prior day, which document 4 states as a
    boundary rather than a defect. Demanding a balance stamped with today's
    date would mean the feed is missing every morning, and the concentration
    check would fail closed every morning with it.

    Phase four adds an explicit stale threshold and a visible warning, which
    is the difference between "this is three days old" and "this is absent".
    That threshold reads this function.
    """
    statement = select(func.max(OracleBalance.as_of_date)).where(
        OracleBalance.tenant_id == tenant_id
    )
    if not_after is not None:
        statement = statement.where(OracleBalance.as_of_date <= not_after)
    return session.scalar(statement)


def uninvested_cash_pence(
    session: Session, tenant_id: str, as_of_date: str
) -> int | None:
    """Total balance across accounts, from the latest feed on or before the
    date. None when nothing has ever been fed for that far back.

    None is not zero. Zero is a balance and None is the absence of one, and
    the concentration check has no denominator without it.
    """
    effective = latest_balance_date(session, tenant_id, not_after=as_of_date)
    if effective is None:
        return None
    total = session.scalar(
        select(func.sum(OracleBalance.balance_pence))
        .where(OracleBalance.tenant_id == tenant_id)
        .where(OracleBalance.as_of_date == effective)
    )
    return int(total) if total is not None else None


def instructions(session: Session, tenant_id: str) -> list[OracleInstruction]:
    return list(
        session.scalars(
            select(OracleInstruction)
            .where(OracleInstruction.tenant_id == tenant_id)
            .order_by(OracleInstruction.created_at.desc())
        )
    )
