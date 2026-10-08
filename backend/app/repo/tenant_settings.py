"""Reads and writes against the tenant_setting table.

One row per (tenant_id, key). Payload is JSON text, parsed by callers who
know their own schema. No validation here — the service that owns the key
owns the shape.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TenantSetting


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def get(session: Session, tenant_id: str, key: str) -> dict[str, Any] | None:
    row = session.scalars(
        select(TenantSetting)
        .where(TenantSetting.tenant_id == tenant_id)
        .where(TenantSetting.key == key)
    ).one_or_none()
    if row is None:
        return None
    return json.loads(row.payload_json)


def get_or_default(
    session: Session,
    tenant_id: str,
    key: str,
    default: dict[str, Any],
) -> dict[str, Any]:
    found = get(session, tenant_id, key)
    return found if found is not None else default


def upsert(
    session: Session,
    tenant_id: str,
    key: str,
    payload: dict[str, Any],
    updated_by_user_id: str | None = None,
) -> dict[str, Any]:
    row = session.scalars(
        select(TenantSetting)
        .where(TenantSetting.tenant_id == tenant_id)
        .where(TenantSetting.key == key)
    ).one_or_none()
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    if row is None:
        row = TenantSetting(
            id=f"ts_{uuid.uuid4().hex[:16]}",
            tenant_id=tenant_id,
            key=key,
            payload_json=body,
            updated_at=_now_utc(),
            updated_by_user_id=updated_by_user_id,
        )
        session.add(row)
    else:
        row.payload_json = body
        row.updated_at = _now_utc()
        row.updated_by_user_id = updated_by_user_id
    session.flush()
    return payload


def delete(session: Session, tenant_id: str, key: str) -> None:
    row = session.scalars(
        select(TenantSetting)
        .where(TenantSetting.tenant_id == tenant_id)
        .where(TenantSetting.key == key)
    ).one_or_none()
    if row is not None:
        session.delete(row)
        session.flush()
