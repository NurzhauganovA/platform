"""Разбор одной строки: общие формы для всех модулей.

В сводной таблице места хватает только на цифры. Но цифре «маржа 18 %» никто
не поверит, пока не увидит, откуда она взялась: что нашли на складе, почём
берут конкуренты, сколько удержит площадка. Разбор отвечает на «откуда»,
причём в том порядке, в каком вопросы возникают: сначала решение — стоит ли
читать дальше, потом деньги, потом что нашлось, потом конкуренты, и только в
конце — на что смотреть перед подачей.

Порядок не выдуман здесь: ровно так устроен лист разбора в книге OMarket.
Человек читает одно и то же в двух местах, и переставлять разделы местами
значит заставлять его искать заново.

Формы общие, а наполнение собирает каждый модуль сам — в своём `core.py`, из
уже посчитанных ядром значений. Считать здесь нечего: разбор только
показывает то, что уже сложилось.

Права те же, что и у таблицы: раздел с деньгами не уходит закупщику. Отбор
идёт по разделам целиком, а не по отдельным полям — иначе «Себестоимость»
исчезла бы, а «Источник цены» рядом с ней остался, и по нему всё стало бы
понятно.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from platform_api.db.models import Role
from platform_api.modules.table import Visibility, sees_money, to_utc


@dataclass(frozen=True, slots=True)
class Field:
    """Строка разбора: подпись и значение.

    Число и текст разделены так же, как в таблице: по числу браузер наводит
    формат, текст показывает как есть.
    """

    label: str
    text: str = ""
    number: float | None = None
    format: str = "text"
    """`text`, `money`, `percent`, `quantity`, `datetime`."""

    link: str | None = None
    tone: str = ""
    """`good`, `warning`, `critical` — когда значение само по себе тревожно:
    просроченный срок, отрицательная маржа, слабое совпадение."""

    note: str = ""
    """Оговорка к значению. «комиссия не известна — карточка не читалась»
    важнее самой цифры: без неё маржа завышена ровно на комиссию."""


@dataclass(frozen=True, slots=True)
class Table:
    """Маленькая таблица внутри раздела — предложения конкурентов и подобное."""

    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    aligns: tuple[str, ...] = ()

    link_column: int = 0
    """В какой колонке живёт ссылка. Название товара повторяется в каждой
    строке и переносится на пять строк — ссылка на нём читается хуже, чем на
    короткой «площадке», по которой строки как раз и различаются."""

    links: tuple[str, ...] = ()
    """Куда ведёт строка — по одной ссылке на строку, пусто если некуда.

    Находка без ссылки — обещание, а не поставщик: менеджер идёт искать её
    заново в поиске, и половину находок не находит."""

    picks: tuple[str, ...] = ()
    """Чем выбрать строку для пересчёта. Пусто — строка не выбирается."""

    chosen: tuple[str, ...] = ()
    """Какие строки сейчас в расчёте. Без отметки непонятно, откуда взялась
    себестоимость, и человек считает её на глаз заново."""


@dataclass(frozen=True, slots=True)
class Section:
    """Раздел разбора."""

    title: str
    fields: tuple[Field, ...] = ()
    table: Table | None = None
    note: str = ""
    """Пояснение к разделу целиком. Место для того, что человек иначе
    спросит вслух: почему цифра такая и чему тут верить."""

    access: Visibility = Visibility.ALL
    empty: str = ""
    """Что сказать, если раздела нет. «Конкуренты ещё не подавались» и
    «карточку не читали» — разные ответы, и молчание вместо них хуже обоих."""

    collapsed: bool = False
    """Показывать свёрнутым: заголовок и сколько внутри, содержимое по щелчку.

    Для разделов, которые нужны не каждый раз, но занимают экран. Разбор
    открывают ради цифры и оснований к ней; развёрнутые на две сотни строк
    предложения конкурентов отодвигают их за нижний край, и до денег человек
    прокручивает.

    Решает это модуль, а не браузер: длина раздела ничего не говорит о том,
    насколько он нужен — «как считали себестоимость» короче, но важнее.
    """


@dataclass(frozen=True, slots=True)
class Detail:
    """Разбор целиком."""

    id: str
    title: str
    subtitle: str = ""
    verdict: str = ""
    tone: str = ""
    url: str | None = None
    """Ссылка на карточку у площадки. То, ради чего разбор чаще всего и
    открывают: посмотреть первоисточник."""

    sections: tuple[Section, ...] = field(default_factory=tuple)
    hidden_sections: int = 0

    lot: Any = None
    """Закупка целиком, если позиций в ней больше одной.

    Приходит и до объединения: сам факт «в этой закупке ещё две позиции» —
    уже предупреждение. Заработок по одной позиции ничего не значит, пока не
    видно остальных, которые придётся поставить вместе с ней.
    """


def for_role(detail: Detail, role: Role) -> Detail:
    """Убирает разделы, которых эта роль видеть не должна.

    Считает убранное, чтобы интерфейс мог сказать об этом словами: молча
    урезанный разбор выглядит как недоделанный.
    """
    money = sees_money(role)
    allowed = tuple(
        section for section in detail.sections if section.access is not Visibility.MONEY or money
    )
    hidden = len(detail.sections) - len(allowed)
    return Detail(
        lot=detail.lot,
        id=detail.id,
        title=detail.title,
        subtitle=detail.subtitle,
        verdict=detail.verdict,
        tone=detail.tone,
        url=detail.url,
        sections=allowed,
        hidden_sections=hidden,
    )


# --- сборка значений -------------------------------------------------------


def money_field(label: str, value: Any, **extra: Any) -> Field:
    """Денежное поле. Пустое значение — прочерк, а не ноль: «не знаем, почём»
    и «бесплатно» это разные ответы."""
    number = _number(value)
    if number is None:
        return Field(label=label, text="—", **extra)
    return Field(label=label, number=number, format="money", **extra)


def percent_field(label: str, value: Any, **extra: Any) -> Field:
    number = _number(value)
    if number is None:
        return Field(label=label, text="—", **extra)
    return Field(label=label, number=number, format="percent", **extra)


def text_field(label: str, value: Any, **extra: Any) -> Field:
    text = "" if value is None else str(value).strip()
    return Field(label=label, text=text or "—", **extra)


def date_field(label: str, value: datetime | date | None, **extra: Any) -> Field:
    """Дата со смещением: без него браузер прочитает время как местное, и в
    Алматы срок уедет на пять часов."""
    if value is None:
        return Field(label=label, text="—", **extra)
    if isinstance(value, datetime):
        value = to_utc(value) or value
    return Field(label=label, text=value.isoformat(), format="datetime", **extra)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal | int | float):
        return float(value)
    return None


__all__ = [
    "Detail",
    "Field",
    "Section",
    "Table",
    "date_field",
    "for_role",
    "money_field",
    "percent_field",
    "text_field",
]
