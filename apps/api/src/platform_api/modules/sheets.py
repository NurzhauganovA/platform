"""Таблица разбора спецификации: хранение, сборка моделью, правки людей.

Таблица заменяет двадцать минут ручной раскладки на лот. Спецификация приходит
сплошным текстом, где требования к процессору, памяти и монитору идут подряд
через маркеры списка; работать с ней нельзя, пока не разложишь по предметам.

Три первых столбца собирает модель, остальные заводят люди — под цену, нашу
спецификацию, ссылку на поставщика. Цена и «Наша ТС» стоят в заготовке
пустыми: заводить их руками в каждом лоте — одно и то же действие тридцать раз
подряд. Разница хранится в самом столбце: пересборка трогает только свои три,
потому что затереть чужую работу заново нажатой кнопкой — худшее, что может
сделать кнопка.

Строки и столбцы правятся свободно: в спецификации нет блока питания, а
поставить его надо, и это добавление руками — не исключение, а обычный ход
работы. Поэтому таблица хранится документом, а не разложенной по ячейкам:
вставка столбца между двумя существующими в разложенном виде означала бы
пересчёт порядка у всех ячеек листа.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from platform_api.config import Settings
from platform_api.db.base import utcnow
from platform_api.db.models import LotCard, SpecSheet
from platform_api.logging import get_logger
from platform_api.modules import sheeting

logger = get_logger(__name__)

SUBJECT = "subject"
DEMAND = "demand"
BRIEF = "brief"
PRICE = "price"
OURS = "ours"

BY_MODEL = "model"
"""Столбец заполняет модель. Пересборка их перезаписывает."""

BY_HAND = "hand"
"""Столбец завёл человек. Пересборка его не трогает."""

WIDTH = {SUBJECT: 100, DEMAND: 340, BRIEF: 170, PRICE: 100, OURS: 240}
"""Ширина в точках. Предмет — одно слово, выжимка — числа столбиком, цена —
число; широкими им быть нечем, а занятое ими место уводит вправо то, что
заполняют руками. Требование заказчика остаётся самым широким: там абзац."""


@dataclass(frozen=True, slots=True)
class Column:
    """Столбец таблицы."""

    key: str
    title: str
    width: int = 200
    filled_by: str = BY_HAND


@dataclass(slots=True)
class Row:
    """Строка: свой ключ и значения по ключам столбцов."""

    key: str
    cells: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Table:
    """Таблица целиком — то, что уходит на экран."""

    columns: tuple[Column, ...]
    rows: tuple[Row, ...]
    source_name: str = ""
    model: str = ""
    trouble: str = ""
    built_at: str = ""


def base_columns() -> tuple[Column, ...]:
    """Три столбца, которые заполняет модель.

    Заголовки словами работы, а не буквами столбцов: «B» ничего не говорит
    тому, кто открыл таблицу впервые, а «Требование заказчика» объясняет, чем
    это поле отличается от соседнего и почему его нельзя править на глаз.
    """
    return (
        Column(key=SUBJECT, title="Предмет", width=WIDTH[SUBJECT], filled_by=BY_MODEL),
        Column(
            key=DEMAND,
            title="Требование заказчика",
            width=WIDTH[DEMAND],
            filled_by=BY_MODEL,
        ),
        Column(key=BRIEF, title="Кратко", width=WIDTH[BRIEF], filled_by=BY_MODEL),
    )


def hand_columns() -> tuple[Column, ...]:
    """Два столбца, которые заводить руками пришлось бы в каждом лоте.

    Цена и наша техническая спецификация — то, ради чего разбор и затевается:
    строка требования нужна, чтобы напротив неё встало наше предложение с
    ценой. Столбцы человеческие, поэтому пересборка их не трогает, а убрать
    их с экрана по-прежнему можно крестиком.
    """
    return (
        Column(key=PRICE, title="Цена", width=WIDTH[PRICE]),
        Column(key=OURS, title="Наша ТС", width=WIDTH[OURS]),
    )


def default_columns() -> tuple[Column, ...]:
    """Заготовка таблицы: три столбца модели и два под ответ."""
    return (*base_columns(), *hand_columns())


def load(db: DbSession, card: LotCard) -> Table:
    """Отдаёт таблицу лота. Нет — пустую с заготовкой столбцов.

    Пустая, а не отсутствующая: экран должен показать заготовку и кнопку
    «Разобрать», а не пустоту, по которой не понять, потеряно что-то или ещё
    не начато.
    """
    found = _find(db, card)
    if found is None:
        return Table(columns=default_columns(), rows=())
    return _out(found)


def save(db: DbSession, card: LotCard, *, columns: list[Column], rows: list[Row]) -> Table:
    """Сохраняет правки человека целиком.

    Целиком, а не по ячейке: таблица небольшая, а раздельная запись означала
    бы гонку между «переименовал столбец» и «дописал строку», сделанными
    одновременно двумя людьми в одном лоте.
    """
    sheet = _find(db, card)
    if sheet is None:
        sheet = SpecSheet(
            organization_id=card.organization_id, module=card.module, row_id=card.row_id
        )
        db.add(sheet)
    sheet.columns = [_as_json(column) for column in columns]
    sheet.rows = [{"key": row.key, "cells": dict(row.cells)} for row in rows]
    db.flush()
    return _out(sheet)


def build(
    db: DbSession,
    card: LotCard,
    settings: Settings,
    *,
    spec_text: str,
    spec_name: str,
    user_id: uuid.UUID | None = None,
) -> Table:
    """Раскладывает спецификацию моделью.

    Столбцы, заведённые людьми, и их значения остаются: модель переписывает
    только свои три. Строки при этом собираются заново — предметы в новой
    спецификации могут стоять в другом порядке, и сшивать старые значения с
    новыми строками не по чему.

    Спецификации нет — это не отказ, а ответ: у большинства лотов портала её
    действительно нет, и сказать об этом надо словами, а не пустой таблицей.
    """
    sheet = _find(db, card)
    if sheet is None:
        sheet = SpecSheet(
            organization_id=card.organization_id, module=card.module, row_id=card.row_id
        )
        db.add(sheet)

    if not spec_text.strip():
        sheet.trouble = (
            "К этой закупке спецификация не приложена — раскладывать нечего. "
            "Заполните таблицу руками или проверьте документы на портале"
        )
        db.flush()
        return _out(sheet)

    from platform_api.modules import writer

    answer = writer.ask(
        sheeting.prompt(title=card.title, spec=spec_text),
        settings,
        about=card.code,
        # Объём ответа — от длины спецификации: требования переносятся
        # дословно, и на четырнадцати страницах общий потолок замечания рвал
        # таблицу посередине.
        max_tokens=sheeting.budget(spec_text, ceiling=settings.writer.sheet_tokens),
        json_only=True,
    )
    if not answer.text:
        sheet.trouble = answer.trouble
        db.flush()
        return _out(sheet)

    shaped = sheeting.shape(answer.text, cut=answer.cut)
    # Обрыв по объёму — не пустая таблица: целые строки из недописанного ответа
    # сохраняются, а человеку говорится, что хвоста не хватает. Так у него
    # остаётся сделанная работа и знание, чего в ней нет.
    if shaped.trouble and not shaped.rows:
        sheet.trouble = shaped.trouble
        db.flush()
        return _out(sheet)

    mine = [column for column in _columns(sheet) if column.filled_by == BY_HAND]
    # Заготовка досоздаётся, а не навязывается: убранный человеком столбец
    # возвращается только пересборкой, и то если его ключ свободен.
    taken = {column.key for column in mine}
    sheet.columns = [
        _as_json(column)
        for column in (
            *base_columns(),
            *mine,
            *(column for column in hand_columns() if column.key not in taken),
        )
    ]
    sheet.rows = [
        {
            "key": f"r{number}",
            "cells": {SUBJECT: row.subject, DEMAND: row.demand, BRIEF: row.brief},
        }
        for number, row in enumerate(shaped.rows, 1)
    ]
    sheet.source_name = spec_name
    sheet.model = answer.model
    sheet.trouble = shaped.trouble
    sheet.built_at = utcnow()
    sheet.built_by_id = user_id
    db.flush()

    logger.info("sheet.built", code=card.code, rows=len(shaped.rows), model=answer.model)
    return _out(sheet)


def _find(db: DbSession, card: LotCard) -> SpecSheet | None:
    return db.execute(
        select(SpecSheet).where(SpecSheet.module == card.module, SpecSheet.row_id == card.row_id)
    ).scalar_one_or_none()


def _columns(sheet: SpecSheet) -> tuple[Column, ...]:
    return tuple(_column(item) for item in sheet.columns or ())


def _column(item: dict[str, Any]) -> Column:
    return Column(
        key=str(item.get("key", "")),
        title=str(item.get("title", "")),
        width=int(item.get("width") or 200),
        filled_by=str(item.get("filled_by") or BY_HAND),
    )


def _as_json(column: Column) -> dict[str, Any]:
    return {
        "key": column.key,
        "title": column.title,
        "width": column.width,
        "filled_by": column.filled_by,
    }


def _out(sheet: SpecSheet) -> Table:
    columns = _columns(sheet) or default_columns()
    rows = tuple(
        Row(key=str(item.get("key", "")), cells=dict(item.get("cells") or {}))
        for item in sheet.rows or ()
    )
    return Table(
        columns=columns,
        rows=rows,
        source_name=sheet.source_name,
        model=sheet.model,
        trouble=sheet.trouble,
        built_at=sheet.built_at.isoformat() if sheet.built_at else "",
    )
