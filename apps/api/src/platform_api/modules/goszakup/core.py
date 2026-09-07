"""Единственная точка, где платформа обращается к ядру госзакупок.

Всё остальное в модуле ходит через неё: когда ядро изменит имя класса или
сигнатуру, это выяснится здесь, а не россыпью по обработчикам запросов.

Ядро настраивается своим `.env` с префиксом `GOSZAKUP__` — оно самостоятельный
проект со своим CLI, а не часть платформы. База задаётся снаружи
(`GOSZAKUP__DB__URL`), чтобы терминал и платформа работали с одними данными.

Чтение здесь не стоит денег и не ходит в сеть: обход портала — отдельная
задача с кнопкой. Открытая страница показывает то, что он оставил в базе.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from goszakup.config import Settings
    from goszakup.export.sheet import Column


@lru_cache(maxsize=1)
def core_settings() -> Settings:
    """Настройки ядра госзакупок."""
    from goszakup.config import get_settings

    return get_settings()


@lru_cache(maxsize=1)
def _sessions() -> Any:
    """Фабрика сессий к базе ядра.

    Схема создаётся при первом обращении: таблиц две, миграций у ядра пока
    нет. Когда схема начнёт меняться на живых данных, сюда встанет alembic —
    как у платформы.
    """
    from goszakup.infrastructure.db import (
        create_db_engine,
        create_session_factory,
        ensure_schema,
    )

    engine = create_db_engine(core_settings().db)
    ensure_schema(engine)
    return create_session_factory(engine)


def session() -> Any:
    """Сессия к базе ядра. Закрывать вызывающему."""
    return _sessions()()


def columns() -> Sequence[Column]:
    """Колонки листа `августГЗ` — те же, что в книге ядра."""
    from goszakup.export.sheet import columns as sheet_columns

    return sheet_columns()


def sheet_title() -> str:
    return "ГЗ"


@dataclass(frozen=True, slots=True)
class Worklist:
    """Что показывать в отборе госзакупок."""

    rows: tuple[Any, ...]
    total: int
    """Сколько лотов в базе всего."""

    live: int
    """По скольким приём ещё идёт."""

    burning: int
    """По скольким осталось меньше суток."""

    amount_total: Decimal | None
    codes: int
    """Сколько кодов ЕНС ТРУ отслеживается."""

    harvested_at: str
    """Когда обход портала был в последний раз."""


def worklist() -> Worklist:
    """Лоты из базы ядра — без обращений к порталу и без списаний.

    Обход портала оплачен временем и запросами, и повторять его на каждое
    открытие страницы нельзя: портал государственный, а F5 в отделе нажимают
    часто.
    """
    from datetime import UTC, datetime

    from goszakup.application import catalog, storage

    with session() as db:
        rows = storage.lots(db)
        codes = len(catalog.watched(db))

    now = datetime.now(UTC)
    live = burning = 0
    amounts: list[Decimal] = []
    latest = None
    for row in rows:
        if row.amount is not None:
            amounts.append(row.amount)
        seen = _aware(row.last_seen_at)
        latest = seen if latest is None or seen > latest else latest
        left = _left_seconds(row, now)
        if left is None or left <= 0:
            continue
        live += 1
        if left < 86_400:
            burning += 1

    return Worklist(
        rows=tuple(rows),
        total=len(rows),
        live=live,
        burning=burning,
        amount_total=sum(amounts, Decimal(0)) if amounts else None,
        codes=codes,
        harvested_at=latest.isoformat() if latest else "",
    )


def row_id(row: Any) -> str:
    """Чем открыть лот — номер лота.

    Не номер закупки, хотя вслух звучит именно он. У объявления с четырьмя
    лотами номер закупки один на всех, и как ключ он склеивал их в одну
    строку: открытие любого из четырёх показывало один и тот же — какой
    первым вернула база. Тем же номером выдавался устойчивый код, и на 183
    лота их набралось 218 в двух рядах: в списке лот звался GZ000045, в
    карточке GZ000196. Счётчики обсуждений искались по нему же и не находили
    ничего — переписка ведётся по номеру лота.

    Номер закупки никуда не делся: он в колонке, в разборе и в замечании
    заказчику. Он для человека, а ключ — для машины.
    """
    return str(row.lot_number)


def row_deadline(row: Any) -> str | None:
    """Когда закрывается приём. По нему подсвечивается срочное."""
    return _aware(row.end_date).isoformat() if row.end_date is not None else None


URGENT_HOURS = 24
"""Со скольких часов до конца приёма лот горит.

Сутки, а не три часа, как у площадок: на портале приём идёт неделями, заявку
собирают с юристами и снабжением, и трёх часов на это не хватит. Порог один на
цвет строки, легенду и плитку — раньше плитка считала по своему, и на экране
стояли «Горит 2» и «Горит 6» рядом.
"""


def tone_of(row: Any) -> str:
    """Цвет строки.

    Решения по лоту у нас пока нет — себестоимость по госзакупкам не считается.
    Поэтому цветом показано время: сутки до конца приёма это то, что нужно
    увидеть, не читая. Цвет дублируется колонкой «Осталось» словами.
    """
    from datetime import UTC, datetime

    left = _left_seconds(row, datetime.now(UTC))
    if left is None:
        return ""
    if left <= 0:
        return "critical"
    if left < URGENT_HOURS * 3_600:
        return "warning"
    return "good"


def legend() -> tuple[tuple[str, str, str], ...]:
    """Что означает цвет строки. Словами — сам по себе он смысла не несёт."""
    return (
        ("good", "Приём идёт", "заявку подать успеваем"),
        ("warning", "Горит", "до конца приёма меньше суток"),
        ("critical", "Приём закрыт", "лот остался историей"),
    )


def in_focus(row: Any) -> bool:
    """Есть ли с лотом что делать: приём ещё идёт."""
    from datetime import UTC, datetime

    left = _left_seconds(row, datetime.now(UTC))
    return left is None or left > 0


def core_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("goszakup-analytics")
    except PackageNotFoundError:  # pragma: no cover — ядро поставлено из исходников
        return "неизвестна"


def _left_seconds(row: Any, now: Any) -> float | None:
    if row.end_date is None:
        return None
    return float((_aware(row.end_date) - now).total_seconds())


def _aware(value: Any) -> Any:
    """Время с зоной: PostgreSQL её хранит, SQLite нет, а в ходу обе."""
    from datetime import UTC

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
