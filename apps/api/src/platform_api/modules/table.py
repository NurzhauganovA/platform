"""Рабочая таблица модуля: те же колонки, что и в его книге Excel.

Сотрудник работает в двух местах — в браузере и в выгруженном файле, — и
колонки в них обязаны совпадать. Не «примерно те же», а буквально: человек
показывает коллеге экран, коллега открывает у себя файл, и они должны видеть
одно и то же. Поэтому таблица не описывается здесь второй раз, а собирается из
`Column` самого проекта — того же объекта, из которого пишется лист книги.

Тип `Column` у подключённых проектов одинаковый (заголовок, функция значения,
необязательная ссылка, ширина, числовой формат), и это не совпадение: оба
выгружают Excel одной и той же механикой. Платформе от него нужен утиный
интерфейс, а не импорт конкретного класса — иначе модуль оказался бы привязан
к внутренностям чужого пакета.

Права решаются здесь же, и это главное место файла. Себестоимость, маржа и
наша цена не должны уйти закупщику или наблюдателю — а таблица собирается
автоматически, и колонка, добавленная в проекте, попала бы в ответ сама.
Поэтому видимость задаётся явным списком, а незнакомая колонка считается
денежной: новая колонка не покажется никому, кроме тендерщика, пока человек не
решит иначе. Обратный порядок — «показываем, пока не запретили» — однажды
отдал бы наружу себестоимость, и узнали бы об этом от заказчика.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from platform_api.db.models import Role
from platform_api.logging import get_logger

logger = get_logger(__name__)


class Column(Protocol):
    """Колонка листа так, как её описывает подключённый проект.

    Поля объявлены свойствами только для чтения, и это не педантизм: у обоих
    проектов `Column` — замороженный `dataclass`, а изменяемое поле протокола
    с таким не совпадает. Читать нам и правда нужно только читать.
    """

    @property
    def title(self) -> str: ...

    @property
    def getter(self) -> Callable[[Any], Any]: ...

    @property
    def hyperlink(self) -> Callable[[Any], str | None] | None: ...

    @property
    def width(self) -> int: ...

    @property
    def number_format(self) -> str | None: ...


class Visibility(StrEnum):
    """Кому колонка видна."""

    ALL = "all"
    """Данные площадки: что покупают, сколько, до какого срока. Их видят все,
    у кого есть доступ к модулю."""

    SOURCING = "sourcing"
    """Работа закупщика: где брать, у кого, что проверить. Тендерщику и
    закупщику — им обоим это нужно, чтобы договориться."""

    MONEY = "money"
    """Себестоимость, маржа, наша цена. Только тендерщику: закупщику для его
    работы это не нужно, а уходит вместе с ним."""


_ROLE_ACCESS: dict[Role, frozenset[Visibility]] = {
    Role.ADMIN: frozenset(Visibility),
    Role.ANALYST: frozenset(Visibility),
    Role.BUYER: frozenset({Visibility.ALL, Visibility.SOURCING}),
    Role.VIEWER: frozenset({Visibility.ALL}),
}


# Числовые форматы Excel в то, что понимает браузер. Формат остаётся форматом,
# а не превращается в готовую строку: сортировать и складывать нужно числа,
# а «1 234 567,89 ₸» — уже текст.
_FORMATS: dict[str, str] = {
    "#,##0.00": "money",
    "#,##0.###": "quantity",
    "0.0%": "percent",
    "DD.MM.YYYY HH:MM": "datetime",
}


@dataclass(frozen=True, slots=True)
class ColumnOut:
    """Колонка так, как её рисует браузер."""

    key: str
    """Устойчивое имя для React и для сохранённых настроек показа. Считается
    от заголовка: заголовки внутри листа уникальны, а порядковый номер
    съезжает от любой вставки в середину."""

    title: str
    width: int
    format: str = "text"
    align: str = "left"
    sensitive: bool = False
    """Колонка с деньгами. Отдаётся, только если роль их видит; признак нужен
    интерфейсу, чтобы подписать таблицу «здесь себестоимость»."""

    compact: bool = False
    """Показывать значком, а не текстом.

    Для колонок, где важен сам факт и ссылка, а не содержимое: «Где купить» —
    это сорок четыре знака про поставщика, доставку и минимальную партию, и в
    строке списка они вытесняют маржу. Целиком они всё равно есть — в
    подсказке и в разборе, куда за подробностями и идут."""

    role: str = ""
    """Что колонка означает по смыслу: `total`, `price`, `cost`, `profit`,
    `margin`, `quantity`. Пусто — колонка без особой роли.

    По ролям браузер считает итоги по отобранному. Заголовки у разделов
    разные — «Маржа ₸», «Заработок всего, ₸», «заработок», — и разбирать их
    на месте значит сломаться на площадке, которую добавят следующей."""

    essential: bool = False
    """Показывать ли сразу, без прокрутки вбок.

    Отдаются все колонки, а не только главные: переключение «Главное / Все
    колонки» тогда мгновенное и не стоит ещё одного запроса. Скрывать по этому
    признаку безопасно — за ним нет тайны, в отличие от `sensitive`."""


@dataclass(frozen=True, slots=True)
class CellOut:
    """Значение одной ячейки.

    Число и текст разделены намеренно: по числу сортируют и подводят итог,
    текст только показывают. Слить их в одну строку значит потерять сортировку
    ровно там, где она нужнее всего, — в колонке маржи.
    """

    text: str = ""
    number: float | None = None
    link: str | None = None


@dataclass(frozen=True, slots=True)
class RowOut:
    """Строка таблицы."""

    cells: tuple[CellOut, ...]

    number: int = 0
    """Номер строки, которым её называют вслух: «посмотри сорок вторую».

    Считается один раз по всему списку и приходит вместе со строкой, а не
    рисуется браузером по месту. Иначе он менялся бы от каждого отбора и
    сортировки: один сотрудник говорит «сорок вторая», у второго на экране
    другой отбор — и сорок вторая у него чужая.

    Разбор им не открывают, для этого есть `id`: список пересобирается после
    каждой выгрузки, и номер закрепляется за строкой только до неё.
    """

    deadline: str | None = None
    """Когда закрывается приём предложений. Отдельным полем, а не разбором
    ячейки: колонок с датой может стать несколько, и угадывать, какая из них
    про срок, — верный способ однажды подсветить не ту."""

    id: str = ""
    """Чем открыть разбор. Идентификатор площадки, а не номер строки: номер
    съезжает от сортировки и отбора, и ссылка вела бы не туда."""

    focus: bool = True
    """Есть ли с этой строкой что делать.

    Отдаются все строки, и отбор идёт в браузере: переключение «Только нужное
    / Все строки» тогда мгновенное. Прятать по этому признаку безопасно — за
    ним нет тайны, в отличие от прав на колонки.
    """

    tone: str = ""
    """Как подсвечена строка: `good`, `warning`, `info`, `critical`, пусто.

    В книге Excel строки отбора залиты по вердикту, и на экране это должно
    выглядеть так же — глаз ищет зелёное, а не читает двести строк подряд.
    Цвет при этом ничего не значит сам по себе: вердикт словами стоит первой
    колонкой, иначе при дальтонизме «участвовать» и «не участвовать»
    неразличимы.
    """


@dataclass(frozen=True, slots=True)
class TableOut:
    """Готовая таблица: чем подписаны колонки и что в строках."""

    columns: tuple[ColumnOut, ...]
    rows: tuple[RowOut, ...]
    hidden_columns: int = 0
    """Сколько колонок скрыто по правам. Показывается человеку строкой «ещё 5
    колонок с себестоимостью видны тендерщику» — молча урезанная таблица
    выглядит как потерянные данные."""


def to_utc(value: datetime | None) -> datetime | None:
    """Приводит время к UTC с явным часовым поясом.

    Обходчики площадок записывают сроки в UTC, но SQLite часовой пояс не
    хранит, и обратно они приходят «голыми». Пока такое значение живёт внутри
    Python, это неважно; беда начинается, когда оно уезжает в браузер строкой
    без смещения — там его читают как местное время. В Алматы это пять часов
    разницы: срок, до которого ещё полдня, показывался истёкшим.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def is_past(value: datetime | None) -> bool:
    """Истёк ли срок. Пустой срок не считается истёкшим: «не знаем, когда» и
    «поздно» — разные ответы."""
    at = to_utc(value)
    return at is not None and at < datetime.now(UTC)


