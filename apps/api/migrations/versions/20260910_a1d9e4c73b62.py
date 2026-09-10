"""Варианты разбора спецификации

Revision ID: a1d9e4c73b62
Revises: f7b3c8d21a45
Create Date: 2026-09-10 11:40:00.000000

Откат уносит все варианты, кроме «A», — иначе прежний уникальный ключ на двух
колонках не создастся. Написано словами намеренно: откатывают ночью и в
спешке, и «удалит данные» должно попасться на глаза до запуска, а не после.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1d9e4c73b62"
down_revision: str | Sequence[str] | None = "f7b3c8d21a45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Уже собранные таблицы становятся вариантом «A» и ничего не теряют:
    # умолчание проставляет его самой базой, а не отдельным проходом.
    op.add_column(
        "spec_sheets",
        sa.Column("variant", sa.String(length=4), nullable=False, server_default="A"),
    )
    op.drop_constraint("sheet_on_row", "spec_sheets", type_="unique")
    op.create_unique_constraint("sheet_on_row", "spec_sheets", ["module", "row_id", "variant"])


def downgrade() -> None:
    """Downgrade schema."""
    # Варианты, кроме «A», удаляются: на двух колонках ключ иначе не встанет.
    op.execute("DELETE FROM spec_sheets WHERE variant <> 'A'")
    op.drop_constraint("sheet_on_row", "spec_sheets", type_="unique")
    op.create_unique_constraint("sheet_on_row", "spec_sheets", ["module", "row_id"])
    op.drop_column("spec_sheets", "variant")
