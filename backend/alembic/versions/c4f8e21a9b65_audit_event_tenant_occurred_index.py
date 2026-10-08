"""audit_event — composite (tenant_id, occurred_at) index (P1-05)

Revision ID: c4f8e21a9b65
Revises: b17c3f04d2a8
Create Date: 2026-10-08 13:30:00.000000

Every compliance query filters by tenant_id and orders/ranges on
occurred_at. A composite index on that pair turns a growing-table
scan into an index seek. Portable across SQLite + Postgres.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "c4f8e21a9b65"
down_revision: Union[str, None] = "b17c3f04d2a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_audit_tenant_occurred",
        "audit_event",
        ["tenant_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_tenant_occurred", table_name="audit_event")
