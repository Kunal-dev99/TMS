"""policy_version change metadata: changed_by / authorised_by / note / superseded_by

Revision ID: d6a2e91b31c4
Revises: 694ad4b80e75
Create Date: 2026-09-18 22:00:00.000000

Adds the columns Compliance needs to render policy history: who wrote
the change, who authorised it (four-eye), a note explaining the change,
and an explicit link to the version that superseded this one. The
existing `approved_by` free-text stays put for backwards compatibility.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6a2e91b31c4"
down_revision: Union[str, None] = "694ad4b80e75"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("policy_version", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("changed_by_user_id", sa.String(length=40), nullable=True)
        )
        batch_op.add_column(
            sa.Column("changed_by_display", sa.String(length=120), nullable=True)
        )
        batch_op.add_column(
            sa.Column("authorised_by_user_id", sa.String(length=40), nullable=True)
        )
        batch_op.add_column(
            sa.Column("authorised_by_display", sa.String(length=120), nullable=True)
        )
        batch_op.add_column(sa.Column("note", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "superseded_by_version_id", sa.String(length=40), nullable=True
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("policy_version", schema=None) as batch_op:
        batch_op.drop_column("superseded_by_version_id")
        batch_op.drop_column("note")
        batch_op.drop_column("authorised_by_display")
        batch_op.drop_column("authorised_by_user_id")
        batch_op.drop_column("changed_by_display")
        batch_op.drop_column("changed_by_user_id")
