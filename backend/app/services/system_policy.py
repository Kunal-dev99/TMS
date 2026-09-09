"""System policy - everything the treasurer can twist that isn't
investment-principle-shaped and isn't accounting-events-shaped.

Four things live here:
  - Concentration cap (bp of portfolio).
  - Enforcement mode (WARN_WITH_OVERRIDE / HARD_BLOCK).
  - Rating bands (max limit and max tenor per rating).
  - Rate curve (bp per rating per tenor).

The first three are stored in the DB (PolicyVersion + RatingBand).
The rate curve lives in an in-memory singleton for the prototype,
matching the pattern used by planner_settings and accounting_events.

Every field the UI shows also names its source. The "audit trail" for
the prototype's in-place update is documented; production would
supersede the current PolicyVersion and create a new one on save.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from sqlalchemy.orm import Session

from app.models import PolicyVersion, RatingBand
from app.services.planner_settings import RATING_LADDER


# --------------------------------------------------------------------- rate curve

# Default rate curve. Mirrors the one in planner_service._RATE_CURVE so
# on first read the numbers match what the planner uses. Once the
# treasurer edits and saves, the singleton overrides.
_DEFAULT_RATE_CURVE: dict[str, dict[int, int]] = {
    "AAA":  {3: 385, 6: 395, 12: 405, 24: 415},
    "AA+":  {3: 390, 6: 400, 12: 410, 24: 420},
    "AA":   {3: 395, 6: 405, 12: 415, 24: 425},
    "AA-":  {3: 400, 6: 410, 12: 420, 24: 430},
    "A+":   {3: 405, 6: 415, 12: 425, 24: 435},
    "A":    {3: 410, 6: 420, 12: 430, 24: 440},
    "A-":   {3: 405, 6: 415, 12: 430, 24: 445},
    "BBB+": {3: 415, 6: 425, 12: 435, 24: 450},
    "BBB":  {3: 420, 6: 430, 12: 445, 24: 460},
    "BBB-": {3: 425, 6: 440, 12: 460, 24: 480},
}

# Tenors the UI edits. Values in the curve for other tenors are
# interpolated by nearest-tenor when planner asks for them.
CURVE_TENORS: list[int] = [3, 6, 12, 24]


@dataclass
class RateCurveSettings:
    curve: dict[str, dict[int, int]] = field(
        default_factory=lambda: {r: dict(t) for r, t in _DEFAULT_RATE_CURVE.items()}
    )


_lock = Lock()
_rate_curve = RateCurveSettings()


def get_rate_curve() -> dict[str, dict[int, int]]:
    """The effective curve. Callers get a deep copy so they don't mutate."""
    with _lock:
        return {r: dict(t) for r, t in _rate_curve.curve.items()}


def update_rate_curve(patch: dict[str, dict[str, Any]]) -> dict[str, dict[int, int]]:
    """Merge a partial curve update into the singleton.

    Accepts the same shape the API sends: {rating: {tenor_str: bp}}.
    """
    global _rate_curve
    with _lock:
        new = {r: dict(t) for r, t in _rate_curve.curve.items()}
        for rating, tenors in (patch or {}).items():
            if rating not in RATING_LADDER:
                continue
            existing = new.setdefault(rating, {})
            for tenor_key, value in (tenors or {}).items():
                try:
                    tenor = int(tenor_key)
                    bp = max(0, min(2000, int(value)))
                except (TypeError, ValueError):
                    continue
                existing[tenor] = bp
        _rate_curve = RateCurveSettings(curve=new)
        return {r: dict(t) for r, t in _rate_curve.curve.items()}


def reset_rate_curve() -> dict[str, dict[int, int]]:
    global _rate_curve
    with _lock:
        _rate_curve = RateCurveSettings()
        return {r: dict(t) for r, t in _rate_curve.curve.items()}


# --------------------------------------------------------------------- read

def as_dict(session: Session, tenant_id: str) -> dict[str, Any]:
    policy = _current_policy(session, tenant_id)
    bands = _current_bands(session, tenant_id)
    curve = get_rate_curve()
    return {
        "policy": {
            "concentration_cap_bp": policy.concentration_cap_bp,
            "enforcement": policy.enforcement,
            "threshold_analyst_pence": policy.threshold_analyst_pence,
            "threshold_hot_pence": policy.threshold_hot_pence,
            "fx_add_on_bp": policy.fx_add_on_bp,
        },
        "rating_bands": [
            {
                "rating": b.rating,
                "ordinal": b.ordinal,
                "max_limit_pence": b.max_limit_pence,
                "max_tenor_months": b.max_tenor_months,
            }
            for b in bands
        ],
        "rate_curve": {
            rating: {str(t): bp for t, bp in tenors.items()}
            for rating, tenors in curve.items()
        },
        "curve_tenors": CURVE_TENORS,
        "rating_ladder": RATING_LADDER,
        "sources": _sources_catalogue(),
    }


# --------------------------------------------------------------------- write

