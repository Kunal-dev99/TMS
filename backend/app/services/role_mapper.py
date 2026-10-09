"""IdP group claims -> project Role, per-tenant.

A real customer configures their own mapping in ``sso_group_map`` —
rows of (tenant_id, group_claim, role). This service reads them,
nothing more. There are no mappings seeded today; a call returns an
empty set, which is the fail-closed default: the SSO caller gets no
roles and therefore no access until an admin explicitly maps a group.

Separate module from permissions.py because the shape "groups ->
roles" is specific to the SSO flow; the local-password flow uses
``membership`` rows directly.
"""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SsoGroupMap


def roles_for_groups(
    session: Session,
    tenant_id: str,
    groups: Iterable[str],
) -> set[str]:
    """Return the set of role strings this tenant maps the given groups onto.

    Case-sensitive on the claim string, matching the IdP's exact
    casing. A group with no mapping contributes nothing (fail-closed).
    """
    group_list = [g for g in groups if g]
    if not group_list:
        return set()
    rows = session.scalars(
        select(SsoGroupMap)
        .where(SsoGroupMap.tenant_id == tenant_id)
        .where(SsoGroupMap.group_claim.in_(group_list))
    ).all()
    return {row.role for row in rows}
