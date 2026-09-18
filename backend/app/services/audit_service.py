"""One writer for every durable event the compliance page needs to show.

The dedicated `audit_event` table (rather than a view stitching check_run +
hedge_link + policy_version) is the compliance page's substrate. It also
carries events the DB tables alone cannot express — AI runs, sign-ins,
admin actions, policy edits.

Every service that wants to leave a compliance trail calls `record` here.
Actions are short kebab-case strings (`user.invited`, `user.role.granted`,
`policy.fx.updated`) so filtering is stable across UI iterations.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.ids import new_id, now
from app.models import AuditEvent


def record(
    session: Session,
    *,
    tenant_id: str,
    actor_user_id: str | None,
    actor_display: str | None,
    action: str,
    subject_type: str,
    subject_id: str | None = None,
    outcome: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        id=new_id("aud"),
        tenant_id=tenant_id,
        occurred_at=now(),
        actor_user_id=actor_user_id,
        actor_display=actor_display,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        outcome=outcome,
        payload_json=json.dumps(payload, default=str) if payload else None,
    )
    session.add(event)
    session.flush()
    return event
