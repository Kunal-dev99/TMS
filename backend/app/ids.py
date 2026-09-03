"""Identifiers.

Text, prefixed, with a random suffix. Readable on screen and in a log,
stable across a database move, and there is no sequence to reset when the
book is reseeded.

The suffix is from `secrets` rather than `random`, not because an identifier
is a secret, but because a predictable identifier in a URL is a way to
enumerate other people's records the day this has more than one tenant.
"""

import secrets
from datetime import datetime, timezone

ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def new_id(prefix: str, length: int = 10) -> str:
    suffix = "".join(secrets.choice(ALPHABET) for _ in range(length))
    return f"{prefix}_{suffix}"


def now() -> str:
    """An event timestamp. ISO 8601 text, seconds resolution in this build."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
