"""коды госзакупок переезжают с номера закупки на номер лота

Revision ID: c41a7de9b0f2
Revises: e04bd4172a35
Create Date: 2026-09-03 12:10:00.000000

Ключом строки в госзакупках был номер закупки. У объявления с четырьмя лотами
он один на всех, и на нём сошлось сразу несколько поломок: разбор открывал
случайный лот из четырёх, счётчики обсуждений искались не по тому ключу, а
устойчивые коды выдавались двумя рядами — на 183 лота их набралось 218. В
списке лот звался GZ000045, в карточке GZ000196.

Ключом стал номер лота. Без этой миграции коды в списке сменились бы разом у
всех: старые записи остались бы висеть на номере закупки, а лотам выдались бы
новые номера с конца ряда. Код печатают в задачах и называют вслух — менять
его без нужды нельзя.

Перенос идёт только там, где он однозначен: номеру закупки соответствует ровно
один лот, и у этого лота своего кода ещё нет. У объявлений с несколькими
лотами номер закупки общий, и какому из них принадлежал код, восстановить
нечем — такие записи остаются нетронутыми, а лоты получат коды заново.

Соответствие «номер закупки — номер лота» живёт в базе площадки, отдельной от
базы платформы. Недоступна она — миграция проходит без переноса: пропущенный
перенос означает сменившиеся коды, а остановленная миграция означает
неподнявшуюся платформу.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from platform_api.logging import get_logger

# revision identifiers, used by Alembic.
revision: str = "c41a7de9b0f2"
down_revision: str | Sequence[str] | None = "e04bd4172a35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = get_logger(__name__)


def upgrade() -> None:
    """Переносит выданные коды на номер лота."""
    pairs = _lots_by_purchase()
    if not pairs:
        return

    bind = op.get_bind()
    taken = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT row_key FROM worklist_codes WHERE module = 'goszakup'")
        )
    }

    moved = 0
    for purchase, lot_number in pairs.items():
        # Код у лота уже есть — переносить не на что: два кода на одну строку
        # нарушили бы единственность ключа, и выбирать между ними пришлось бы
        # наугад.
        if purchase not in taken or lot_number in taken:
            continue
        bind.execute(
            sa.text(
                "UPDATE worklist_codes SET row_key = :lot "
                "WHERE module = 'goszakup' AND row_key = :purchase"
            ),
            {"lot": lot_number, "purchase": purchase},
        )
        taken.add(lot_number)
        moved += 1

    logger.info("codes.rekeyed", module="goszakup", moved=moved, candidates=len(pairs))


def downgrade() -> None:
    """Обратно не переносим.

    Соответствие однозначно только в одну сторону: несколько лотов делят один
    номер закупки, и вернуть их коды на него значило бы сложить разные строки
    в одну запись.
    """


def _lots_by_purchase() -> dict[str, str]:
    """Номера закупок, за которыми стоит ровно один лот.

    Читается из базы площадки. Её может не быть — ядро госзакупок ставится
    отдельно, и на машине, где его нет, миграция всё равно должна пройти.
    """
    try:
        from goszakup.infrastructure.db.models import LotRecord
        from platform_api.modules.goszakup import core
        from sqlalchemy import select

        with core.session() as portal:
            rows: list[Any] = list(
                portal.execute(select(LotRecord.purchase_number, LotRecord.lot_number))
            )
    except Exception as exc:
        logger.warning("codes.rekey.skipped", error=str(exc))
        return {}

    seen: dict[str, str] = {}
    ambiguous: set[str] = set()
    for purchase, lot_number in rows:
        if not purchase or not lot_number:
            continue
        if purchase in seen and seen[purchase] != lot_number:
            ambiguous.add(purchase)
        seen[purchase] = lot_number
    return {key: value for key, value in seen.items() if key not in ambiguous}