def sees_money(role: Role) -> bool:
    """Видит ли эта роль себестоимость и маржу.

    Нужно не только таблице: итоговые плитки над ней («заработаем столько-то»)
    считаются по тем же данным, и показывать их закупщику при скрытой колонке
    маржи значило бы отдать то же самое, только крупным шрифтом.
    """
    return Visibility.MONEY in _ROLE_ACCESS.get(role, frozenset({Visibility.ALL}))


def visible_columns(
    columns: Sequence[Column],
    policy: dict[str, Visibility],
    role: Role,
) -> list[tuple[int, Column, Visibility]]:
    """Отбирает колонки, которые эта роль имеет право видеть.

    Незнакомая колонка считается денежной. Так добавление колонки в проекте не
    может само по себе отдать себестоимость наружу: пока её не внесли в список,
    её видит только тендерщик.

    """
    allowed = _ROLE_ACCESS.get(role, frozenset({Visibility.ALL}))
    result: list[tuple[int, Column, Visibility]] = []
    for index, column in enumerate(columns):
        access = policy.get(column.title)
        if access is None:
            access = Visibility.MONEY
            logger.warning(
                "Колонка не описана в правах — показываем только тендерщику",
                column=column.title,
            )
        if access in allowed:
            result.append((index, column, access))
    return result


