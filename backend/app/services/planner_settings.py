"""Editable policy for the cash-deployment planner.

Anil's feedback on the Sep-7 demo: "nothing should be hardwired,
everything should be config driven." The four planner strategies, the
rating floor, the tenor ceiling, and the per-name cap were all hardcoded
Python; this module holds them as a settings singleton that the settings
modal PUTs into, and that PlannerService reads on every run.

In the prototype the singleton lives in memory (dict at module scope),
seeded with the same defaults the code used to hardcode. On free-tier
Render the container is recycled between demos, which reseeds the
defaults — perfectly fine for a prototype and one less thing to migrate.
Production would persist this to policy_versions with an approval flow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any

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
        "tagline": "A and above only, at three months.",
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

    # Rating floor: any counterparty below this is excluded from every
    # placement (including the conservative one). Default "BBB-" reproduces
    # the old behaviour (no floor).
    min_rating: str = "BBB-"

    # Tenor ceiling in months, capped by the per-band max in the book.
    max_tenor_months: int = 12

    # Cap per counterparty as a % of idle cash. 100 = no cap.
    per_name_cap_pct: int = 100

    # Group concentration cap displayed alongside the existing policy
    # limit; the actual gate is the CheckEngine concentration check.
    # Editing this here documents the desired posture for the demo.
    group_concentration_cap_pct: int = 25

    # Which built-in strategies to render, in the order they appear.
    enabled_strategies: list[str] = field(
        default_factory=lambda: [s["kind"] for s in BUILTIN_STRATEGIES]
    )

    # User-defined strategies. Each runs as its `based_on` archetype with
    # rating/tenor overrides applied to the placement pool.
    custom_strategies: list[CustomStrategy] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Module-level singleton. One shared instance per running process.
# ---------------------------------------------------------------------------

_lock = Lock()
_settings = PlannerSettings()


def get_settings() -> PlannerSettings:
    with _lock:
        return _settings


def as_dict(s: PlannerSettings) -> dict[str, Any]:
    """Serialize for the API."""
    return {
        "min_rating": s.min_rating,
        "max_tenor_months": s.max_tenor_months,
        "per_name_cap_pct": s.per_name_cap_pct,
        "group_concentration_cap_pct": s.group_concentration_cap_pct,
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
    }


def update_settings(patch: dict[str, Any]) -> PlannerSettings:
    """Apply a partial update; whatever is missing keeps its current value.

    Validates enough to keep the planner from breaking: rating must be
    on the ladder, tenor must be at least 3 months, caps must be percent
    values, every enabled_strategies entry must be a known kind.
    """
    global _settings
    with _lock:
        current = _settings

        new = PlannerSettings(
            min_rating=str(patch.get("min_rating", current.min_rating)),
            max_tenor_months=int(patch.get("max_tenor_months", current.max_tenor_months)),
            per_name_cap_pct=int(patch.get("per_name_cap_pct", current.per_name_cap_pct)),
            group_concentration_cap_pct=int(
                patch.get("group_concentration_cap_pct", current.group_concentration_cap_pct)
            ),
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

        _settings = new
        return new


def reset_defaults() -> PlannerSettings:
    global _settings
    with _lock:
        _settings = PlannerSettings()
        return _settings
