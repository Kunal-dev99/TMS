"""Per-tenant MFA enforcement policy (Phase 4).

Stored in ``tenant_setting`` under ``key='mfa_policy'``. Payload:

    {
      "mode": "off" | "optional" | "required_for_sensitive_roles" | "required_for_all",
      "grace_days": 7,
      "activated_at": "2026-10-09T12:00:00Z"   # when mode last became non-off
    }

Grace window
------------
When ``mode`` flips from ``off`` to anything else, ``activated_at`` is
stamped with now. Users inside the grace window (now < activated_at +
grace_days) still see sensitive endpoints work — they just see
``mfa_required_by`` on ``GET /auth/me`` so the client can show a nag
banner. Outside grace, require_mfa() refuses.

Sensitive roles
---------------
For ``required_for_sensitive_roles``, the roles that must have MFA are:
CFO, HEAD_OF_TREASURY, ADMIN, COMPLIANCE_OFFICER. Everyone else is
exempt. Hard-coded here rather than configurable because every one of
those roles is explicitly treasury-sensitive by ADR-0011; a customer
asking "can we add my accountant" needs an admin decision, not a
settings slider.

Default
-------
A tenant with no row in tenant_setting for ``mfa_policy`` is treated
as ``mode: off``. The demo tenant stays off until an admin changes it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.repo import tenant_settings as settings_repo


SETTING_KEY = "mfa_policy"
SENSITIVE_ROLES: frozenset[str] = frozenset(
    {"CFO", "HEAD_OF_TREASURY", "ADMIN", "COMPLIANCE_OFFICER"}
)

Mode = Literal["off", "optional", "required_for_sensitive_roles", "required_for_all"]
VALID_MODES: tuple[Mode, ...] = (
    "off", "optional", "required_for_sensitive_roles", "required_for_all",
)
DEFAULT_GRACE_DAYS = 7


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _defaults_payload() -> dict[str, Any]:
    return {"mode": "off", "grace_days": DEFAULT_GRACE_DAYS, "activated_at": None}


# --- read ------------------------------------------------------------------


def get_policy(session: Session, tenant_id: str) -> dict[str, Any]:
    """Return the full policy payload (always well-formed)."""
    payload = settings_repo.get_or_default(
        session, tenant_id, SETTING_KEY, _defaults_payload()
    )
    # Normalise against bad data in the DB.
    mode = payload.get("mode")
    if mode not in VALID_MODES:
        mode = "off"
    grace_days = int(payload.get("grace_days", DEFAULT_GRACE_DAYS) or DEFAULT_GRACE_DAYS)
    if grace_days < 0:
        grace_days = 0
    return {
        "mode": mode,
        "grace_days": grace_days,
        "activated_at": payload.get("activated_at"),
    }


def mode(session: Session, tenant_id: str) -> str:
    return get_policy(session, tenant_id)["mode"]


# --- write -----------------------------------------------------------------


def set_policy(
    session: Session,
    tenant_id: str,
    *,
    mode: str,
    grace_days: int | None = None,
    updated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """Set the policy. If the mode is becoming non-off (from off), stamp
    activated_at. Flipping to 'off' clears activated_at — if an admin
    later turns it back on, grace restarts.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"Unknown MFA mode: {mode!r}. One of {VALID_MODES}.")
    if grace_days is None:
        grace_days = DEFAULT_GRACE_DAYS
    if grace_days < 0:
        raise ValueError("grace_days must be >= 0.")

    current = get_policy(session, tenant_id)
    was_off = current["mode"] == "off"
    now_iso = _iso(_utcnow())

    if mode == "off":
        activated_at = None
    elif was_off:
        activated_at = now_iso
    else:
        # Still non-off — keep the original activation so grace doesn't
        # reset when an admin tightens the policy (off → optional →
        # required_for_all should not grant another 7 days of grace).
        activated_at = current.get("activated_at") or now_iso

    new_payload = {
        "mode": mode,
        "grace_days": grace_days,
        "activated_at": activated_at,
    }
    settings_repo.upsert(
        session, tenant_id, SETTING_KEY, new_payload, updated_by_user_id
    )
    return new_payload


# --- enforcement ----------------------------------------------------------


def is_mfa_required(
    session: Session,
    tenant_id: str,
    roles: list[str],
    now: datetime | None = None,
) -> bool:
    """Should this caller be refused unless mfa_passed==True?"""
    policy = get_policy(session, tenant_id)
    policy_mode = policy["mode"]
    if policy_mode in ("off", "optional"):
        return False

    # Grace window still open? If so, don't refuse — the nag banner is
    # how we tell the user it's coming.
    activated_at = _parse_iso(policy.get("activated_at") or "")
    if activated_at is not None:
        deadline = activated_at + timedelta(days=policy["grace_days"])
        if (now or _utcnow()) < deadline:
            return False

    if policy_mode == "required_for_all":
        return True
    if policy_mode == "required_for_sensitive_roles":
        return any(r in SENSITIVE_ROLES for r in roles)
    return False


def required_by(
    session: Session,
    tenant_id: str,
    roles: list[str],
) -> str | None:
    """Return the ISO deadline for the nag banner, or None if MFA is
    not relevant for this caller (policy off / optional / role exempt
    under required_for_sensitive_roles).

    Returns the deadline whether or not the user is still inside the
    grace window — the client decides whether to show a banner.
    """
    policy = get_policy(session, tenant_id)
    policy_mode = policy["mode"]
    if policy_mode in ("off", "optional"):
        return None
    if policy_mode == "required_for_sensitive_roles" and not any(
        r in SENSITIVE_ROLES for r in roles
    ):
        return None
    activated_at = _parse_iso(policy.get("activated_at") or "")
    if activated_at is None:
        return None
    deadline = activated_at + timedelta(days=policy["grace_days"])
    return _iso(deadline)
