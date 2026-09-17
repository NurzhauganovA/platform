"""Семь итогов закупки вместо трёх.

Причин закончить закупку больше, чем «выиграли» и «проиграли». «Не участвуем»,
«тендер отменён», «код ТРУ не подходит», «не ликвидный» и «не успели подать» —
разные ответы на вопрос «почему прошли мимо», и до сих пор все они лежали одним
пустым итогом. Отчёт по такому полю отвечает одним словом на пять случаев, а
спрашивают его как раз затем, чтобы их различить.

Колонка расширяется: `native_enum=False` пишет в неё ИМЯ члена заглавными, и
самое длинное теперь `NOT_SUBMITTED` — тринадцать знаков против прежних восьми.
Без этого первая же запись падает с «value too long».

Ограничения на значения в базе нет (`create_constraint=False` по умолчанию),
поэтому в DDL больше ничего и не требуется.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d8a3f21c605e"
down_revision = "c7e2a45b019f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "lot_cards",
        "outcome",
        existing_type=sa.String(length=8),
        type_=sa.String(length=24),
        existing_nullable=False,
        existing_server_default="NONE",
    )
    # Завершённые лоты, по которым решили не участвовать, получают свой итог.
    # Раньше они были неотличимы от «протокол ещё не пришёл»: и там и там
    # стояло пустое значение.
    op.execute(
        "update lot_cards set outcome = 'SKIPPED' "
        "where status = 'DONE' and participation = 'NO' and outcome = 'NONE'"
    )


def downgrade() -> None:
    # Обратно с потерей, и это надо знать заранее: «отменён», «не тот код» и
    # «не ликвидный» после отката друг от друга не отличить — все пятеро
    # сходятся в пустой итог, каким и были до этой правки.
    op.execute(
        "update lot_cards set outcome = 'NONE' "
        "where outcome in ('NOT_SUBMITTED', 'NOT_LIQUID', 'WRONG_CODE', 'CANCELLED', 'SKIPPED')"
    )
    # Сужение — только после замены: длинное имя в короткую колонку не влезет.
    op.alter_column(
        "lot_cards",
        "outcome",
        existing_type=sa.String(length=24),
        type_=sa.String(length=8),
        existing_nullable=False,
        existing_server_default="NONE",
    )
