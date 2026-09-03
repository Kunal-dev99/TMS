"""Queries against the policy, the clock and the rating bands.

No rules here. A function returns rows or None, and the caller decides what
that means. `current_policy` returning None is not an error in this layer;
it becomes one in CheckEngine, which fails closed on it.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PolicyVersion, RatingBand, SystemClock


def current_policy(session: Session, tenant_id: str) -> PolicyVersion | None:
    """The one version with no superseded_at. The partial unique index is
    what makes 'the one' true rather than hopeful."""
    return session.scalars(
        select(PolicyVersion)
        .where(PolicyVersion.tenant_id == tenant_id)
        .where(PolicyVersion.superseded_at.is_(None))
    ).one_or_none()


def policy_by_id(session: Session, policy_id: str) -> PolicyVersion | None:
    """A historic version, for re-deriving a check run recorded against it."""
    return session.get(PolicyVersion, policy_id)


def today(session: Session, tenant_id: str) -> str | None:
    clock = session.get(SystemClock, tenant_id)
    return clock.today_date if clock else None


def rating_bands(session: Session, tenant_id: str) -> list[RatingBand]:
    return list(
        session.scalars(
            select(RatingBand)
            .where(RatingBand.tenant_id == tenant_id)
            .order_by(RatingBand.ordinal.desc())
        )
    )


def band_for_rating(
    session: Session, tenant_id: str, rating: str
) -> RatingBand | None:
    return session.scalars(
        select(RatingBand)
        .where(RatingBand.tenant_id == tenant_id)
        .where(RatingBand.rating == rating)
    ).one_or_none()
