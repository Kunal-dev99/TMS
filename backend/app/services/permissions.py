"""Permission matrix — the plain-English answer to 'what may this user do?'.

Roles are opaque labels ('ANALYST', 'CFO'); permissions are the specific
actions the system gates on. A role holds a set of permissions; a user
holds a set of roles. Effective permissions = union of role permissions.

Enterprise treasury tools (Treasury Systems, Nomentia, TIS) split
'managing access' from 'financial authority' from 'reading the trail'.
The matrix here follows that shape. This is the source of truth: the
Admin page reads it to render 'Can propose deposits · Cannot approve';
the backend reads it via `require_permission()` to gate endpoints.

Recorded as ADR-0011.
"""

from __future__ import annotations

from enum import Enum


class Permission(str, Enum):
    # Read
    VIEW_BOOK = "view.book"
    VIEW_EXPOSURE = "view.exposure"
    VIEW_AUDIT = "view.audit"

    # Dealing lifecycle
    PROPOSE_DEAL = "deal.propose"
    APPROVE_DEAL = "deal.approve"
    BOOK_DEAL = "deal.book"
    OVERRIDE_CHECKS = "deal.override"

    # Hedging (a subset of dealing but often scoped differently)
    INITIATE_HEDGE = "hedge.initiate"

    # Policy & configuration
    CHANGE_INVESTMENT_POLICY = "policy.investment.change"
    CHANGE_FX_POLICY = "policy.fx.change"
    CHANGE_SYSTEM_POLICY = "policy.system.change"
    CHANGE_COUNTERPARTY = "counterparty.change"

    # Data export
    EXPORT_DATA = "export.data"

    # Administration
    MANAGE_USERS = "admin.users"
    MANAGE_ROLES = "admin.roles"
    MANAGE_TENANT = "admin.tenant"


# ---------------------------------------------------------- role catalogue
#
# Each role → the set of permissions it grants. A user's effective
# permissions are the union of the sets from every role they hold.
#
# Design notes matching the enterprise-treasury pattern:
#
#   * ADMIN can manage people and roles but does NOT get automatic
#     dealing / approval authority (Treasury Systems: "removing the
#     unrestricted 'Everything' role after implementation" is exactly
#     this principle).
#   * COMPLIANCE_OFFICER is read-only across the audit trail; never
#     mutates the book.
#   * ANALYST / HEAD_OF_TREASURY / CFO are financial authority ladder —
#     CFO inherits everything the Head has plus override powers.
#   * OPERATOR runs the day-to-day but cannot sign.
#   * AUDITOR is read-only external.

ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    "ADMIN": {
        Permission.VIEW_BOOK,
        Permission.VIEW_EXPOSURE,
        Permission.VIEW_AUDIT,
        Permission.MANAGE_USERS,
        Permission.MANAGE_ROLES,
        Permission.MANAGE_TENANT,
    },
    "COMPLIANCE_OFFICER": {
        Permission.VIEW_BOOK,
        Permission.VIEW_EXPOSURE,
        Permission.VIEW_AUDIT,
        Permission.EXPORT_DATA,
    },
    "CFO": {
        Permission.VIEW_BOOK,
        Permission.VIEW_EXPOSURE,
        Permission.VIEW_AUDIT,
        Permission.PROPOSE_DEAL,
        Permission.APPROVE_DEAL,
        Permission.BOOK_DEAL,
        Permission.OVERRIDE_CHECKS,
        Permission.INITIATE_HEDGE,
        Permission.CHANGE_INVESTMENT_POLICY,
        Permission.CHANGE_FX_POLICY,
        Permission.CHANGE_SYSTEM_POLICY,
        Permission.CHANGE_COUNTERPARTY,
        Permission.EXPORT_DATA,
    },
    "HEAD_OF_TREASURY": {
        Permission.VIEW_BOOK,
        Permission.VIEW_EXPOSURE,
        Permission.VIEW_AUDIT,
        Permission.PROPOSE_DEAL,
        Permission.APPROVE_DEAL,
        Permission.BOOK_DEAL,
        Permission.INITIATE_HEDGE,
        Permission.CHANGE_INVESTMENT_POLICY,
        Permission.CHANGE_FX_POLICY,
        Permission.CHANGE_COUNTERPARTY,
        Permission.EXPORT_DATA,
    },
    "ANALYST": {
        Permission.VIEW_BOOK,
        Permission.VIEW_EXPOSURE,
        Permission.PROPOSE_DEAL,
        Permission.INITIATE_HEDGE,
    },
    "OPERATOR": {
        Permission.VIEW_BOOK,
        Permission.VIEW_EXPOSURE,
    },
    "AUDITOR": {
        Permission.VIEW_BOOK,
        Permission.VIEW_EXPOSURE,
        Permission.VIEW_AUDIT,
        Permission.EXPORT_DATA,
    },
}


# ---------------------------------------------------------- descriptions
#
# One short plain-English line per permission. The Admin page displays
# these to explain what a role does, alongside "Can / Cannot" prefixes.

PERMISSION_LABEL: dict[Permission, str] = {
    Permission.VIEW_BOOK: "view the deal book",
    Permission.VIEW_EXPOSURE: "view exposure and hedging",
    Permission.VIEW_AUDIT: "read the audit trail",
    Permission.PROPOSE_DEAL: "propose deposits",
    Permission.APPROVE_DEAL: "approve proposed deals",
    Permission.BOOK_DEAL: "book approved deals",
    Permission.OVERRIDE_CHECKS: "override a failed check with a reason",
    Permission.INITIATE_HEDGE: "initiate FX forward hedges",
    Permission.CHANGE_INVESTMENT_POLICY: "edit investment principles",
    Permission.CHANGE_FX_POLICY: "edit FX hedge policy",
    Permission.CHANGE_SYSTEM_POLICY: "edit the system policy (six-check enforcement)",
    Permission.CHANGE_COUNTERPARTY: "add or amend counterparties and limits",
    Permission.EXPORT_DATA: "export data (CSV, PDF)",
    Permission.MANAGE_USERS: "invite, edit and suspend users",
    Permission.MANAGE_ROLES: "grant and revoke roles",
    Permission.MANAGE_TENANT: "change tenant/workspace settings",
}


# ---------------------------------------------------------- helpers


def permissions_for_role(role: str) -> set[Permission]:
    return ROLE_PERMISSIONS.get(role, set())


def permissions_for_roles(roles: list[str]) -> set[Permission]:
    out: set[Permission] = set()
    for role in roles:
        out |= permissions_for_role(role)
    return out


def has_permission(roles: list[str], perm: Permission) -> bool:
    return perm in permissions_for_roles(roles)


def summarise_permissions(roles: list[str]) -> dict:
    """Machine + human friendly summary for the Admin page.

    Returns:
      {
        "held": ["deal.propose", ...],          # sorted, unique
        "can":  ["propose deposits", ...],      # plain English, sorted
        "cannot": ["approve proposed deals", ...],
      }
    """
    held = permissions_for_roles(roles)
    all_perms = list(Permission)
    can = sorted(PERMISSION_LABEL[p] for p in all_perms if p in held)
    cannot = sorted(PERMISSION_LABEL[p] for p in all_perms if p not in held)
    return {
        "held": sorted(p.value for p in held),
        "can": can,
        "cannot": cannot,
    }
