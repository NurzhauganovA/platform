"""Срок взятия задачи

Revision ID: a932bb95d899
Revises: eefa2e88faa9
Create Date: 2026-09-07 16:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a932bb95d899"
down_revision: str | Sequence[str] | None = "eefa2e88faa9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("tasks", sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True))
    # Уже назначенные задачи считаем взятыми в момент заведения: иначе они
    # разом окажутся «не взяты за час» и загорятся красным все сразу.
    op.execute("UPDATE tasks SET taken_at = created_at WHERE assignee_id IS NOT NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tasks", "taken_at")
