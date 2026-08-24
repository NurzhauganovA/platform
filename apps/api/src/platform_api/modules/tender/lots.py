"""Лот: закупка, которую ведут целиком, а не позициями по отдельности.

В заключении заказчика позиций бывает три. По одной из них заработок выглядит
отличным, её берут в работу — и там выясняется, что поставить придётся все
три, а на остальных двух убыток. В сумме по лоту сделка убыточна, и увидеть
это надо до подачи, а не после.

Разделение на позиции при этом правильное и остаётся: у каждой свой код ЕНС,
своё количество и свои поставщики, и в реестре закупку ищут по коду позиции.
Лот — это связь поверх них, а не отмена разделения.

Решение о лоте принимает человек и хранится оно здесь, в базе платформы. Из
данных его не вывести: позиции одного заключения иногда разыгрываются порознь,
и «одна папка — один лот» было бы догадкой, которая иногда стоит денег.

Считается лот сложением уже посчитанных ядром строк. Своего расчёта тут нет —
ни себестоимости, ни маржи по позиции; складываются готовые числа, и маржа
лота получается из его же суммы и себестоимости.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select

from platform_api.db.models import TenderLot

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session as DbSession


@dataclass(frozen=True, slots=True)
class Position:
    """Одна позиция лота — то, чем переключаются в разборе."""

    id: str
    title: str
    quantity: Decimal | None
    total: Decimal | None
    cost: Decimal | None
    margin_percent: Decimal | None
    tone: str
    current: bool


@dataclass(frozen=True, slots=True)
class Lot:
    """Закупка целиком: её позиции и сумма по ним."""

    key: str
    """Короткое имя лота. Считается от папки, а не от строк: строки
    пересобираются с каждым разбором, а папка у закупки одна."""

    merged: bool
    """Объединил ли человек эти позиции. Пока нет — лот показывается только
    как возможность: «в этой закупке ещё две позиции»."""

    positions: tuple[Position, ...]
    total: Decimal | None
    cost: Decimal | None
    profit: Decimal | None
    margin_percent: Decimal | None
    priced: int
    """По скольким позициям себестоимость известна. Без этого числа итог по
    лоту врёт в лучшую сторону: непосчитанная позиция выглядит бесплатной."""

    @property
    def size(self) -> int:
        return len(self.positions)


def key_of(folder_path: str) -> str:
    """Короткое имя лота по папке закупки."""
    return hashlib.sha1(folder_path.encode()).hexdigest()[:12]


def merged_folders(db: DbSession, organization_id: uuid.UUID) -> frozenset[str]:
    """Папки, объединённые в лоты этой организацией.

    Одним запросом на всю таблицу: рабочий список строит лот для каждой из
    восьмисот строк, и обращение на строку было бы восемьюстами обращений к
    базе ради нескольких десятков записей.
    """
    rows = db.execute(
        select(TenderLot.folder_path).where(TenderLot.organization_id == organization_id)
    ).scalars()
    return frozenset(rows)


def merge(db: DbSession, organization_id: uuid.UUID, user_id: uuid.UUID, folder: str) -> None:
    """Объединяет позиции закупки в лот. Повтор ничего не меняет."""
    if folder in merged_folders(db, organization_id):
        return
    db.add(
        TenderLot(
            organization_id=organization_id,
            created_by_id=user_id,
            folder_path=folder,
        )
    )


def split(db: DbSession, organization_id: uuid.UUID, folder: str) -> None:
    """Разъединяет лот обратно на позиции."""
    db.execute(
        delete(TenderLot).where(
            TenderLot.organization_id == organization_id,
            TenderLot.folder_path == folder,
        )
    )


def collect(rows: Any, current: Any, merged: bool, *, money: bool) -> Lot | None:
    """Лот вокруг открытой позиции. `None` — позиция в закупке одна.

    `rows` — весь отбор; лот собирается по той же папке. Отдельного запроса к
    ядру это не стоит: отбор уже собран и лежит в кэше.

    `money` закрывает суммы от тех, кому не положено видеть себестоимость.
    Итог по лоту — та же себестоимость, только сложенная: отдать её потому,
    что она в другом поле, значило бы обойти собственные права.
    """
    from platform_api.modules.tender.worklist import row_id, tone_of

    folder = current.row.folder_path or ""
    if not folder:
        return None
    свои = [item for item in rows if (item.row.folder_path or "") == folder]
    if len(свои) < 2:
        return None

    открыт = row_id(current)
    позиции = tuple(
        Position(
            id=row_id(item),
            title=item.row.title,
            quantity=item.row.quantity,
            total=item.row.total,
            cost=item.row.cost if money else None,
            margin_percent=item.row.margin_percent if money else None,
            tone=tone_of(item),
            current=row_id(item) == открыт,
        )
        for item in свои
    )

    сумма = _sum(item.row.total for item in свои)
    себестоимость = _sum(item.row.cost for item in свои) if money else None
    заработок = сумма - себестоимость if сумма is not None and себестоимость is not None else None
    маржа = (
        (заработок / сумма * 100).quantize(Decimal("0.1"))
        if заработок is not None and сумма
        else None
    )
    return Lot(
        key=key_of(folder),
        merged=merged,
        positions=позиции,
        total=сумма,
        cost=себестоимость,
        profit=заработок,
        margin_percent=маржа,
        priced=sum(1 for item in свои if item.row.cost is not None),
    )


def _sum(values: Any) -> Decimal | None:
    """Сумма известных значений. `None` — не известно ни одного.

    Ноль и «неизвестно» тут разные вещи: закупка без единой посчитанной
    позиции не стоит ноль, по ней просто нечего складывать.
    """
    known = [value for value in values if value is not None]
    return sum(known, Decimal(0)) if known else None


__all__ = ["Lot", "Position", "collect", "key_of", "merge", "merged_folders", "split"]
