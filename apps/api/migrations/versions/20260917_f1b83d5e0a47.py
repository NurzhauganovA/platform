"""Хронология обсуждения.

Собрать её из самого замечания нельзя: в `discussions` хранятся только
последние значения. Кем отправлено — не хранится вовсе, текст модели
затирается при каждом перезапуске прогона, а правивший помнится только
последний. То есть на вопрос «что именно ушло заказчику и чем оно отличалось
от написанного» отвечать нечем — а задают его ровно тогда, когда пришёл отказ.

Отдельной таблицей, а не записями в ленте лота: замечание заводят по строке
списка, где карточки может ещё не быть, и привязка к ней потеряла бы историю у
тех закупок, которые в работу так и не взяли.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f1b83d5e0a47"
down_revision = "e4c9b71a0d82"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "remark_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "discussion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("discussions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("actor_role", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("by_machine", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_remark_events_discussion_id", "remark_events", ["discussion_id"])
    op.create_index("ix_remark_events_kind", "remark_events", ["kind"])
    op.create_index("remark_event_at", "remark_events", ["discussion_id", "created_at"])

    # Задним числом ленту не восстановить: следов нет. Что известно точно —
    # когда модель написала и когда отправили; по этим двум отметкам ставим по
    # строке, чтобы у прежних обсуждений хронология не выглядела пустой.
    op.execute(
        "insert into remark_events "
        "(id, discussion_id, actor_id, actor_name, actor_role, by_machine, kind, "
        " title, detail, created_at, updated_at) "
        "select gen_random_uuid(), id, null, '', '', true, 'written', "
        "       'Написала модель', '', ai_written_at, ai_written_at "
        "from discussions where ai_written_at is not null"
    )
    op.execute(
        "insert into remark_events "
        "(id, discussion_id, actor_id, actor_name, actor_role, by_machine, kind, "
        " title, detail, created_at, updated_at) "
        "select gen_random_uuid(), id, null, '', '', false, 'sent', "
        "       'Отправил заказчику', '', sent_at, sent_at "
        "from discussions where sent_at is not null"
    )


def downgrade() -> None:
    op.drop_index("remark_event_at", table_name="remark_events")
    op.drop_index("ix_remark_events_kind", table_name="remark_events")
    op.drop_index("ix_remark_events_discussion_id", table_name="remark_events")
    op.drop_table("remark_events")
