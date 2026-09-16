"""Задачи вне лота и переписка внутри задачи.

Поручение — это работа человека, а не закупки: «собрать доверенности»,
«оформить пропуск на склад». Раньше задача без лота была невозможна, и такие
поручения жили в мессенджере — то есть нигде: срока у них не было, спросить о
них было не с кого, а через неделю не вспомнить, кому что говорили.

Поэтому лот у задачи становится необязательным, а вместе с ним и отдел:
поручение адресуется человеку. Отдел у него был бы придуманным и вывел бы
задачу в чужую очередь.

Переписка внутри задачи — в той же таблице, что и обсуждение строки. Устроены
они одинаково (реплика, автор, правка, упоминания), и вторая таблица означала
бы второй набор правил о том, кто может править чужое, и второй способ звать
людей. Расходятся такие наборы молча.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c7e2a45b019f"
down_revision = "b6c9f04a1e27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("tasks", "card_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.alter_column("tasks", "department", existing_type=sa.String(length=16), nullable=True)

    op.add_column(
        "discussion_messages",
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_discussion_messages_task_id",
        "discussion_messages",
        ["task_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_discussion_messages_task_id", table_name="discussion_messages")
    op.drop_column("discussion_messages", "task_id")

    # Обратно только то, что обратимо. Задачи без лота при откате удаляются:
    # ставить их произвольному лоту значит завести в его ленте работу, которой
    # там не было, а оставить — упереться в NOT NULL на середине отката.
    op.execute("DELETE FROM tasks WHERE card_id IS NULL")
    op.alter_column("tasks", "department", existing_type=sa.String(length=16), nullable=False)
    op.alter_column("tasks", "card_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
