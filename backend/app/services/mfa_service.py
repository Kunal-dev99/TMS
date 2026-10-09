"""TOTP MFA — secret generation, encryption, verification, recovery codes.

Storage: ``user_mfa_secret`` (one row per enrolled user) and
``mfa_recovery_code`` (10 rows per enrolled user, one-shot).

Encryption at rest: Fernet symmetric cipher. The master key is read
through SecretsPort under the name ``mfa_master_key`` (ADR-0024). A
deployment without the key cannot enroll — ``generate_secret`` and
``verify_code`` raise ``MfaKeyUnavailable``. Fail-closed.

Verification: ``pyotp.TOTP(secret).verify(code, valid_window=1)`` so a
code from the previous or next 30-second window is accepted (handles
clock skew). Replay-protection is NOT implemented here — a code can
be re-used within its window. That's fine for enrollment but Phase 3's
``/auth/mfa/consume`` adds a short-TTL ``mfa_last_consumed_at`` guard.

Recovery codes: 10 codes per enrollment, format ``XXXX-XXXX-XXXX``
(uppercase alphanumeric, dashes for readability). Shown ONCE at
issuance; stored as sha256 hex hashes. Consuming a recovery code
flips ``consumed_at`` and MUST also mark the TOTP session verified.
Re-issuing recovery codes supersedes the old set (old rows get
``consumed_at`` set to the re-issuance timestamp).
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connector import ports, registry
from app.models import MfaRecoveryCode, UserMfaSecret


MFA_KEY_NAME = "mfa_master_key"
RECOVERY_CODES_PER_ENROLLMENT = 10
TOTP_ISSUER = "Treasury Register"


class MfaKeyUnavailable(RuntimeError):
    """Raised when SecretsPort cannot supply the mfa_master_key.

    A caller translates this to a 503 at the API edge so a deployment
    that forgot to configure the key gets a loud, actionable error
    rather than a silent crash.
    """


class MfaNotEnrolled(RuntimeError):
    """verify_code / consume_recovery_code called for a user with no secret."""


@dataclass(frozen=True)
class EnrollmentResult:
    secret: str              # base32 TOTP secret — DO NOT STORE
    provisioning_uri: str    # otpauth:// URI for a QR code


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    was_first_verification: bool  # True on the enrollment-completing code


# --- key management --------------------------------------------------------


def _fernet() -> Fernet:
    """Build a Fernet from the SecretsPort key. Raises MfaKeyUnavailable."""
    secrets_port = registry.get(ports.SecretsPort)
    key = secrets_port.get(MFA_KEY_NAME)
    if not key:
        raise MfaKeyUnavailable(
            f"SecretsPort has no value for '{MFA_KEY_NAME}'. "
            "MFA cannot be enrolled or verified until it is set."
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as e:
        raise MfaKeyUnavailable(
            f"'{MFA_KEY_NAME}' is not a valid Fernet key "
            "(need a 32-byte url-safe base64 string). Rotate it."
        ) from e


def generate_master_key() -> str:
    """Operator helper — emits a new Fernet-ready key for the vault.

    Not called by the application; shown in docs/MFA_SETUP.md.
    """
    return Fernet.generate_key().decode()


# --- enrollment ------------------------------------------------------------


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def generate_secret(
    session: Session, user_id: str, user_email: str
) -> EnrollmentResult:
    """Create a fresh TOTP secret for the user, store it encrypted,
    return the plaintext secret + provisioning URI for QR display.

    Idempotent-ish: if the user already has a secret but it is NOT yet
    verified (verified_at IS NULL), the row is replaced. If the user has
    a verified secret, raises ValueError — call ``reset_enrollment``
    first.
    """
    fernet = _fernet()  # raises MfaKeyUnavailable at the edge

    existing = session.get(UserMfaSecret, user_id)
    if existing and existing.verified_at:
        raise ValueError(
            "User already has a verified MFA enrollment. "
            "Call reset_enrollment() before issuing a new secret."
        )

    secret = pyotp.random_base32()
    ciphertext = fernet.encrypt(secret.encode()).decode()

    if existing:
        existing.secret_encrypted = ciphertext
        existing.created_at = _now_utc()
        existing.verified_at = None
        existing.last_used_at = None
    else:
        session.add(
            UserMfaSecret(
                user_id=user_id,
                secret_encrypted=ciphertext,
                created_at=_now_utc(),
            )
        )
    session.flush()

    provisioning = pyotp.TOTP(secret).provisioning_uri(
        name=user_email, issuer_name=TOTP_ISSUER
    )
    return EnrollmentResult(secret=secret, provisioning_uri=provisioning)


def reset_enrollment(session: Session, user_id: str) -> None:
    """Operator-level reset: drops the user's secret + any recovery
    codes. Next enroll call starts fresh. Caller is responsible for
    the audit event + four-eye flow (ADR-0015 pattern)."""
    row = session.get(UserMfaSecret, user_id)
    if row is not None:
        session.delete(row)
    session.execute(
        MfaRecoveryCode.__table__.delete().where(
            MfaRecoveryCode.user_id == user_id
        )
    )
    session.flush()


# --- verification ----------------------------------------------------------


def verify_code(
    session: Session, user_id: str, code: str
) -> VerificationResult:
    """Validate a TOTP code. Flips verified_at on the first success."""
    row = session.get(UserMfaSecret, user_id)
    if row is None:
        raise MfaNotEnrolled(f"User {user_id} has no MFA secret.")

    fernet = _fernet()
    try:
        secret = fernet.decrypt(row.secret_encrypted.encode()).decode()
    except InvalidToken as e:
        raise MfaKeyUnavailable(
            "Stored MFA secret cannot be decrypted. "
            "The mfa_master_key likely changed since enrollment."
        ) from e

    ok = pyotp.TOTP(secret).verify(code, valid_window=1)
    if not ok:
        return VerificationResult(verified=False, was_first_verification=False)

    was_first = row.verified_at is None
    now = _now_utc()
    row.last_used_at = now
    if was_first:
        row.verified_at = now
    session.flush()
    return VerificationResult(verified=True, was_first_verification=was_first)


# --- recovery codes --------------------------------------------------------


def _format_recovery_code() -> str:
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # drop I,L,O,0,1 — ambiguous
    chunks = [
        "".join(secrets.choice(alphabet) for _ in range(4))
        for _ in range(3)
    ]
    return "-".join(chunks)


def _hash_recovery_code(code: str) -> str:
    # sha256 hex — recovery codes are high-entropy already (120 bits),
    # so a work-factor KDF (bcrypt/argon2) is overkill. A plain hash
    # is sufficient and fast enough for the verify path.
    return hashlib.sha256(code.encode()).hexdigest()


def issue_recovery_codes(
    session: Session, user_id: str, count: int = RECOVERY_CODES_PER_ENROLLMENT
) -> list[str]:
    """Mint ``count`` fresh codes; mark any previous unused ones as
    consumed (supersession). Returns the plaintext codes — the caller
    MUST surface them to the user exactly once and never again."""
    now = _now_utc()
    # Supersede any live ones.
    session.execute(
        MfaRecoveryCode.__table__.update()
        .where(MfaRecoveryCode.user_id == user_id)
        .where(MfaRecoveryCode.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    codes: list[str] = []
    for _ in range(count):
        code = _format_recovery_code()
        session.add(
            MfaRecoveryCode(
                id=f"mrc_{uuid.uuid4().hex[:16]}",
                user_id=user_id,
                code_hash=_hash_recovery_code(code),
                created_at=now,
            )
        )
        codes.append(code)
    session.flush()
    return codes


def consume_recovery_code(
    session: Session, user_id: str, code: str
) -> bool:
    """Spend a recovery code. Returns True if it was valid + unused.

    Also marks the user's MFA session as verified by stamping
    last_used_at on user_mfa_secret so callers can rely on the same
    "proof of possession" surface as a TOTP success. Does NOT flip
    verified_at — a user who hasn't completed first-time TOTP
    verification can't skip it with a recovery code.
    """
    normalised = code.strip().upper()
    code_hash = _hash_recovery_code(normalised)
    row = session.scalars(
        select(MfaRecoveryCode)
        .where(MfaRecoveryCode.user_id == user_id)
        .where(MfaRecoveryCode.code_hash == code_hash)
        .where(MfaRecoveryCode.consumed_at.is_(None))
    ).one_or_none()
    if row is None:
        return False
    now = _now_utc()
    row.consumed_at = now
    secret_row = session.get(UserMfaSecret, user_id)
    if secret_row is not None:
        secret_row.last_used_at = now
    session.flush()
    return True


# --- query helpers --------------------------------------------------------


def is_enrolled(session: Session, user_id: str) -> bool:
    """True iff the user has a verified secret. An unverified row
    counts as 'not enrolled' for enforcement purposes (Phase 4)."""
    row = session.get(UserMfaSecret, user_id)
    return row is not None and row.verified_at is not None


def enrollment_status(session: Session, user_id: str) -> dict:
    """Compact dict for the admin surface + the user's own profile."""
    row = session.get(UserMfaSecret, user_id)
    if row is None:
        return {"enrolled": False, "verified_at": None, "last_used_at": None}
    remaining = session.scalar(
        select(MfaRecoveryCode.id)
        .where(MfaRecoveryCode.user_id == user_id)
        .where(MfaRecoveryCode.consumed_at.is_(None))
        .limit(1)
    )
    return {
        "enrolled": row.verified_at is not None,
        "verified_at": row.verified_at,
        "last_used_at": row.last_used_at,
        "has_recovery_codes": remaining is not None,
    }
