"""Шесть статусов лота вместо четырнадцати, итог — отдельной величиной.

Прежний список описывал путь по отделам: «Обсуждение», «На разборе», «Готов к
участию», «Договор», «Исполнение», «Ожидаем оплату». На планёрке по нему
отвечали не на тот вопрос: он говорил, чья сейчас очередь, а спрашивают — где
закупка. Чья очередь, видно по задачам и по точкам отделов в строке, и держать
то же самое ещё и статусом значило переводить лот пять раз за день руками.

Итог закупки при этом перестал быть статусом. «Выиграли» и «Проиграли» стояли
в том же списке, и завершённый лот не мог быть одновременно проигранным — хотя
проигранный завершён ровно так же, как выигранный.

Как переносится:

* «Обсуждение» и «На разборе» — в «В работе»: отделы работают внутри него;
* «Готов к участию» — в «Подача»: подписи собраны, остаётся подать;
* «Ожидаем итоги» — в «Ожидание протокола итогов»;
* «Выиграли», «Договор», «Исполнение», «Ожидаем оплату» — «Завершённый» с
  итогом «Выиграли»: договор без победы не заключают;
* «Проиграли» — «Завершённый» с итогом «Проиграли»;
* «Завершён» — «Завершённый»; итог «Выиграли», если записана сумма победы,
  иначе пустой: сумма — единственный след победы у таких лотов;
* «Не участвуем» и «Отменён» — «Завершённый» с пустым итогом. Причина отказа
  осталась в `skip_reason`, а решение — в `participation`, так что ничего не
  потеряно.

Обратно не восстанавливается: четырнадцать состояний из шести не собрать —
«Договор» и «Исполнение» после переноса неразличимы. Понижение возвращает
лоты в ближайшее прежнее состояние и об этом честно говорит.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d3a7b95c1f64"
down_revision = "c8e1f34b7a25"
branch_labels = None
depends_on = None

# Статус — строка (`native_enum=False`), поэтому переносится обычным update:
# типа в базе нет, и ломать нечего.
#
# Значения — ИМЕНА членов перечисления, а не их значения: SQLAlchemy с
# `native_enum=False` пишет в колонку `ANALYSIS`, а не `analysis`. Перенос по
# значениям молча не нашёл бы ни одной строки — и все лоты остались бы в
# состояниях, которых в коде уже нет.
СТАТУСЫ = {
    "DISCUSSION": "WORK",
    "ANALYSIS": "WORK",
    "READY": "SUBMISSION",
    "AWAITING": "WAITING",
    "WON": "DONE",
    "LOST": "DONE",
    "CONTRACT": "DONE",
    "FULFILLING": "DONE",
    "AWAITING_PAYMENT": "DONE",
    "SKIPPED": "DONE",
    "CANCELLED": "DONE",
}

ИТОГИ = {
    "WON": "WON",
    "CONTRACT": "WON",
    "FULFILLING": "WON",
    "AWAITING_PAYMENT": "WON",
    "LOST": "LOST",
}


def upgrade() -> None:
    op.add_column(
        "lot_cards",
        sa.Column("outcome", sa.String(length=8), nullable=False, server_default="NONE"),
    )
    op.create_index("ix_lot_cards_outcome", "lot_cards", ["outcome"])

    # Итог ставится до переноса статуса: после него «Договор» от «Проиграли»
    # уже не отличить — оба станут «Завершённым».
    for было, итог in ИТОГИ.items():
        op.execute(f"update lot_cards set outcome = '{итог}' where status = '{было}'")
    op.execute(
        "update lot_cards set outcome = 'WON' "
        "where status = 'DONE' and won_amount is not null and outcome = 'NONE'"
    )
    for было, стало in СТАТУСЫ.items():
        op.execute(f"update lot_cards set status = '{стало}' where status = '{было}'")


def downgrade() -> None:
    # Ближайшее прежнее состояние, а не исходное: «Договор» и «Исполнение» из
    # «Завершённого» с итогом «Выиграли» не восстановить — они неразличимы.
    op.execute("update lot_cards set status = 'WON' where status = 'DONE' and outcome = 'WON'")
    op.execute("update lot_cards set status = 'LOST' where status = 'DONE' and outcome = 'LOST'")
    op.execute("update lot_cards set status = 'AWAITING' where status = 'WAITING'")
    op.execute("update lot_cards set status = 'READY' where status = 'SUBMISSION'")
    op.execute("update lot_cards set status = 'ANALYSIS' where status = 'WORK'")
    op.drop_index("ix_lot_cards_outcome", table_name="lot_cards")
    op.drop_column("lot_cards", "outcome")
