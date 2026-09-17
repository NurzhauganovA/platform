"""Пять отделов с ответственными вместо «менеджера» и «ведущего».

На планёрке спрашивают не «чей лот», а «кто по нему юрист» — и до сих пор
ответом было открывание задач по одной. Два поля на всю закупку отвечали одним
именем на пять вопросов.

Строками, а не пятью колонками, по той же причине, что и подписи: у назначения
есть время, есть имя копией и есть признак «посадило правило, а не человек», и
поле их не вмещает. А шестой отдел появится правкой справочника, без миграции.

Переносится так:

* `owner_id` — тот, кто вёл лот, — садится в «Поставку» (отдел разбора: у нас
  это один и тот же человек, он считает себестоимость и он же ведёт поставку);
* `manager_id` становится `taken_by_id` — «кто взял закупку в работу».
  Раньше взявший молча становился менеджером, и первое же назначение его
  затирало: узнать, кто завёл лот, можно было только в ленте событий.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e4c9b71a0d82"
down_revision = "d8a3f21c605e"
branch_labels = None
depends_on = None

DESKS = ("ANALYSIS", "DISCUSSION", "LEGAL", "SUPPLY", "TECHNOLOGIST")
"""Отделы, у которых есть место в лоте. Имена заглавными: `native_enum=False`
пишет в колонку имя члена, а не значение."""


def upgrade() -> None:
    op.create_table(
        "lot_seats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "card_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lot_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("desk", sa.String(length=16), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("by_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("card_id", "desk", name="lot_seat_desk"),
    )
    op.create_index("ix_lot_seats_card_id", "lot_seats", ["card_id"])
    op.create_index("lot_seat_user", "lot_seats", ["user_id", "desk"])

    op.add_column(
        "lot_cards",
        sa.Column(
            "taken_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "lot_cards",
        sa.Column("taken_by_name", sa.String(length=255), nullable=False, server_default=""),
    )
    op.create_index("card_taken_by", "lot_cards", ["taken_by_id", "status"])

    # Кто взял лот в работу — это бывший менеджер: им становился взявший.
    op.execute("update lot_cards set taken_by_id = manager_id where manager_id is not null")

    # Пять пустых мест каждому лоту: «строки нет» и «строка пуста» должны
    # выглядеть одинаково, иначе каждому читателю придётся доливать
    # недостающие.
    for desk in DESKS:
        op.execute(
            "insert into lot_seats "
            "(id, card_id, desk, user_id, by_name, taken_at, auto, created_at, updated_at) "
            f"select gen_random_uuid(), id, '{desk}', null, '', null, false, now(), now() "
            "from lot_cards"
        )

    # Ведущего сажаем в «Поставку»: у нас он же и считает себестоимость.
    op.execute(
        "update lot_seats s set user_id = c.owner_id, taken_at = c.updated_at "
        "from lot_cards c where s.card_id = c.id and s.desk = 'ANALYSIS' "
        "and c.owner_id is not null"
    )

    op.drop_index("card_owner", table_name="lot_cards")
    op.drop_column("lot_cards", "owner_id")
    op.drop_column("lot_cards", "manager_id")


def downgrade() -> None:
    op.add_column(
        "lot_cards",
        sa.Column(
            "manager_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "lot_cards",
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("card_owner", "lot_cards", ["owner_id", "status"])

    op.execute("update lot_cards set manager_id = taken_by_id")
    op.execute(
        "update lot_cards c set owner_id = s.user_id "
        "from lot_seats s where s.card_id = c.id and s.desk = 'ANALYSIS'"
    )
    # Обратно с потерей, и это надо знать заранее: юрист, снабженец и технолог
    # по лоту после отката не восстанавливаются — полей под них не было.

    op.drop_index("card_taken_by", table_name="lot_cards")
    op.drop_column("lot_cards", "taken_by_name")
    op.drop_column("lot_cards", "taken_by_id")
    op.drop_index("lot_seat_user", table_name="lot_seats")
    op.drop_index("ix_lot_seats_card_id", table_name="lot_seats")
    op.drop_table("lot_seats")
