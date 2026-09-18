"""Issue and consume single-use activation tokens.

Replaces the initial 'return the temp password inline' shape. The
admin invites a user or resets their password: this service issues a
token, returns the raw string once (never stored), records only its
SHA-256 hash. The invitee visits `/activate?token=…`, sets their own
password, and the token is marked consumed. Neither the admin nor
Treasury Register ever sees the chosen password.

Tokens are 24-hour, single-use. Consuming a token also invalidates any
other unconsumed tokens for the same user — so a reset always
supersedes a pending invite.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ErrorCode, TreasuryError
from app.ids import new_id, now
from app.models import ActivationToken, AppUser
from app.security import hash_password


DEFAULT_TTL_HOURS = 24
# Placeholder password_hash for a user who has been invited but not yet
# activated. verify_password() against this always returns False, so the
# user can exist and hold roles/scope but not sign in until they consume
# the invite token.
UNUSABLE_PASSWORD_HASH = "!pending-activation"


@dataclass
class IssuedToken:
    raw_token: str  # only exists in memory; caller shows this once
    expires_at: str
    activation_url: str  # convenience for the admin UI


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _activation_url(raw: str) -> str:
    # Client-facing URL fragment; the frontend serves `/activate?token=…`.
    return f"/activate?token={raw}"


def issue_token(
    session: Session,
    *,
    tenant_id: str,
    user_id: str,
    purpose: str,  # 'INVITE' or 'RESET'
    created_by: str,
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> IssuedToken:
    if purpose not in ("INVITE", "RESET"):
        raise ValueError(f"unknown activation purpose: {purpose}")
    # Revoke any live unconsumed token for this user — one active
    # activation link at a time.
    for row in session.scalars(
        select(ActivationToken)
        .where(ActivationToken.user_id == user_id)
        .where(ActivationToken.consumed_at.is_(None))
    ):
        row.consumed_at = now()

    raw = secrets.token_urlsafe(32)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    ).replace(microsecond=0).isoformat()
    session.add(
        ActivationToken(
            id=new_id("act"),
            tenant_id=tenant_id,
            user_id=user_id,
            token_hash=_hash_token(raw),
            purpose=purpose,
            expires_at=expires_at,
            consumed_at=None,
            created_by=created_by,
            created_at=now(),
        )
    )
    session.flush()
    return IssuedToken(
        raw_token=raw,
        expires_at=expires_at,
        activation_url=_activation_url(raw),
    )


@dataclass
class ResolvedToken:
    user_id: str
    email: str
    display_name: str
    purpose: str
    expires_at: str


def resolve_token(session: Session, raw_token: str) -> ResolvedToken:
    """Look up a token WITHOUT consuming it — used by the activation
    page to show the user's email + purpose before they set a password.

    Raises on invalid, expired, consumed, or unknown tokens.
    """
    row = session.scalars(
        select(ActivationToken).where(
            ActivationToken.token_hash == _hash_token(raw_token)
        )
    ).one_or_none()
    if row is None:
        raise TreasuryError(
            ErrorCode.NOT_AUTHENTICATED,
            "That activation link is not valid.",
            field="token",
        )
    if row.consumed_at is not None:
        raise TreasuryError(
            ErrorCode.NOT_AUTHENTICATED,
            "That activation link has already been used.",
            field="token",
        )
    if row.expires_at < now():
        raise TreasuryError(
            ErrorCode.NOT_AUTHENTICATED,
            "That activation link has expired. Ask an administrator for a new one.",
            field="token",
        )
    user = session.get(AppUser, row.user_id)
    if user is None or user.status != "ACTIVE":
        raise TreasuryError(
            ErrorCode.NOT_AUTHENTICATED,
            "The account this link belongs to is no longer active.",
            field="token",
        )
    return ResolvedToken(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        purpose=row.purpose,
        expires_at=row.expires_at,
    )


def consume_token(session: Session, raw_token: str, new_password: str) -> AppUser:
    """Set the user's password and mark the token consumed.

    Both writes happen in one call. Password strength policy lives
    here for the moment (min 8 chars); wire to a policy version later.
    """
    if len(new_password) < 8:
        raise TreasuryError(
            ErrorCode.NOT_AUTHENTICATED,
            "Password must be at least 8 characters.",
            field="password",
        )
    row = session.scalars(
        select(ActivationToken).where(
            ActivationToken.token_hash == _hash_token(raw_token)
        )
    ).one_or_none()
    if row is None or row.consumed_at is not None or row.expires_at < now():
        raise TreasuryError(
            ErrorCode.NOT_AUTHENTICATED,
            "That activation link is not valid or has expired.",
            field="token",
        )
    user = session.get(AppUser, row.user_id)
    if user is None or user.status != "ACTIVE":
        raise TreasuryError(
            ErrorCode.NOT_AUTHENTICATED,
            "The account this link belongs to is no longer active.",
            field="token",
        )
    user.password_hash = hash_password(new_password)
    row.consumed_at = now()
    session.flush()
    return user


def has_pending_activation(session: Session, user_id: str) -> bool:
    """True when the user has a live unconsumed activation token."""
    return session.scalars(
        select(ActivationToken)
        .where(ActivationToken.user_id == user_id)
        .where(ActivationToken.consumed_at.is_(None))
        .where(ActivationToken.expires_at > now())
    ).first() is not None
