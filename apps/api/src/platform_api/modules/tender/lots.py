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

from sqlalchemy import delete, func, select

from platform_api.db.models import TenderLot, TenderLotPosition

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterable

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
    """Короткое имя лота: его собственное после объединения, иначе — от папки
    закупки. Строки для этого не годятся: они пересобираются с каждым
    разбором."""

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
    """Имя подсказанного лота — по папке закупки.

    Нужно до объединения: лота ещё нет, а строки в списке уже надо чем-то
    связать между собой.
    """
    return hashlib.sha1(folder_path.encode()).hexdigest()[:12]


def membership(db: DbSession, organization_id: uuid.UUID) -> dict[tuple[str, str], str]:
    """Какая позиция в каком лоте: «папка и название» → имя лота.

    Одним запросом на всю организацию. Рабочий список спрашивает это для
    каждой из восьмисот строк, и обращение на строку было бы восемьюстами
    запросов ради нескольких десятков записей.
    """
    rows = db.execute(
        select(
            TenderLotPosition.folder_path, TenderLotPosition.title, TenderLotPosition.lot_id
        ).where(TenderLotPosition.organization_id == organization_id)
    ).all()
    return {(folder, title): str(lot_id)[:12] for folder, title, lot_id in rows}


def lot_of(db: DbSession, organization_id: uuid.UUID, folder: str, title: str) -> TenderLot | None:
    """Лот, в котором лежит эта позиция."""
    return db.execute(
        select(TenderLot)
        .join(TenderLotPosition)
        .where(
            TenderLotPosition.organization_id == organization_id,
            TenderLotPosition.folder_path == folder,
            TenderLotPosition.title == title,
        )
    ).scalar_one_or_none()


def positions_of(
    db: DbSession, organization_id: uuid.UUID, position: tuple[str, str]
) -> frozenset[tuple[str, str]] | None:
    """Состав лота, в котором лежит эта позиция. `None` — лота нет.

    Пустое множество и «лота нет» — разные ответы: по первому разбор показал
    бы объединённый лот без позиций, по второму — подсказку из соседей папки.
    """
    lot = lot_of(db, organization_id, *position)
    if lot is None:
        return None
    return frozenset((item.folder_path, item.title) for item in lot.positions)


def gather(
    db: DbSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    anchor: tuple[str, str],
    members: Iterable[tuple[str, str]],
) -> TenderLot:
    """Собирает лот вокруг позиции, добавляя к нему перечисленные.

    Лот у позиции уже есть — дополняется он, а не заводится второй: иначе одна
    и та же поставка оказалась бы в двух лотах с разными итогами, и какой из
    них правда, потом не выяснить.

    Позиция, занятая чужим лотом, переезжает в этот. Так человек и исправляет
    ошибку разбора: увидел, что позиция приписана не туда, и перенёс.
    """
    lot = lot_of(db, organization_id, *anchor)
    if lot is None:
        lot = TenderLot(organization_id=organization_id, created_by_id=user_id)
        db.add(lot)
        db.flush()
        _attach(db, lot, organization_id, anchor)
    for member in members:
        _attach(db, lot, organization_id, member)
    return lot


def _attach(
    db: DbSession, lot: TenderLot, organization_id: uuid.UUID, position: tuple[str, str]
) -> None:
    """Переносит позицию в этот лот, откуда бы она ни была."""
    folder, title = position
    existing = db.execute(
        select(TenderLotPosition).where(
            TenderLotPosition.organization_id == organization_id,
            TenderLotPosition.folder_path == folder,
            TenderLotPosition.title == title,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.lot_id = lot.id
        return
    db.add(
        TenderLotPosition(
            lot_id=lot.id,
            organization_id=organization_id,
            folder_path=folder,
            title=title,
        )
    )


def detach(db: DbSession, organization_id: uuid.UUID, position: tuple[str, str]) -> None:
    """Убирает позицию из лота. Остался один участник — лота больше нет.

    Лот из одной позиции ничем не отличается от позиции без лота, но выглядит
    иначе: полоса в списке и карточка в разборе обещают связь, которой нет.
    """
    folder, title = position
    lot = lot_of(db, organization_id, folder, title)
    if lot is None:
        return
    db.execute(
        delete(TenderLotPosition).where(
            TenderLotPosition.organization_id == organization_id,
            TenderLotPosition.folder_path == folder,
            TenderLotPosition.title == title,
        )
    )
    db.flush()
    осталось = db.execute(
        select(func.count())
        .select_from(TenderLotPosition)
        .where(TenderLotPosition.lot_id == lot.id)
    ).scalar_one()
    if осталось < 2:
        _dissolve(db, lot)


def dissolve(db: DbSession, organization_id: uuid.UUID, position: tuple[str, str]) -> None:
    """Разъединяет лот целиком — по любой его позиции."""
    lot = lot_of(db, organization_id, *position)
    if lot is not None:
        _dissolve(db, lot)


def _dissolve(db: DbSession, lot: TenderLot) -> None:
    db.execute(delete(TenderLotPosition).where(TenderLotPosition.lot_id == lot.id))
    db.execute(delete(TenderLot).where(TenderLot.id == lot.id))


def collect(
    rows: Any,
    current: Any,
    *,
    members: frozenset[tuple[str, str]] | None = None,
    key: str = "",
    money: bool = True,
) -> Lot | None:
    """Лот вокруг открытой позиции. `None` — собирать нечего.

    `members` — состав, который человек утвердил. Пусто — лота ещё нет, и
    вместо него показывается подсказка: остальные позиции той же папки. Это
    не одно и то же. Папка — догадка разбора, и она ошибается: заказчик
    раскладывает один лот по двум папкам, а бывает и наоборот. Утверждённый
    состав ошибаться не может, потому что его собрал человек.

    `money` закрывает суммы от тех, кому не положено видеть себестоимость.
    Итог по лоту — та же себестоимость, только сложенная: отдать её потому,
    что она в другом поле, значило бы обойти собственные права.
    """
    from platform_api.modules.tender.worklist import row_id, tone_of

    folder = current.row.folder_path or ""
    if not folder:
        return None

    if members is None:
        свои = [item for item in rows if (item.row.folder_path or "") == folder]
        merged = False
        имя = key_of(folder)
    else:
        свои = [item for item in rows if (item.row.folder_path or "", item.row.title) in members]
        merged = True
        имя = key or key_of(folder)
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
        key=имя,
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


__all__ = [
    "Lot",
    "Position",
    "collect",
    "detach",
    "dissolve",
    "gather",
    "key_of",
    "lot_of",
    "membership",
    "positions_of",
]