def build_table(
    columns: Sequence[Column],
    rows: Iterable[Any],
    *,
    policy: dict[str, Visibility],
    role: Role,
    tone: Callable[[Any], str] | None = None,
    focus: Callable[[Any], bool] | None = None,
    identity: Callable[[Any], str] | None = None,
    deadline: Callable[[Any], str | None] | None = None,
    compact: Collection[str] = (),
    essential: Sequence[str] = (),
    roles: dict[str, str] | None = None,
) -> TableOut:
    """Собирает таблицу из колонок проекта и его же строк.

    Значения берутся вызовом `getter` — тем самым, которым они попадают в
    книгу. Второй способ посчитать ячейку разошёлся бы с первым, и расхождение
    всплыло бы при сверке экрана с файлом.

    `roles` подписывает колонки по смыслу: где сумма, где себестоимость, где
    заработок. Без этого браузеру, который считает итоги по отобранному,
    остаётся угадывать по заголовку — а заголовки у трёх разделов разные
    («Маржа ₸», «Заработок всего, ₸», «заработок»), и угадывание ломается на
    той площадке, которую добавят следующей.
    """
    chosen = visible_columns(columns, policy, role)
    key_columns = frozenset(essential)
    icon_columns = frozenset(compact)
    materialized = list(rows)

    keys = _unique_keys([column.title for _index, column, _access in chosen])
    header = tuple(
        ColumnOut(
            key=key,
            title=column.title,
            width=column.width,
            format=_FORMATS.get(column.number_format or "", "text"),
            align="right" if column.number_format in _NUMERIC else "left",
            sensitive=access is Visibility.MONEY,
            essential=column.title in key_columns,
            compact=column.title in icon_columns,
            role=(roles or {}).get(column.title, ""),
        )
        for key, (_index, column, access) in zip(keys, chosen, strict=True)
    )

    body = tuple(
        RowOut(
            number=position,
            cells=tuple(_cell(column, item) for _index, column, _access in chosen),
            id=identity(item) if identity is not None else "",
            deadline=deadline(item) if deadline is not None else None,
            focus=focus(item) if focus is not None else True,
            tone=tone(item) if tone is not None else "",
        )
        for position, item in enumerate(materialized, start=1)
    )
    # Скрытыми считаем только те, что закрыты правами: их человек не увидит
    # никаким переключателем, и об этом стоит сказать. Колонки, убранные
    # кнопкой «Главное», он прячет сам и знает об этом.
    return TableOut(columns=header, rows=body, hidden_columns=len(columns) - len(chosen))


