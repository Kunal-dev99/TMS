"""Editable policy for the cash-deployment planner.

Anil's feedback on the Sep-7 demo: "nothing should be hardwired,
everything should be config driven." The four planner strategies, the
rating floor, the tenor ceiling, and the per-name cap were all hardcoded
Python; this module holds them as per-tenant settings that the settings
modal PUTs into, and that PlannerService reads on every run.

Storage: one row per tenant in `tenant_setting` with `key='planner'`.
Previously this was a module-level singleton seeded with defaults, which
reset on every process restart and diverged across app instances. The
restart-safe table is a prerequisite for horizontal scaling and for the
parked multi-tenancy plan.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.repo import tenant_settings as settings_repo


SETTING_KEY = "planner"


# The four built-in archetypes. UI shows these with a checkbox each; the
# treasurer can also add custom ones (see below), each of which is a
# clone of one of the four with different rating floor and tenor.
BUILTIN_STRATEGIES: list[dict[str, str]] = [
    {
        "kind": "MAX_YIELD",
        "label": "Maximum yield",
        "tagline": "Everything with the highest-paying name that has room.",
    },
    {
        "kind": "DIVERSIFIED",
        "label": "Diversified",
        "tagline": "Equal-share across the top few names.",
    },
    {
        "kind": "PRESERVE_HEADROOM",
        "label": "Preserve group headroom",
        "tagline": "Leaves the tightest group room for later business.",
    },
    {
        "kind": "CONSERVATIVE",
        "label": "Conservative",
        "tagline": "AAA only, at three months.",
    },
]

# Rating ordinals so a "min rating" slider works. Higher = safer.
RATING_ORDINAL: dict[str, int] = {
    "BBB-": 1, "BBB": 2, "BBB+": 3,
    "A-":   4, "A":   5, "A+":   6,
    "AA-":  7, "AA":  8, "AA+":  9,
    "AAA": 10,
}
RATING_LADDER: list[str] = [
    r for r, _ in sorted(RATING_ORDINAL.items(), key=lambda kv: kv[1])
]

# Coarse rating bands the treasurer allocates across in buckets.
# Order matters: highest (safest) first, so it renders top-to-bottom.
RATING_BANDS: list[str] = ["AAA", "AA", "A", "BBB"]


def band_of(rating: str) -> str:
    """Collapse a fine-grained rating (e.g. 'AA-') onto a band ('AA').

    Anything outside the known bands (or missing) falls back to 'BBB' so
    it never disappears from the pool by accident.
    """
    if not rating:
        return "BBB"
    r = rating.upper()
    if r == "AAA":
        return "AAA"
    if r.startswith("AA"):
        return "AA"
    if r.startswith("A"):
        return "A"
    if r.startswith("BBB"):
        return "BBB"
    return "BBB"


@dataclass
class CustomStrategy:
    kind: str          # user-supplied slug, e.g. "CUSTOM_BALANCED"
    label: str
    tagline: str
    based_on: str      # one of BUILTIN kinds
    min_rating: str    # override; empty means inherit settings.min_rating
    max_tenor_months: int  # override; 0 means inherit settings.max_tenor_months


@dataclass
class PlannerSettings:
    """Everything the treasurer can twist from the settings modal."""

    min_rating: str = "BBB-"
    max_tenor_months: int = 12
    per_name_cap_pct: int = 100
    group_concentration_cap_pct: int = 25
    buckets: dict[str, int] = field(
        default_factory=lambda: {"AAA": 50, "AA": 30, "A": 20, "BBB": 0}
    )
    enabled_strategies: list[str] = field(
        default_factory=lambda: [s["kind"] for s in BUILTIN_STRATEGIES]
    )
    custom_strategies: list[CustomStrategy] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Serialisation helpers — defaults live in the dataclass, DB stores the diff.
# ---------------------------------------------------------------------------


def _defaults_payload() -> dict[str, Any]:
    s = PlannerSettings()
    return {
        "min_rating": s.min_rating,
        "max_tenor_months": s.max_tenor_months,
        "per_name_cap_pct": s.per_name_cap_pct,
        "group_concentration_cap_pct": s.group_concentration_cap_pct,
        "buckets": dict(s.buckets),
        "enabled_strategies": list(s.enabled_strategies),
        "custom_strategies": [],
    }


def _from_payload(payload: dict[str, Any]) -> PlannerSettings:
    custom = [
        CustomStrategy(
            kind=str(c.get("kind", "")),
            label=str(c.get("label", "")),
            tagline=str(c.get("tagline", "")),
            based_on=str(c.get("based_on", "MAX_YIELD")),
            min_rating=str(c.get("min_rating", "")),
            max_tenor_months=int(c.get("max_tenor_months", 0)),
        )
        for c in payload.get("custom_strategies", []) or []
    ]
    return PlannerSettings(
        min_rating=str(payload.get("min_rating", "BBB-")),
        max_tenor_months=int(payload.get("max_tenor_months", 12)),
        per_name_cap_pct=int(payload.get("per_name_cap_pct", 100)),
        group_concentration_cap_pct=int(payload.get("group_concentration_cap_pct", 25)),
        buckets={
            band: int((payload.get("buckets") or {}).get(band, 0))
            for band in RATING_BANDS
        },
        enabled_strategies=list(
            payload.get("enabled_strategies") or [s["kind"] for s in BUILTIN_STRATEGIES]
        ),
        custom_strategies=custom,
    )


def _to_payload(s: PlannerSettings) -> dict[str, Any]:
    return {
        "min_rating": s.min_rating,
        "max_tenor_months": s.max_tenor_months,
        "per_name_cap_pct": s.per_name_cap_pct,
        "group_concentration_cap_pct": s.group_concentration_cap_pct,
        "buckets": {band: int(s.buckets.get(band, 0)) for band in RATING_BANDS},
        "enabled_strategies": list(s.enabled_strategies),
        "custom_strategies": [asdict(c) for c in s.custom_strategies],
    }


# ---------------------------------------------------------------------------
# Public API — all DB-backed, per-tenant.
# ---------------------------------------------------------------------------


def get_settings(session: Session, tenant_id: str) -> PlannerSettings:
    payload = settings_repo.get_or_default(
        session, tenant_id, SETTING_KEY, _defaults_payload()
    )
    return _from_payload(payload)


def as_dict(s: PlannerSettings) -> dict[str, Any]:
    """Serialize for the API. Shape unchanged from the pre-DB singleton."""
    return {
        "min_rating": s.min_rating,
        "max_tenor_months": s.max_tenor_months,
        "per_name_cap_pct": s.per_name_cap_pct,
        "group_concentration_cap_pct": s.group_concentration_cap_pct,
        "buckets": {band: int(s.buckets.get(band, 0)) for band in RATING_BANDS},
        "enabled_strategies": list(s.enabled_strategies),
        "custom_strategies": [
            {
                "kind": c.kind,
                "label": c.label,
                "tagline": c.tagline,
                "based_on": c.based_on,
                "min_rating": c.min_rating,
                "max_tenor_months": c.max_tenor_months,
            }
            for c in s.custom_strategies
        ],
        "builtin_strategies": BUILTIN_STRATEGIES,
        "rating_ladder": RATING_LADDER,
        "rating_bands": RATING_BANDS,
    }


def update_settings(
    session: Session,
    tenant_id: str,
    patch: dict[str, Any],
    updated_by_user_id: str | None = None,
) -> PlannerSettings:
    """Merge a partial update onto the current row; persist, return the result.

    Validates enough to keep the planner from breaking: rating must be
    on the ladder, tenor must be at least 3 months, caps must be percent
    values, every enabled_strategies entry must be a known kind.
    """
    current = get_settings(session, tenant_id)

    raw_buckets = patch.get("buckets", _to_payload(current)["buckets"])
    buckets = {
        band: max(0, min(100, int(raw_buckets.get(band, 0) or 0)))
        for band in RATING_BANDS
    }

    new = PlannerSettings(
        min_rating=str(patch.get("min_rating", current.min_rating)),
        max_tenor_months=int(patch.get("max_tenor_months", current.max_tenor_months)),
        per_name_cap_pct=int(patch.get("per_name_cap_pct", current.per_name_cap_pct)),
        group_concentration_cap_pct=int(
            patch.get("group_concentration_cap_pct", current.group_concentration_cap_pct)
        ),
        buckets=buckets,
        enabled_strategies=list(
            patch.get("enabled_strategies", current.enabled_strategies)
        ),
        custom_strategies=[
            CustomStrategy(
                kind=str(item["kind"]),
                label=str(item.get("label", item["kind"])),
                tagline=str(item.get("tagline", "")),
                based_on=str(item.get("based_on", "MAX_YIELD")),
                min_rating=str(item.get("min_rating", "")),
                max_tenor_months=int(item.get("max_tenor_months", 0)),
            )
            for item in patch.get(
                "custom_strategies",
                [
                    {
                        "kind": c.kind, "label": c.label, "tagline": c.tagline,
                        "based_on": c.based_on, "min_rating": c.min_rating,
                        "max_tenor_months": c.max_tenor_months,
                    }
                    for c in current.custom_strategies
                ],
            )
        ],
    )

    # Guard rails.
    if new.min_rating not in RATING_ORDINAL:
        new.min_rating = "BBB-"
    new.max_tenor_months = max(3, min(24, new.max_tenor_months))
    new.per_name_cap_pct = max(10, min(100, new.per_name_cap_pct))
    new.group_concentration_cap_pct = max(5, min(100, new.group_concentration_cap_pct))
    builtin_kinds = {s["kind"] for s in BUILTIN_STRATEGIES}
    new.enabled_strategies = [
        k for k in new.enabled_strategies if k in builtin_kinds
    ] or [s["kind"] for s in BUILTIN_STRATEGIES]

    if sum(new.buckets.values()) == 0:
        new.buckets = {b: (100 if b == "AAA" else 0) for b in RATING_BANDS}

    settings_repo.upsert(
        session, tenant_id, SETTING_KEY, _to_payload(new), updated_by_user_id
    )
    return new


def reset_defaults(
    session: Session,
    tenant_id: str,
    updated_by_user_id: str | None = None,
) -> PlannerSettings:
    settings_repo.delete(session, tenant_id, SETTING_KEY)
    return PlannerSettings()
