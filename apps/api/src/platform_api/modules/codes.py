"""Постоянные коды строк рабочего списка: «TN-00042».

Порядковый номер для этого не годится. Он считается по списку, а список
пересобирается при каждом разборе: появилась одна закупка — и всё, что ниже,
сдвинулось на единицу. Сотрудник говорит «посмотри сорок вторую», а у
собеседника это уже другая строка.

Код выдаётся один раз и остаётся при позиции. Приставка своя у каждого
раздела: впереди Mitwork и госзакупки, и «сорок второй» без приставки будет в
каждой из них.

Выдаётся при чтении списка — иного момента нет. Разбор идёт у тендерщика на
машине, платформа о новых закупках узнаёт, только когда их спросят. Запись при
этом идёт лишь на новые строки: на устоявшемся списке чтение не пишет ничего.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from platform_api.db.models import WorklistCode
from platform_api.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session as DbSession

logger = get_logger(__name__)

WIDTH = 5
"""Сколько знаков в номере: «TN-00042». Пять — это сто тысяч позиций на
раздел; при трёхстах закупках в год запаса хватит дольше, чем проживёт
формат. Ведущие нули нужны, чтобы коды одинаково выглядели в списке и
сортировались как текст."""


def assign(db: DbSession, module: str, prefix: str, keys: Sequence[str]) -> dict[str, str]:
    """Коды перечисленных строк. Кому не хватало — выдаёт новые.

    Одним запросом на весь список, а не по строке: строк восемьсот, и
    обращение на каждую превратило бы открытие страницы в восемьсот обходов
    базы по сети.
    """
    if not keys:
        return {}

    issued_codes = _known(db, module, keys)
    fresh = [key for key in dict.fromkeys(keys) if key not in issued_codes]
    if not fresh:
        return {code: _format(prefix, code_number) for code, code_number in issued_codes.items()}

    next_one = _next_number(db, module)
    db.execute(
        insert(WorklistCode)
        .values(
            [
                {"module": module, "row_key": key, "number": next_one + shift}
                for shift, key in enumerate(fresh)
            ]
        )
        # Тот же список могли открыть двое разом. Проигравший не падает и не
        # заводит второй код: он просто перечитает то, что записал первый.
        .on_conflict_do_nothing(constraint="module_row")
    )
    db.flush()
    logger.info("Выданы коды строк", module=module, added=len(fresh))

    issued_codes = _known(db, module, keys)
    return {key: _format(prefix, number) for key, number in issued_codes.items()}


def _known(db: DbSession, module: str, keys: Sequence[str]) -> dict[str, int]:
    rows = db.execute(
        select(WorklistCode.row_key, WorklistCode.number).where(
            WorklistCode.module == module,
            WorklistCode.row_key.in_(set(keys)),
        )
    ).all()
    return dict(rows)  # type: ignore[arg-type]


def _next_number(db: DbSession, module: str) -> int:
    """Следующий свободный номер раздела.

    От наибольшего выданного, а не от количества строк: удалённая из отбора
    закупка свой номер не освобождает — иначе он достался бы другой позиции, и
    ссылка «TN-00042» из переписки повела бы не туда.
    """
    best = db.execute(
        select(func.max(WorklistCode.number)).where(WorklistCode.module == module)
    ).scalar()
    return (best or 0) + 1


def _format(prefix: str, number: int) -> str:
    return f"{prefix}-{number:0{WIDTH}d}"


__all__ = ["WIDTH", "assign"]
