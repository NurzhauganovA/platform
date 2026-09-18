"""Время последней смены статуса — по нему сортируются списки.

Список сортировался по сроку приёма заявок, и на вопрос «что нового» отвечал
«что горит»: лот, который вчера перевели на согласование, лежал в середине
между теми, к которым никто не прикасался. Теперь сверху то, что двигалось
последним; срок при этом никуда не делся — он в строке и красным, когда горит.

Отдельным полем, а не выводом из ленты событий: лента лежит другой таблицей, и
сортировка списка по ней означала бы соединение на каждое открытие страницы
ради одного столбца.

Задним числом время берётся из ленты — там переходы и записаны. Нет записи —
берём последнее изменение карточки: точнее в базе ничего нет, а пустое поле
отправило бы такие лоты в самый низ списка, хотя они могли двигаться вчера.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c6f37b2e94d1"
down_revision = "b5e19c74af08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lot_cards", sa.Column("status_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_lot_cards_status_at", "lot_cards", ["status_at"])

    # Последний переход из ленты. `to_status <> ''` отсекает записи, которые
    # статуса не меняли: задачи, файлы, подписи лежат в той же таблице.
    op.execute(
        "update lot_cards c set status_at = e.at from ("
        "  select card_id, max(created_at) as at from lot_events"
        "  where coalesce(to_status, '') <> '' group by card_id"
        ") e where e.card_id = c.id"
    )
    op.execute("update lot_cards set status_at = updated_at where status_at is null")


def downgrade() -> None:
    op.drop_index("ix_lot_cards_status_at", table_name="lot_cards")
    op.drop_column("lot_cards", "status_at")
