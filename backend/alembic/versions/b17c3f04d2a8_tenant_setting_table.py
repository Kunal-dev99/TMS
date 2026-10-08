"""tenant_setting — per-tenant JSON config backing planner + rate-curve

Revision ID: b17c3f04d2a8
Revises: a91c4e2f0d05
Create Date: 2026-10-08 12:00:00.000000

Replaces two in-process singletons (planner_settings, rate_curve) with
rows in a single tenant-keyed table. Portable across SQLite + Postgres.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b17c3f04d2a8"
down_revision: Union[str, None] = "a91c4e2f0d05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_setting",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("tenant_id", sa.String(length=40), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.String(length=30), nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["app_user.id"], name="fk_tenant_setting_updated_by"
        ),
        sa.UniqueConstraint("tenant_id", "key", name="ux_tenant_setting_key"),
    )
    op.create_index(
        "ix_tenant_setting_tenant_id", "tenant_setting", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_setting_tenant_id", table_name="tenant_setting")
    op.drop_table("tenant_setting")
