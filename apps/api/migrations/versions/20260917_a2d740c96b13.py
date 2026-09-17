"""Место отдела занимают сами: правило «в роли один — сажаем» снято.

Задумано было так: если в роли один человек, работа сразу его. На живом лоте
это читалось неверно — строка «Обсуждение» оказывалась занятой до того, как
человек к лоту притронулся. Работу берут сами, и до этого момента она не его;
а уведомление и так уходит всей роли.

Вместе с правилом уходит и признак «посажено правилом»: ставить его больше
некому, а колонка, которую никто не заполняет, через полгода читается как
«здесь что-то было, но непонятно что».
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a2d740c96b13"
down_revision = "f1b83d5e0a47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Освобождаем то, что успело сесть правилом. Занявшие место руками
    # остаются: они эту работу выбрали.
    op.execute("update lot_seats set user_id = null, by_name = '', taken_at = null where auto")
    op.drop_column("lot_seats", "auto")


def downgrade() -> None:
    op.add_column(
        "lot_seats",
        sa.Column("auto", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Кого сажало правило, после отката не восстановить: признак и был
    # единственным следом.
