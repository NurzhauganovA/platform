"""Имя автора копией рядом со ссылкой.

Сотрудника можно удалить, и ссылка на него в истории тогда обнуляется — иначе
удаление унесло бы саму запись. Без копии имени лента превращалась бы в список
действий без авторов: «перевёл в „Подача“» без имени неотличимо от прогона по
расписанию. А спрашивают по ленте ровно одно: кто это сделал.

То же у подписи. Вопрос «кто это одобрил» возникает, когда закупка вышла в
убыток, и это бывает через полгода после того, как человек уволился.

Имя на момент действия, а не сегодняшнее: человек меняет фамилию, и запись
должна остаться той, какой её прочитали тогда. Старые записи заполняются
текущими именами — другого источника для них нет.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2b6a90d47e3"
down_revision = "e4f81c6d92b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lot_events",
        sa.Column("actor_name", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "approvals",
        sa.Column("by_name", sa.String(length=255), nullable=False, server_default=""),
    )
    # Задним числом — по нынешним именам: другого источника для прежних записей
    # нет, а пустая лента у старых лотов хуже приблизительной.
    op.execute(
        """
        update lot_events set actor_name = coalesce(nullif(u.full_name, ''), u.email)
        from users u where u.id = lot_events.actor_id
        """
    )
    op.execute(
        """
        update approvals set by_name = coalesce(nullif(u.full_name, ''), u.email)
        from users u where u.id = approvals.by_id
        """
    )


def downgrade() -> None:
    op.drop_column("approvals", "by_name")
    op.drop_column("lot_events", "actor_name")
