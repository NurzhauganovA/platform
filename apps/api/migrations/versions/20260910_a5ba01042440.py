"""Таблица снабжения рядом с таблицей разбора.

Снабжение продолжает работу разбора: берёт те же позиции и дописывает к ним
поставщика, закупочную цену и срок. Пока таблица была одна на лот, эти две
работы шли поверх друг друга — снабженец правил строку, по которой разборщик
считал маржу, и разбор задним числом переставал сходиться с тем, что
показывали на согласовании.

Разделяются признаком `kind`, а не второй таблицей в базе: устроены они
одинаково, читаются и пишутся одним кодом, и вторая таблица означала бы вторую
миграцию при каждой правке столбцов.

Обратно: снабженческие таблицы удаляются. Спуститься на эту версию и не
потерять их нельзя — колонки, по которой их отличать, там нет.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a5ba01042440"
down_revision = "a1d9e4c73b62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "spec_sheets",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="analysis"),
    )
    op.create_index("ix_spec_sheets_kind", "spec_sheets", ["kind"])
    # Ключ становится четверным: у лота бывает несколько вариантов разбора и
    # столько же снабженческих таблиц к ним.
    op.drop_constraint("sheet_on_row", "spec_sheets", type_="unique")
    op.create_unique_constraint(
        "sheet_on_row", "spec_sheets", ["module", "row_id", "variant", "kind"]
    )


def downgrade() -> None:
    op.execute("delete from spec_sheets where kind <> 'analysis'")
    op.drop_constraint("sheet_on_row", "spec_sheets", type_="unique")
    op.create_unique_constraint("sheet_on_row", "spec_sheets", ["module", "row_id", "variant"])
    op.drop_index("ix_spec_sheets_kind", table_name="spec_sheets")
    op.drop_column("spec_sheets", "kind")
