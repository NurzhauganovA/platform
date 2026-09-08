"""Полный журнал действий

Revision ID: b3b4fec764df
Revises: a932bb95d899
Create Date: 2026-09-07 17:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3b4fec764df"
down_revision: str | Sequence[str] | None = "a932bb95d899"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "audit_log", sa.Column("method", sa.String(length=8), nullable=False, server_default="")
    )
    op.add_column(
        "audit_log", sa.Column("path", sa.String(length=512), nullable=False, server_default="")
    )
    op.add_column(
        "audit_log", sa.Column("status", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "audit_log", sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "audit_log", sa.Column("role", sa.String(length=32), nullable=False, server_default="")
    )
    op.add_column(
        "audit_log",
        sa.Column("user_agent", sa.String(length=512), nullable=False, server_default=""),
    )
    # Отбор «что делал этот человек» — второй по частоте после «что было в
    # этот день». Без указателя он читает таблицу целиком, а она растёт
    # быстрее всех остальных: строка на каждое изменение.
    op.create_index("ix_audit_user_created", "audit_log", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_audit_user_created", table_name="audit_log")
    for column in ("user_agent", "role", "duration_ms", "status", "path", "method"):
        op.drop_column("audit_log", column)
