"""the check run purpose admits an amendment

Revision ID: 0008
Revises: 0007

An amendment is now re-tested against the six checks before it is applied,
and the run it writes needs a purpose of its own. Without it the evidence
would have to borrow `CORRECTION`, which already means something else: a
correction takes the confirmed terms from a mismatch, and an amendment is
raised by a person against terms nobody disputes.

SQLite cannot alter a check constraint in place, so this rebuilds the table.
That is why the constraint is named: an unnamed one cannot be dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = (
    "purpose in ('CHECK','BOOKING','RETEST','CORRECTION',"
    "'ADVISORY_CANDIDATE','ADVISORY_VALIDATION')"
)
NEW = (
    "purpose in ('CHECK','BOOKING','RETEST','CORRECTION','AMENDMENT',"
    "'ADVISORY_CANDIDATE','ADVISORY_VALIDATION')"
)


def _swap(condition: str) -> None:
    with op.batch_alter_table("check_run") as batch:
        batch.drop_constraint("ck_check_run_purpose", type_="check")
        batch.create_check_constraint("ck_check_run_purpose", condition)


def upgrade() -> None:
    _swap(NEW)


def downgrade() -> None:
    # An amendment run written under the new constraint would not survive
    # this, which is correct: the rows and the rule move together.
    op.execute("DELETE FROM check_run WHERE purpose = 'AMENDMENT'")
    _swap(OLD)