def update(
    session: Session,
    tenant_id: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Update policy + bands + curve from one PUT.

    Prototype: updates in place, so a demo can iterate quickly and
    reset restores the seed. Production would supersede the current
    PolicyVersion and create a new row so the audit trail is preserved.
    """
    policy_patch = patch.get("policy") or {}
    if policy_patch:
        policy = _current_policy(session, tenant_id)
        if "concentration_cap_bp" in policy_patch:
            cap = int(policy_patch["concentration_cap_bp"])
            policy.concentration_cap_bp = max(100, min(10000, cap))
        if "enforcement" in policy_patch:
            enf = str(policy_patch["enforcement"])
            if enf in ("HARD_BLOCK", "WARN_WITH_OVERRIDE"):
                policy.enforcement = enf

    for row in patch.get("rating_bands") or []:
        rating = str(row.get("rating", ""))
        if rating not in RATING_LADDER:
            continue
        band = session.query(RatingBand).filter(
            RatingBand.tenant_id == tenant_id,
            RatingBand.rating == rating,
        ).first()
        if band is None:
            continue
        if "max_limit_pence" in row:
            band.max_limit_pence = max(0, int(row["max_limit_pence"]))
        if "max_tenor_months" in row:
            band.max_tenor_months = max(0, min(60, int(row["max_tenor_months"])))

    if "rate_curve" in patch:
        update_rate_curve(patch["rate_curve"])

    session.commit()
    return as_dict(session, tenant_id)


def reset(session: Session, tenant_id: str) -> dict[str, Any]:
    """Reset only the rate curve (policy + bands are DB-backed via
    admin reset). Left to the treasurer to Reset the whole book via
    the header button if they want the DB values back."""
    reset_rate_curve()
    return as_dict(session, tenant_id)


# --------------------------------------------------------------------- helpers

def _current_policy(session: Session, tenant_id: str) -> PolicyVersion:
    policy = session.query(PolicyVersion).filter(
        PolicyVersion.tenant_id == tenant_id,
        PolicyVersion.superseded_at.is_(None),
    ).first()
    if policy is None:
        raise ValueError("No current policy version for tenant.")
    return policy


def _current_bands(session: Session, tenant_id: str) -> list[RatingBand]:
    return list(
        session.query(RatingBand)
        .filter(RatingBand.tenant_id == tenant_id)
        .order_by(RatingBand.ordinal.desc())
        .all()
    )


# --------------------------------------------------------------------- sources

def _sources_catalogue() -> list[dict[str, str]]:
    """The catalogue the Reference & sources tile renders."""
    return [
        {
            "field": "Counterparty rating",
            "source": "S&P / Moody's / Fitch / Bloomberg composite - per counterparty",
            "editable": "no (external feed)",
            "shown_on": "Book row · under rating chip",
        },
        {
            "field": "Rating as-of date",
            "source": "same provider as the rating",
            "editable": "no (external feed)",
            "shown_on": "Book row · under rating chip",
        },
        {
            "field": "ISIN codes",
            "source": "Provider ISIN feed / bank catalogue",
            "editable": "no (external feed)",
            "shown_on": "Book row · instrument badges",
        },
        {
            "field": "Interest rate on ticket / planner",
            "source": "Bloomberg BGN composite (stubbed for demo)",
            "editable": "yes - Control · Rate curve",
            "shown_on": "Ticket · Planner allocations",
        },
        {
            "field": "Investment principles (buckets, sliders)",
            "source": "Treasurer sets - quarterly cadence in production",
            "editable": "yes - Control · Investment principles",
            "shown_on": "Planner uses them on every run",
        },
        {
            "field": "Accounting-event catalogue + destination",
            "source": "Treasurer sets",
            "editable": "yes - Control · Accounting events",
            "shown_on": "Evidence panel timeline chips",
        },
        {
            "field": "Concentration cap (bp)",
            "source": "Policy version - held on policy_version table",
            "editable": "yes - Control · System policy",
            "shown_on": "Planner header · six-check gate",
        },
        {
            "field": "Enforcement mode",
            "source": "Policy version",
            "editable": "yes - Control · System policy",
            "shown_on": "Header info",
        },
        {
            "field": "Rating bands (max limit, max tenor)",
            "source": "Rating band table",
            "editable": "yes - Control · System policy",
            "shown_on": "Ratings & Policy panel · six-check gate",
        },
        {
            "field": "Rate curve (bp per rating per tenor)",
            "source": "In production: Bloomberg BGN daily. In prototype: internal curve.",
            "editable": "yes - Control · System policy",
            "shown_on": "Ticket · Planner allocations (behind the Bloomberg tag)",
        },
        {
            "field": "Deal accruals / journals / performance",
            "source": "Computed from the accrual table",
            "editable": "no (derived)",
            "shown_on": "Performance panel · Evidence panel",
        },
        {
            "field": "Six-check outcomes",
            "source": "CheckEngine - re-runs the policy in force",
            "editable": "no (derived)",
            "shown_on": "Ticket · Evidence panel",
        },
    ]
