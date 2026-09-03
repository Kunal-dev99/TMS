"""Who is calling.

The whole of phase 1.5 in one idea: the actor comes from the token and never
from the request body. Every service already recorded who acted, so nothing
downstream of here changed when this arrived.

A Principal is the thing services are handed instead of a string. It carries
an identifier that is a foreign key rather than a name somebody typed, which
is what turns an evidence record from a claim into a fact.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.errors import ErrorCode, TreasuryError
from app.repo import users as user_repo
from app.security import issue_token, read_token, verify_password


@dataclass(frozen=True)
class Principal:
    """The caller. Never constructed from anything a client sent."""

    user_id: str
    tenant_id: str
    display_name: str
    email: str
    roles: list[str] = field(default_factory=list)

    def holds(self, role: str) -> bool:
        return role in self.roles

    def __str__(self) -> str:
        """What goes into an evidence field that is still text.

        The identifier is what matters and it is recorded alongside; the name
        is here so a limit approval reads as a person rather than as a
        primary key.
        """
        return self.display_name


class IdentityService:
    def __init__(self, session: Session, tenant_id: str) -> None:
        self.session = session
        self.tenant_id = tenant_id

    def sign_in(self, email: str, password: str) -> tuple[Principal, str]:
        """One refusal for a wrong address and a wrong password alike.

        Saying which of the two was wrong tells somebody who is guessing
        which half they have right.
        """
        user = user_repo.by_email(self.session, self.tenant_id, email)
        if user is None or not verify_password(password, user.password_hash):
            raise TreasuryError(
                ErrorCode.NOT_AUTHENTICATED,
                "That email address and password do not match an account.",
            )
        if user.status != "ACTIVE":
            raise TreasuryError(
                ErrorCode.NOT_AUTHENTICATED, "That account has been disabled."
            )

        principal = self._principal(user)
        return principal, issue_token(user.id, self.tenant_id)

    def from_token(self, token: str) -> Principal:
        payload = read_token(token)
        if payload is None:
            raise TreasuryError(
                ErrorCode.NOT_AUTHENTICATED,
                "That session has expired or the token is not valid. Sign in again.",
            )
        user = user_repo.get(self.session, payload["sub"])
        if user is None or user.status != "ACTIVE" or user.tenant_id != payload["ten"]:
            raise TreasuryError(
                ErrorCode.NOT_AUTHENTICATED, "That account is no longer active."
            )
        return self._principal(user)

    def _principal(self, user) -> Principal:
        return Principal(
            user_id=user.id,
            tenant_id=user.tenant_id,
            display_name=user.display_name,
            email=user.email,
            roles=user_repo.roles(self.session, user.id),
        )
