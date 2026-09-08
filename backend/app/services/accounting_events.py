"""Accounting-event catalogue for the deal lifecycle.

Anil's Sep-8 ask: "these are the accounting, these are what we classify
as accounting event. Deal creation is not an accounting event, for
example, but deal approval maybe, I do not know. And we will say that
we will integrate it. Oracle GL. Nothing should be hardwired in the
application. Everything should be config driven."

This module is the config. Each row is one lifecycle stage plus:
  * whether it fires an accounting event (toggle-able)
  * the event class + type Fusion Accounting Hub would receive
  * the target ledger / hub

The catalogue lives in memory (like planner_settings) for the
prototype; production would persist to policy_versions with an
approval flow. The endpoint is GET/PUT and the "posts to" wording is
deliberately verbatim from the deep-research report so a Fusion
consultant hears the correct integration surface named.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any


# The deal lifecycle stages, in the order they occur.
LIFECYCLE_STAGES: list[str] = [
    "PROPOSED",
    "APPROVED",
    "EXECUTED",
    "CONFIRMED",
    "SETTLED",
    "ACCRUED",
    "MATURED",
    "CLOSED",
]


@dataclass
class EventRule:
    stage: str
    is_event: bool           # does this stage fire an accounting event?
    event_class: str         # AHCS event class name (e.g. "Deals")
    event_type: str          # AHCS event type (e.g. "Deal Executed")
    posts_to: str            # where it posts to
    integration: str         # named integration surface
    cadence: str             # "event-driven" or "batch"
    note: str                # one-line human explanation


def _default_catalogue() -> list[EventRule]:
    """The out-of-the-box mapping, per Anil's guidance and the deep-
    research report on Fusion Accounting Hub."""
    return [
        EventRule(
            stage="PROPOSED",
            is_event=False,
            event_class="",
            event_type="",
            posts_to="",
            integration="",
            cadence="",
            note="Pre-trade workflow; no financial impact.",
        ),
        EventRule(
            stage="APPROVED",
            is_event=False,
            event_class="",
            event_type="",
            posts_to="",
            integration="",
            cadence="",
            note="Control milestone; not typically an accounting event.",
        ),
        EventRule(
            stage="EXECUTED",
            is_event=True,
            event_class="Deals",
            event_type="Deal Executed",
            posts_to="Oracle Fusion Accounting Hub",
            integration="Oracle Integration Cloud + ERP Cloud Adapter",
            cadence="event-driven",
            note="Trade-date recognition. Fires the first accounting entry.",
        ),
        EventRule(
            stage="CONFIRMED",
            is_event=False,
            event_class="",
            event_type="",
            posts_to="",
            integration="",
            cadence="",
            note="Control milestone; no separate journal unless policy differs.",
        ),
        EventRule(
            stage="SETTLED",
            is_event=True,
            event_class="Deals",
            event_type="Deal Settled",
            posts_to="Oracle Fusion Accounting Hub",
            integration="Oracle Integration Cloud + ERP Cloud Adapter",
            cadence="event-driven",
            note="Value-date cash movement; must reconcile to the bank statement.",
        ),
        EventRule(
            stage="ACCRUED",
            is_event=True,
            event_class="Accruals",
            event_type="Daily Accrual",
            posts_to="Oracle Fusion Accounting Hub",
            integration="Oracle Integration Cloud + ERP Cloud Adapter",
            cadence="batch (end-of-day)",
            note="Nightly job accrues interest per open deal.",
        ),
        EventRule(
            stage="MATURED",
            is_event=True,
            event_class="Deals",
            event_type="Deal Matured",
            posts_to="Oracle Fusion Accounting Hub",
            integration="Oracle Integration Cloud + ERP Cloud Adapter",
            cadence="event-driven",
            note="Principal + interest final settlement; unwinds open accruals.",
        ),
        EventRule(
            stage="CLOSED",
            is_event=False,
            event_class="",
            event_type="",
            posts_to="",
            integration="",
            cadence="",
            note="Lifecycle housekeeping; no residual write-off unless custom.",
        ),
    ]


@dataclass
class AccountingEventSettings:
    rules: list[EventRule] = field(default_factory=_default_catalogue)


# ---------------------------------------------------------------------------
# Module-level singleton — same pattern as planner_settings.
# ---------------------------------------------------------------------------

_lock = Lock()
_settings = AccountingEventSettings()


def get_settings() -> AccountingEventSettings:
    with _lock:
        return _settings


def as_dict(s: AccountingEventSettings) -> dict[str, Any]:
    return {
        "rules": [
            {
                "stage": r.stage,
                "is_event": r.is_event,
                "event_class": r.event_class,
                "event_type": r.event_type,
                "posts_to": r.posts_to,
                "integration": r.integration,
                "cadence": r.cadence,
                "note": r.note,
            }
            for r in s.rules
        ],
        "lifecycle_stages": LIFECYCLE_STAGES,
    }


def update_settings(patch: dict[str, Any]) -> AccountingEventSettings:
    """Only the is_event toggle is user-editable — everything else
    (class/type/integration) reflects Oracle's real event model and
    shouldn't be freely edited from the UI. But we accept the whole
    row anyway so the API stays predictable."""
    global _settings
    with _lock:
        current = _settings
        current_by_stage = {r.stage: r for r in current.rules}
        incoming = patch.get("rules") or []
        new_rules: list[EventRule] = []
        for raw in incoming:
            stage = str(raw.get("stage", ""))
            if stage not in LIFECYCLE_STAGES:
                continue
            base = current_by_stage.get(stage)
            new_rules.append(
                EventRule(
                    stage=stage,
                    is_event=bool(raw.get("is_event", base.is_event if base else False)),
                    event_class=str(raw.get("event_class", base.event_class if base else "")),
                    event_type=str(raw.get("event_type", base.event_type if base else "")),
                    posts_to=str(raw.get("posts_to", base.posts_to if base else "")),
                    integration=str(raw.get("integration", base.integration if base else "")),
                    cadence=str(raw.get("cadence", base.cadence if base else "")),
                    note=str(raw.get("note", base.note if base else "")),
                )
            )

        # Preserve any stages the patch didn't include, in canonical order.
        touched = {r.stage for r in new_rules}
        preserved = [current_by_stage[s] for s in LIFECYCLE_STAGES if s not in touched and s in current_by_stage]
        combined = new_rules + preserved
        combined.sort(key=lambda r: LIFECYCLE_STAGES.index(r.stage))

        _settings = AccountingEventSettings(rules=combined)
        return _settings


def reset_defaults() -> AccountingEventSettings:
    global _settings
    with _lock:
        _settings = AccountingEventSettings()
        return _settings
