"""Queries against users and memberships."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppUser, Membership


def by_email(session: Session, tenant_id: str, email: str) -> AppUser | None:
    return session.scalars(
        select(AppUser)
        .where(AppUser.tenant_id == tenant_id)
        .where(AppUser.email == email.strip().lower())
    ).one_or_none()


def get(session: Session, user_id: str) -> AppUser | None:
    return session.get(AppUser, user_id)


def roles(session: Session, user_id: str) -> list[str]:
    """Live memberships only. A revoked role is history, not a permission."""
    return list(
        session.scalars(
            select(Membership.role)
            .where(Membership.user_id == user_id)
            .where(Membership.revoked_at.is_(None))
        )
    )


def list_users(session: Session, tenant_id: str) -> list[AppUser]:
    return list(
        session.scalars(
            select(AppUser)
            .where(AppUser.tenant_id == tenant_id)
            .order_by(AppUser.display_name)
        )
    )