_NUMERIC = frozenset({"#,##0.00", "#,##0.###", "0.0%"})
"""Числовые форматы прижимаются вправо: столбик цифр читается по последнему
разряду, и разнобой по левому краю сравнивать мешает."""


def _cell(column: Column, item: Any) -> CellOut:
    """Одна ячейка: значение и, если есть, ссылка.

    Ошибка в `getter` не роняет таблицу целиком. Строк несколько сотен, и одна
    сломанная — не повод показать человеку пустой экран вместо работы; на её
    месте останется прочерк, а причина уйдёт в лог.
    """
    try:
        value = column.getter(item)
    except Exception as exc:  # pragma: no cover — защита от правки в проекте
        logger.warning("Ячейка не посчиталась", column=column.title, error=str(exc))
        return CellOut(text="—")

    link: str | None = None
    if column.hyperlink is not None:
        try:
            link = column.hyperlink(item)
        except Exception:  # pragma: no cover
            link = None

    return _value(value, link)


def _value(value: Any, link: str | None) -> CellOut:
    """Приводит значение ячейки к тому, что уходит в JSON.

    `Decimal` идёт числом, а не строкой: по нему сортируют и подводят итог.
    Точность при этом теряется — но в таблице на экране её и не требуется,
    а деньги считаются в ядре и в `Decimal`.
    """
    if value is None or value == "":
        return CellOut(link=link)
    if isinstance(value, bool):
        return CellOut(text="да" if value else "", link=link)
    if isinstance(value, Decimal):
        return CellOut(number=float(value), link=link)
    if isinstance(value, int | float):
        return CellOut(number=float(value), link=link)
    if isinstance(value, datetime):
        # Со смещением: без него браузер прочитает время как местное.
        return CellOut(text=(to_utc(value) or value).isoformat(), link=link)
    if isinstance(value, date):
        return CellOut(text=value.isoformat(), link=link)
    return CellOut(text=str(value), link=link)


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}  # fmt: skip

_SYMBOLS = {"%": "percent", "₸": "kzt", "№": "num"}
"""Символы, которые несут смысл заголовка. Без них «Маржа %» и «Маржа ₸»
дают один и тот же ключ — а это две разные колонки, и путать их дорого."""


def _key(title: str) -> str:
    """Имя колонки для интерфейса: латиницей, без пробелов.

    Кириллица в ключе доживает до адресной строки, когда человек делится
    ссылкой, и превращается там в «%D0%BC…» — читать перестаёт и он, и лог.
    """
    parts: list[str] = []
    for character in title.casefold():
        if character in _SYMBOLS:
            parts.append(f"_{_SYMBOLS[character]}")
        elif character in _TRANSLIT:
            parts.append(_TRANSLIT[character])
        elif character.isascii() and character.isalnum():
            parts.append(character)
        else:
            parts.append("_")
    key = "_".join(filter(None, "".join(parts).split("_")))
    return key or "column"


def _unique_keys(titles: Sequence[str]) -> list[str]:
    """Ключи колонок, гарантированно различные.

    Одинаковый заголовок в одном листе — вещь редкая, но не невозможная, а
    два одинаковых ключа в таблице означают, что браузер перепутает колонки
    местами при перерисовке.
    """
    seen: dict[str, int] = {}
    keys: list[str] = []
    for title in titles:
        key = _key(title)
        seen[key] = seen.get(key, 0) + 1
        keys.append(key if seen[key] == 1 else f"{key}_{seen[key]}")
    return keys


__all__ = [
    "CellOut",
    "Column",
    "ColumnOut",
    "RowOut",
    "TableOut",
    "Visibility",
    "build_table",
    "is_past",
    "sees_money",
    "to_utc",
    "visible_columns",
]
