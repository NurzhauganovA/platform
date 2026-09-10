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
from platform_api.errors import SpokenError
from platform_api.logging import get_logger
from platform_api.modules import sheeting

logger = get_logger(__name__)

SUBJECT = "subject"
DEMAND = "demand"
BRIEF = "brief"
PRICE = "price"
COST = "cost"
OURS = "ours"

BY_MODEL = "model"
"""Столбец заполняет модель. Пересборка их перезаписывает."""

BY_HAND = "hand"
"""Столбец завёл человек. Пересборка его не трогает."""

WIDTH = {SUBJECT: 100, DEMAND: 340, BRIEF: 170, PRICE: 100, COST: 100, OURS: 240}
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
    variant: str = "A"
    """Какой это вариант разбора."""
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
    """Три столбца, которые заводить руками пришлось бы в каждом лоте.

    Цена, себестоимость и наш товар — то, ради чего разбор и затевается:
    строка требования нужна, чтобы напротив неё встало наше предложение с
    ценой. Столбцы человеческие, поэтому пересборка их не трогает, а убрать
    их с экрана по-прежнему можно крестиком.

    Себестоимость стоит вплотную к цене намеренно: заработок считается из
    разницы, и держать её через два столбца значит заставить человека возить
    глазами по строке. Заполняет её снабжение — своей закупочной ценой, — и
    поэтому это столбец, а не расчёт: цены поставщиков платформа по
    госзакупкам пока не знает, а придуманная ею себестоимость хуже пустой.

    Столбец назван «Наш товар», а не «Наша ТС»: сюда пишут, что именно
    предлагаем — марку и модель, — а «ТС» читалось как «ещё одна техническая
    спецификация», и половина заполняла его пересказом требования.
    """
    return (
        Column(key=PRICE, title="Цена", width=WIDTH[PRICE]),
        Column(key=COST, title="Себес", width=WIDTH[COST]),
        Column(key=OURS, title="Наш товар", width=WIDTH[OURS]),
    )


def default_columns() -> tuple[Column, ...]:
    """Заготовка таблицы: три столбца модели и два под ответ."""
    return (*base_columns(), *hand_columns())


FIRST = "A"
"""Вариант, который собирает модель. Есть всегда."""

MAX_VARIANTS = 6
"""Сколько вариантов держать на лоте.

Шесть букв — это шесть способов собрать один и тот же компьютер; дальше
сравнение перестаёт помещаться в голову, а выбирать всё равно приходится
один. Предел нужен и затем, что каждый вариант — это своя запись и свой
разбор, который кто-то может запустить.
"""


def variants(db: DbSession, card: LotCard) -> list[str]:
    """Какие варианты у лота есть. «A» — всегда, даже если таблицы ещё нет."""
    letters = list(
        db.scalars(
            select(SpecSheet.variant)
            .where(SpecSheet.module == card.module, SpecSheet.row_id == card.row_id)
            .order_by(SpecSheet.variant)
        )
    )
    return letters or [FIRST]


def branch(db: DbSession, card: LotCard) -> str:
    """Заводит следующий вариант от «A». Возвращает его букву.

    Копируются столбцы целиком и ячейки столбцов модели — предмет, требование
    заказчика и выжимка. Требования у вариантов одни и те же: заказчик просит
    один и тот же товар, а различаются наши ответы — цена, себестоимость и что
    именно предлагаем. Переписывать требования руками во втором варианте
    значит однажды переписать их с ошибкой и подать заявку по придуманному.
    """
    letters = variants(db, card)
    if len(letters) >= MAX_VARIANTS:
        raise SpokenError(f"Вариантов уже {len(letters)}: больше не заводим")

    taken = set(letters)
    letter = next(
        (chr(code) for code in range(ord("A"), ord("A") + MAX_VARIANTS) if chr(code) not in taken),
        "",
    )
    if not letter:
        raise SpokenError("Свободных букв не осталось")

    first = _find(db, card, FIRST)
    columns = _columns(first) if first is not None else default_columns()
    rows = _out(first).rows if first is not None else ()
    kept = {column.key for column in columns if column.filled_by == BY_MODEL}

    made = SpecSheet(
        organization_id=card.organization_id,
        module=card.module,
        row_id=card.row_id,
        variant=letter,
        columns=[_as_json(column) for column in columns],
        rows=[
            {
                "key": row.key,
                "cells": {key: value for key, value in row.cells.items() if key in kept},
            }
            for row in rows
        ],
        source_name=first.source_name if first is not None else "",
    )
    db.add(made)
    db.flush()
    logger.info("sheet.branched", code=card.code, variant=letter, rows=len(made.rows))
    return letter


def drop(db: DbSession, card: LotCard, variant: str) -> None:
    """Убирает вариант. Последний не убирается: лот без разбора — пустая вкладка."""
    letters = variants(db, card)
    if len(letters) <= 1:
        raise SpokenError("Это единственный вариант — удалять нечего")

    found = _find(db, card, variant)
    if found is None:
        raise SpokenError(f"Варианта «{variant}» у этого лота нет")
    db.delete(found)
    db.flush()
    logger.info("sheet.dropped", code=card.code, variant=variant)


def load(db: DbSession, card: LotCard, variant: str = FIRST) -> Table:
    """Отдаёт таблицу лота. Нет — пустую с заготовкой столбцов.

    Пустая, а не отсутствующая: экран должен показать заготовку и кнопку
    «Разобрать», а не пустоту, по которой не понять, потеряно что-то или ещё
    не начато.
    """
    found = _find(db, card, variant)
    if found is None:
        return Table(columns=default_columns(), rows=(), variant=variant)
    return _out(found)


def save(
    db: DbSession,
    card: LotCard,
    *,
    columns: list[Column],
    rows: list[Row],
    variant: str = FIRST,
) -> Table:
    """Сохраняет правки человека целиком.

    Целиком, а не по ячейке: таблица небольшая, а раздельная запись означала
    бы гонку между «переименовал столбец» и «дописал строку», сделанными
    одновременно двумя людьми в одном лоте.
    """
    sheet = _find(db, card, variant)
    if sheet is None:
        sheet = SpecSheet(
            organization_id=card.organization_id,
            module=card.module,
            row_id=card.row_id,
            variant=variant,
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
    variant: str = FIRST,
) -> Table:
    """Раскладывает спецификацию моделью.

    Столбцы, заведённые людьми, и их значения остаются: модель переписывает
    только свои три. Строки при этом собираются заново — предметы в новой
    спецификации могут стоять в другом порядке, и сшивать старые значения с
    новыми строками не по чему.

    Спецификации нет — это не отказ, а ответ: у большинства лотов портала её
    действительно нет, и сказать об этом надо словами, а не пустой таблицей.
    """
    sheet = _find(db, card, variant)
    if sheet is None:
        sheet = SpecSheet(
            organization_id=card.organization_id,
            module=card.module,
            row_id=card.row_id,
            variant=variant,
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


def _find(db: DbSession, card: LotCard, variant: str = FIRST) -> SpecSheet | None:
    """Запись варианта. Вариант обязателен: на строке их теперь несколько, и
    поиск без него падал бы `MultipleResultsFound` на первом же заведённом."""
    return db.execute(
        select(SpecSheet).where(
            SpecSheet.module == card.module,
            SpecSheet.row_id == card.row_id,
            SpecSheet.variant == variant,
        )
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
        variant=sheet.variant,
        source_name=sheet.source_name,
        model=sheet.model,
        trouble=sheet.trouble,
        built_at=sheet.built_at.isoformat() if sheet.built_at else "",
    )
