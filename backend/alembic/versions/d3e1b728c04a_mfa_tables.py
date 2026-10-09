"""MFA — user_mfa_secret + mfa_recovery_code

Revision ID: d3e1b728c04a
Revises: c4f8e21a9b65
Create Date: 2026-10-09 10:00:00.000000

Additive. Portable across SQLite + Postgres. Both tables are
opt-in — a user not enrolled in MFA has no row in either, and no
behaviour changes for anyone until an admin flips the per-tenant
policy (Phase 4).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d3e1b728c04a"
down_revision: Union[str, None] = "c4f8e21a9b65"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_mfa_secret",
        sa.Column("user_id", sa.String(length=40), primary_key=True),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.String(length=30), nullable=False),
        sa.Column("last_used_at", sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name="fk_user_mfa_secret_user"
        ),
    )

    op.create_table(
        "mfa_recovery_code",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("user_id", sa.String(length=40), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.String(length=30), nullable=False),
        sa.Column("consumed_at", sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name="fk_mfa_recovery_code_user"
        ),
        sa.UniqueConstraint("user_id", "code_hash", name="ux_mfa_recovery_code"),
    )
    op.create_index(
        "ix_mfa_recovery_code_user_id", "mfa_recovery_code", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_mfa_recovery_code_user_id", table_name="mfa_recovery_code")
    op.drop_table("mfa_recovery_code")
    op.drop_table("user_mfa_secret")
