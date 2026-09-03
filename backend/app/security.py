"""Passwords and bearer tokens.

Deliberately small. Document 4 names Entra ID single sign on as the
destination for all three systems, so everything here is the thing that
holds until that arrives, and none of it should grow.

Two choices worth stating.

Passwords use PBKDF2 from the standard library rather than bcrypt or argon2.
Not because it is better, but because adding a native dependency to a
prototype that will be replaced by single sign on buys nothing. The
iteration count is high enough to be honest and the cost is paid once per
sign in.

Tokens are signed rather than stored. A session table would be a third table
in a phase the plan budgets at two, and a stateless token needs no lookup on
the request path, which the eighty millisecond check budget cares about.
The cost is that a token cannot be revoked before it expires. That is the
right trade for a prototype and the wrong one for a product, and it goes
away with single sign on rather than being fixed here.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from app import config  # noqa: F401  reads .env before the secret is read

PBKDF2_ROUNDS = 240_000
TOKEN_TTL_SECONDS = 12 * 60 * 60

#: The signing key. An environment variable in anything that is not a
#: developer's machine. The fallback exists so the prototype starts with no
#: setup, and it is not a secret: a token signed with it is worth nothing
#: outside a laptop.
_DEV_SECRET = "treasury-register-development-only"
SECRET = os.environ.get("TREASURY_TOKEN_SECRET", _DEV_SECRET)
USING_DEV_SECRET = SECRET == _DEV_SECRET


def hash_password(password: str) -> str:
    """Returns salt and hash together, so the row carries everything needed
    to verify it and nothing else has to be looked up."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Compared in constant time.

    A plain equality check leaks how much of the hash matched through how
    long it took to say no, which is enough to reconstruct one over many
    attempts.
    """
    try:
        algorithm, rounds, salt_hex, expected = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
    )
    return hmac.compare_digest(digest.hex(), expected)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_token(user_id: str, tenant_id: str, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    payload = {
        "sub": user_id,
        "ten": tenant_id,
        "exp": int(time.time()) + ttl_seconds,
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(signature)}"


def read_token(token: str) -> dict | None:
    """The payload, or None. Never raises, and never trusts the payload
    before the signature has been checked."""
    try:
        body, signature = token.split(".")
    except ValueError:
        return None

    expected = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(_unb64(signature), expected):
        return None

    try:
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict) or payload.get("exp", 0) < time.time():
        return None
    return payload
