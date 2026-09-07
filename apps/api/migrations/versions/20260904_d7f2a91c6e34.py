"""таблица разбора спецификации

Revision ID: d7f2a91c6e34
Revises: c41a7de9b0f2
Create Date: 2026-09-04 09:40:00.000000

Одна запись на лот: столбцы и строки лежат документом, а не разложенные по
ячейкам. Сотрудник добавляет столбцы и строки по ходу работы, и вставка
столбца между двумя существующими в разложенном виде означала бы пересчёт
порядка у всех ячеек листа.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d7f2a91c6e34"
down_revision: str | Sequence[str] | None = "c41a7de9b0f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "spec_sheets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("module", sa.String(length=32), nullable=False),
        sa.Column("row_id", sa.String(length=128), nullable=False),
        sa.Column("columns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rows", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_name", sa.String(length=512), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("trouble", sa.Text(), nullable=False),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("built_by_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["built_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("module", "row_id", name="sheet_on_row"),
    )
    op.create_index(
        op.f("ix_spec_sheets_organization_id"), "spec_sheets", ["organization_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_spec_sheets_organization_id"), table_name="spec_sheets")
    op.drop_table("spec_sheets")
