"""Кто закрыл задачу

Revision ID: d4ef51da634e
Revises: b3b4fec764df
Create Date: 2026-09-07 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4ef51da634e"
down_revision: str | Sequence[str] | None = "b3b4fec764df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("tasks", sa.Column("done_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_tasks_done_by_id_users"),
        "tasks",
        "users",
        ["done_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # У закрытых раньше считаем, что закрыл исполнитель: чаще всего так и было,
    # а пустое поле на экране читается как «непонятно кто» — хуже приблизительно
    # верного. Точнее взять неоткуда: до сих пор это нигде не записывалось.
    op.execute(
        "UPDATE tasks SET done_by_id = assignee_id "
        "WHERE done_at IS NOT NULL AND assignee_id IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("fk_tasks_done_by_id_users"), "tasks", type_="foreignkey")
    op.drop_column("tasks", "done_by_id")
