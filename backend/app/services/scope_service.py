"""Company scope — which legal entities a user may act for.

Enterprise treasury tools (Treasury Systems, Nomentia, TIS) all model
this: an analyst can be scoped to selected subsidiaries; suspending
their access to one subsidiary must not silently take their access to
the group. This module is the single reader/writer for that model.

A user's live scope is one of:
  * "*"                    — group-wide (a row with legal_entity_id IS NULL)
  * ["le_ng_uk", "le_ng_de"] — a specific subset

`may_act_for(user_id, entity_id)` is the check the six-check gate will
gain a seventh implicit rule for once dealing routes are threaded through.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id, now
from app.models import LegalEntity, UserEntityScope


@dataclass
class UserScope:
    group_wide: bool
    entity_ids: list[str]  # explicit entities; empty when group_wide

    def summary(self, entities: dict[str, LegalEntity]) -> str:
        """Plain English for the Admin panel."""
        if self.group_wide:
            return "Group-wide access to every subsidiary"
        if not self.entity_ids:
            return "No entity access"
        names = [entities[eid].code for eid in self.entity_ids if eid in entities]
        return f"{len(names)} of {len(entities)} entities: {', '.join(names)}"


def scope_for_user(session: Session, user_id: str) -> UserScope:
    rows = list(
        session.scalars(
            select(UserEntityScope)
            .where(UserEntityScope.user_id == user_id)
            .where(UserEntityScope.revoked_at.is_(None))
        )
    )
    group_wide = any(r.legal_entity_id is None for r in rows)
    entity_ids = sorted(r.legal_entity_id for r in rows if r.legal_entity_id is not None)
    return UserScope(group_wide=group_wide, entity_ids=entity_ids)


def may_act_for(session: Session, user_id: str, entity_id: str) -> bool:
    scope = scope_for_user(session, user_id)
    return scope.group_wide or entity_id in scope.entity_ids


def require_scope(session: Session, user, entity_id: str) -> None:
    """Refuse the request unless `user` may act for `entity_id`.

    Pre-flight to the six-check gate: if the person is not authorised
    for this legal entity, the deal never reaches the CheckEngine.
    Matches the enterprise-treasury pattern where scope is separate
    from — and evaluated before — financial-authority checks.
    """
    from app.errors import ErrorCode, TreasuryError

    if not entity_id:
        raise TreasuryError(
            ErrorCode.ROLE_NOT_HELD,
            "A legal_entity_id is required to book on the book.",
            field="legal_entity_id",
        )
    if not may_act_for(session, user.user_id, entity_id):
        # Look up the entity code for a friendlier message.
        entity = session.get(LegalEntity, entity_id)
        code = entity.code if entity else entity_id
        raise TreasuryError(
            ErrorCode.ROLE_NOT_HELD,
            f"You do not have scope for {code}. Ask an administrator to grant you access.",
            field="legal_entity_id",
        )


def list_entities(session: Session, tenant_id: str) -> list[LegalEntity]:
    return list(
        session.scalars(
            select(LegalEntity)
            .where(LegalEntity.tenant_id == tenant_id)
            .order_by(LegalEntity.code)
        )
    )


def replace_scope(
    session: Session,
    tenant_id: str,
    user_id: str,
    target: UserScope,
    granter: str,
) -> UserScope:
    """Set the user's live scope to exactly `target`.

    Revokes rows that aren't in the target (never deletes — evidence
    trail). Adds rows for entities not currently held. Group-wide is a
    single sentinel row with legal_entity_id = NULL.
    """
    current = scope_for_user(session, user_id)

    # Case A: target is group-wide.
    if target.group_wide:
        # Revoke every specific-entity row (they're subsumed).
        _revoke_specific(session, user_id)
        if not current.group_wide:
            _add_row(session, tenant_id, user_id, None, granter)
        session.flush()
        return scope_for_user(session, user_id)

    # Case B: target is a specific subset.
    # Revoke the group-wide row if it was there.
    if current.group_wide:
        _revoke_group_wide(session, user_id)
    # Revoke entities that fall out of the target.
    to_revoke = [e for e in current.entity_ids if e not in target.entity_ids]
    for eid in to_revoke:
        _revoke_entity(session, user_id, eid)
    # Add entities that came in.
    have = set() if current.group_wide else set(current.entity_ids)
    for eid in target.entity_ids:
        if eid not in have:
            _add_row(session, tenant_id, user_id, eid, granter)
    session.flush()
    return scope_for_user(session, user_id)


def _add_row(session, tenant_id, user_id, entity_id, granter) -> None:
    session.add(
        UserEntityScope(
            id=new_id("scp"),
            tenant_id=tenant_id,
            user_id=user_id,
            legal_entity_id=entity_id,
            granted_by=granter,
            granted_at=now(),
        )
    )


def _revoke_specific(session, user_id) -> None:
    for row in session.scalars(
        select(UserEntityScope)
        .where(UserEntityScope.user_id == user_id)
        .where(UserEntityScope.revoked_at.is_(None))
        .where(UserEntityScope.legal_entity_id.is_not(None))
    ):
        row.revoked_at = now()


def _revoke_group_wide(session, user_id) -> None:
    for row in session.scalars(
        select(UserEntityScope)
        .where(UserEntityScope.user_id == user_id)
        .where(UserEntityScope.revoked_at.is_(None))
        .where(UserEntityScope.legal_entity_id.is_(None))
    ):
        row.revoked_at = now()


def _revoke_entity(session, user_id, entity_id) -> None:
    for row in session.scalars(
        select(UserEntityScope)
        .where(UserEntityScope.user_id == user_id)
        .where(UserEntityScope.revoked_at.is_(None))
        .where(UserEntityScope.legal_entity_id == entity_id)
    ):
        row.revoked_at = now()
