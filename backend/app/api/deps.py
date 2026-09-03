"""What every router needs before it can call a service.

One session per request, yielded and closed by a dependency. One tenant, one
clock date and one policy version, resolved once and handed to the services
so that every figure in a response was measured against the same world.

Resolving the policy here rather than inside each service is what lets a
re-derivation hand a historic version to the same code.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ErrorCode, TreasuryError
from app.models import PolicyVersion, Tenant
from app.repo import policy as policy_repo
from app.services.identity_service import IdentityService, Principal


@dataclass
class Context:
    session: Session
    tenant_id: str
    tenant_name: str
    as_of_date: str
    policy: PolicyVersion


def get_context(session: Annotated[Session, Depends(get_session)]) -> Context:
    """The single seeded tenant.

    tenant_id is on every operational table already and is never queried
    differently, so phase four turns this into a lookup from the caller's
    token without touching a service.
    """
    tenant = session.query(Tenant).first()
    if tenant is None:
        raise TreasuryError(
            ErrorCode.CHECK_INPUTS_UNAVAILABLE,
            "No tenant has been seeded. Run the seed before starting the API.",
        )

    as_of = policy_repo.today(session, tenant.id)
    if as_of is None:
        raise TreasuryError(
            ErrorCode.CHECK_INPUTS_UNAVAILABLE,
            "The system clock has not been set, so nothing can be measured as of "
            "a date.",
        )

    policy = policy_repo.current_policy(session, tenant.id)
    if policy is None:
        # Fails closed. Without a policy there are no thresholds, no cap and
        # no enforcement setting, and guessing any of them would be inventing
        # a control.
        raise TreasuryError(
            ErrorCode.CHECK_INPUTS_UNAVAILABLE,
            "No treasury policy is in force, so no deal can be tested.",
        )

    return Context(
        session=session,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        as_of_date=as_of,
        policy=policy,
    )


Ctx = Annotated[Context, Depends(get_context)]


def get_principal(
    ctx: Ctx,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """The caller, from the bearer token and from nowhere else.

    This is the whole of phase 1.5 at the transport boundary. No endpoint
    takes an actor in its body any more, so there is no path by which a
    client can name somebody other than itself.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise TreasuryError(
            ErrorCode.NOT_AUTHENTICATED,
            "This endpoint needs a bearer token. Sign in first.",
        )
    token = authorization.split(" ", 1)[1].strip()
    return IdentityService(ctx.session, ctx.tenant_id).from_token(token)


Caller = Annotated[Principal, Depends(get_principal)]
