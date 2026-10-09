"""MFA endpoints — enroll, verify first code, re-issue recovery codes.

All endpoints require an already-signed-in caller. Enrollment is
opt-in; nothing is enforced until Phase 4's per-tenant policy. The
local-password flow stays the sole way to get a bearer token today.

- POST /auth/mfa/enroll   — mint a secret + provisioning URI + QR
- POST /auth/mfa/verify   — submit first TOTP code to complete enrollment
- POST /auth/mfa/recovery/reissue — mint a fresh set of recovery codes
- GET  /auth/mfa/status   — compact status for the user's profile UI
"""
from __future__ import annotations

import base64
import io
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import Caller, Ctx
from app.services import mfa_service
from app.services import rate_limit as rl


router = APIRouter(tags=["MFA"])


# Rate-limit policies live here so they're colocated with the endpoints.
# Keep them conservative — brute-forcing a 6-digit TOTP needs attempts.
MFA_VERIFY = rl.LimitPolicy(name="mfa.verify", max_requests=10, window_seconds=60)
MFA_ENROLL = rl.LimitPolicy(name="mfa.enroll", max_requests=5, window_seconds=60)
MFA_CONSUME = rl.LimitPolicy(name="mfa.consume", max_requests=10, window_seconds=60)


def _render_qr_data_url(uri: str) -> str | None:
    """Render the provisioning URI as a base64 PNG data URL.

    Optional — if ``qrcode`` isn't installed the response just carries
    the URI and the client renders its own QR. The URI alone is enough
    for an authenticator app that supports pasting.
    """
    try:
        import qrcode  # type: ignore[import-not-found]
    except ImportError:
        return None
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


@router.post(
    "/auth/mfa/enroll",
    dependencies=[Depends(rl.limit_by_user(MFA_ENROLL))],
)
def enroll(ctx: Ctx, caller: Caller) -> dict[str, Any]:
    """Start MFA enrollment. Returns the secret + provisioning URI.

    The caller shows the URI as a QR code to the user; the user scans
    it with their authenticator; the user then calls /auth/mfa/verify
    with the first code the authenticator shows. verified_at populates
    on that second call.
    """
    try:
        from app.repo import users as users_repo

        user = users_repo.get(ctx.session, caller.user_id)
        email = user.email if user is not None else caller.user_id

        result = mfa_service.generate_secret(
            ctx.session, caller.user_id, email
        )
    except mfa_service.MfaKeyUnavailable as e:
        # 503 — operational problem, not a client bug.
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    ctx.session.commit()
    qr_data_url = _render_qr_data_url(result.provisioning_uri)
    return {
        "secret": result.secret,
        "provisioning_uri": result.provisioning_uri,
        "qr_data_url": qr_data_url,
    }


@router.post(
    "/auth/mfa/verify",
    dependencies=[Depends(rl.limit_by_user(MFA_VERIFY))],
)
def verify(body: dict, ctx: Ctx, caller: Caller) -> dict[str, Any]:
    """Submit a TOTP code. First success completes enrollment and
    issues 10 recovery codes (returned once).
    """
    code = str(body.get("code", "")).strip()
    if not code:
        raise HTTPException(status_code=400, detail="code is required.")

    try:
        result = mfa_service.verify_code(ctx.session, caller.user_id, code)
    except mfa_service.MfaNotEnrolled:
        raise HTTPException(
            status_code=400,
            detail="No MFA enrollment in progress. Call /auth/mfa/enroll first.",
        )
    except mfa_service.MfaKeyUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    if not result.verified:
        raise HTTPException(
            status_code=400,
            detail="That code didn't match. Check the time on your device and try again.",
        )

    recovery_codes: list[str] = []
    if result.was_first_verification:
        recovery_codes = mfa_service.issue_recovery_codes(
            ctx.session, caller.user_id
        )
    ctx.session.commit()
    return {
        "verified": True,
        "was_first_verification": result.was_first_verification,
        "recovery_codes": recovery_codes,
    }


@router.post(
    "/auth/mfa/recovery/reissue",
    dependencies=[Depends(rl.limit_by_user(MFA_ENROLL))],
)
def reissue_recovery_codes(ctx: Ctx, caller: Caller) -> dict[str, Any]:
    """Mint a fresh set of recovery codes; the old ones stop working."""
    codes = mfa_service.issue_recovery_codes(ctx.session, caller.user_id)
    ctx.session.commit()
    return {"recovery_codes": codes}


@router.post(
    "/auth/mfa/consume",
    dependencies=[Depends(rl.limit_by_user(MFA_CONSUME))],
)
def consume(body: dict, ctx: Ctx, caller: Caller) -> dict[str, Any]:
    """Prove possession of a second factor; reissue the bearer with mfa=true.

    Accepts EITHER a 6-digit TOTP code OR a recovery code (XXXX-XXXX-XXXX).
    On success, returns a fresh token that will clear the require_mfa
    dependency for the rest of the session (12h). The current token the
    client used to call this endpoint stays technically valid until it
    expires — but it still has mfa=false, so re-use buys nothing on a
    gated endpoint.
    """
    from app.security import issue_token

    code = str(body.get("code", "")).strip()
    if not code:
        raise HTTPException(status_code=400, detail="code is required.")

    verified = False

    # TOTP shape = 6 digits; recovery = XXXX-XXXX-XXXX. Try the one that
    # matches the shape first; fall back to the other if the user pasted
    # something that doesn't match our regex guess (we don't want to
    # refuse a legitimate code because of a shape heuristic).
    looks_like_totp = code.isdigit() and len(code) == 6
    try:
        if looks_like_totp:
            result = mfa_service.verify_code(ctx.session, caller.user_id, code)
            verified = result.verified
            if not verified:
                verified = mfa_service.consume_recovery_code(
                    ctx.session, caller.user_id, code
                )
        else:
            verified = mfa_service.consume_recovery_code(
                ctx.session, caller.user_id, code
            )
            if not verified:
                result = mfa_service.verify_code(ctx.session, caller.user_id, code)
                verified = result.verified
    except mfa_service.MfaNotEnrolled:
        raise HTTPException(
            status_code=400,
            detail="No MFA enrollment on this account. Call /auth/mfa/enroll first.",
        )
    except mfa_service.MfaKeyUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    if not verified:
        raise HTTPException(
            status_code=400,
            detail="That code didn't match. Check the time on your device and try again.",
        )

    ctx.session.commit()
    new_token = issue_token(
        caller.user_id, caller.tenant_id, mfa_passed=True,
    )
    return {"token": new_token, "mfa_passed": True}


@router.get("/auth/mfa/status")
def status(ctx: Ctx, caller: Caller) -> dict[str, Any]:
    """Compact enrollment status for the user's own profile UI."""
    return mfa_service.enrollment_status(ctx.session, caller.user_id)
