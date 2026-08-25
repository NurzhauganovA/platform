"""Раздел «В работе»: путь лота между отделом разбора и снабжением.

Права здесь не отдельные, а те же, что и везде: тендерщик — это отдел
разбора, закупщик — снабжение. Заводить третье понятие ролей значило бы
завести и третье место, где их надо не забыть согласовать.

Что видит снабжение, решает сервер, а не вёрстка. Ему уходят только позиции,
их документы и «где купить»: суммы закупки, себестоимость и маржа не уходят
даже в ответе. Спрятать в браузере и отдать в JSON — значит отдать.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, status

from platform_api.auth.dependencies import CurrentUser, Db, requires_read
from platform_api.db.base import utcnow
from platform_api.db.models import Role, TenderWork, TenderWorkOption, WorkStage
from platform_api.errors import SpokenError, unavailable
from platform_api.modules.schemas import (
    DetailField,
    WorkAskIn,
    WorkHandOverIn,
    WorkListItemOut,
    WorkOptionIn,
    WorkOptionOut,
    WorkOut,
    WorkPositionOut,
)
from platform_api.modules.table import sees_money
from platform_api.modules.tender import works

router = APIRouter()


@router.get("/works", summary="Лоты в работе")
def list_works(
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_read] = None,
) -> list[WorkListItemOut]:
    """Что сейчас в работе и у кого.

    Снабжению видно только то, что ему передали: до передачи там нечего
    смотреть, а после возврата лот снова у разбора.
    """
    from sqlalchemy import select

    rows = db.execute(
        select(TenderWork)
        .where(TenderWork.organization_id == identity.organization.id)
        .order_by(TenderWork.created_at.desc())
    ).scalars()
    money = sees_money(identity.role)
    return [
        WorkListItemOut(
            id=str(work.id),
            code=work.code,
            title=work.title,
            customer=work.customer,
            stage=work.stage.value,
            positions=len(work.positions),
            total=_money(_sum(position.total for position in work.positions)) if money else None,
            sent_at=work.sent_at.isoformat() if work.sent_at else None,
            waiting_days=_waiting(work),
        )
        for work in rows
        if works.visible_for(work, identity.role)
    ]


@router.post("/item/{item_id}/work", summary="Взять лот в работу", status_code=201)
def take_into_work(
    item_id: str,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_read] = None,
) -> WorkOut:
    """Берёт лот, в котором лежит эта позиция, в работу.

    Позиции переписываются в работу целиком, а не ссылкой: отбор
    пересобирается при каждом прогоне ядра, названия у позиций меняются — а
    работа должна остаться той же, с теми же позициями, по которым её взяли.

    Вместе с ними переписываются находки: их разбор и будет подтверждать.
    """
    from platform_api.modules.tender import lots, worklist

    if not sees_money(identity.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Брать лоты в работу может отдел разбора",
        )

    try:
        rows = worklist.ranked()
    except Exception as exc:
        raise unavailable("Отбор закупок", exc) from exc

    found = next((item for item in rows if worklist.row_id(item) == item_id), None)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Такой закупки нет в отборе"
        )

    состав = lots.positions_of(
        db, identity.organization.id, (found.row.folder_path or "", found.row.title)
    )
    свои = (
        [item for item in rows if (item.row.folder_path or "", item.row.title) in состав]
        if состав
        else [found]
    )
    коды = _codes(db, rows)

    try:
        work = works.take(
            db,
            identity.organization.id,
            identity.user.id,
            code=коды.get(worklist.row_id(found), found.row.title[:32]),
            title=found.row.title,
            customer=found.row.customer or "",
            positions=[_draft(item, коды) for item in свои],
        )
    except SpokenError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.commit()
    return _work_out(work, identity.role)


@router.get("/works/{work_id}", summary="Лот в работе")
def get_work(
    work_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_read] = None,
) -> WorkOut:
    work = _mine(db, identity, work_id)
    return _work_out(work, identity.role)


@router.post("/works/{work_id}/options/{option_id}/choose", summary="Подтвердить поставщика")
def choose_option(
    work_id: uuid.UUID,
    option_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_read] = None,
) -> WorkOut:
    """Разбор выбирает вариант; остальные найденные по позиции убираются.

    Снабжению они не нужны — разбор их уже посмотрел и отверг.
    """
    work = _mine(db, identity, work_id)
    _do(lambda: works.choose(db, work, option_id))
    db.commit()
    return _work_out(work, identity.role)


@router.post("/works/{work_id}/positions/{position_id}/ask", summary="Заказать поиск снабжению")
def ask_supply(
    work_id: uuid.UUID,
    position_id: uuid.UUID,
    body: WorkAskIn,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_read] = None,
) -> WorkOut:
    work = _mine(db, identity, work_id)
    _do(lambda: works.ask(db, work, position_id, body.name))
    db.commit()
    return _work_out(work, identity.role)


@router.post("/works/{work_id}/positions/{position_id}/options", summary="Добавить вариант")
def add_option(
    work_id: uuid.UUID,
    position_id: uuid.UUID,
    body: WorkOptionIn,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_read] = None,
) -> WorkOut:
    work = _mine(db, identity, work_id)
    _do(lambda: works.add(db, work, position_id, identity.user.id, **body.model_dump()))
    db.commit()
    return _work_out(work, identity.role)


@router.patch("/works/{work_id}/options/{option_id}", summary="Поправить вариант")
def edit_option(
    work_id: uuid.UUID,
    option_id: uuid.UUID,
    body: WorkOptionIn,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_read] = None,
) -> WorkOut:
    """Снабжение правит цену, ссылку, поставщика и срок поставки.

    Срок здесь появляется впервые: до снабжения его никто не знает, а от него
    зависит, беремся ли мы вообще.
    """
    work = _mine(db, identity, work_id)
    _do(lambda: works.edit(db, work, option_id, identity.user.id, **body.model_dump()))
    db.commit()
    return _work_out(work, identity.role)


@router.delete("/works/{work_id}/options/{option_id}", summary="Убрать вариант")
def drop_option(
    work_id: uuid.UUID,
    option_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_read] = None,
) -> WorkOut:
    work = _mine(db, identity, work_id)
    _do(lambda: works.drop(db, work, option_id))
    db.commit()
    return _work_out(work, identity.role)


@router.post("/works/{work_id}/hand-over", summary="Передать другому отделу")
def hand_over(
    work_id: uuid.UUID,
    body: WorkHandOverIn,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_read] = None,
) -> WorkOut:
    """Разбор передаёт снабжению, снабжение возвращает разбору.

    Кнопка одна, и это правильно: у каждого отдела «отправить» значит своё, и
    выбирать получателя из списка — лишний вопрос там, где ответ один.
    """
    work = _mine(db, identity, work_id)
    _do(lambda: works.hand_over(db, work, body.note))
    db.commit()
    return _work_out(work, identity.role)


# ---------------------------------------------------------------------------


def _mine(db: Db, identity: Any, work_id: uuid.UUID) -> TenderWork:
    """Работа этой организации, доступная этой роли."""
    try:
        work = works.one(db, identity.organization.id, work_id)
    except SpokenError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not works.visible_for(work, identity.role):
        # Не 403: иначе по коду ответа перебирается, какие лоты существуют.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Такой работы нет")
    return work


def _do(action: Any) -> None:
    """Выполняет действие, превращая отказ правила в понятный ответ."""
    try:
        action()
    except SpokenError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def _draft(item: Any, коды: dict[str, str]) -> works.Draft:
    from platform_api.modules.tender.worklist import row_id

    row = item.row
    return works.Draft(
        folder_path=row.folder_path or "",
        title=row.title,
        code=коды.get(row_id(item), ""),
        quantity=row.quantity,
        unit="",
        total=row.total,
        options=tuple(
            {
                "name": line.position,
                "supplier": line.supplier or "",
                "marketplace": line.marketplace or "",
                "country": line.country or "",
                "url": line.url or "",
                "price": line.landed,
                "note": line.note or "",
            }
            for line in (row.market or [])
        ),
    )


def _codes(db: Db, rows: Any) -> dict[str, str]:
    from platform_api.modules import codes
    from platform_api.modules.tender.columns import CODE_PREFIX
    from platform_api.modules.tender.worklist import row_id

    return codes.assign(db, "tender", CODE_PREFIX, [row_id(item) for item in rows])


def _work_out(work: TenderWork, role: Role) -> WorkOut:
    money = sees_money(role)
    positions = sorted(work.positions, key=lambda position: position.ordering)
    return WorkOut(
        id=str(work.id),
        code=work.code,
        title=work.title,
        customer=work.customer,
        stage=work.stage.value,
        analysis_note=work.analysis_note,
        supply_note=work.supply_note,
        sent_at=work.sent_at.isoformat() if work.sent_at else None,
        positions=[_position_out(position, money=money) for position in positions],
        total=_money(_sum(position.total for position in positions)) if money else None,
        cost=_money(_cost(positions)) if money else None,
        priced=sum(1 for position in positions if _picked(position) is not None),
    )


def _position_out(position: Any, *, money: bool) -> WorkPositionOut:
    from platform_api.modules.tender.detail import documents_of

    return WorkPositionOut(
        id=str(position.id),
        code=position.code,
        title=position.title,
        quantity=_money(position.quantity),
        unit=position.unit,
        # Сумма закупки — деньги: по ней считают маржу, а снабжению её знать
        # не нужно и не положено.
        total=_money(position.total) if money else None,
        options=[
            WorkOptionOut(
                id=str(option.id),
                source=option.source.value,
                name=option.name,
                supplier=option.supplier,
                marketplace=option.marketplace,
                country=option.country,
                url=option.url,
                price=_money(option.price),
                delivery_days=option.delivery_days,
                note=option.note,
                chosen=option.chosen,
            )
            for option in position.options
        ],
        documents=[
            DetailField.model_validate(asdict(field))
            for field in documents_of(position.folder_path, position.title)
        ],
    )


def _picked(position: Any) -> TenderWorkOption | None:
    """Вариант, по которому считается себестоимость: самый дешёвый с ценой."""
    с_ценой = [option for option in position.options if option.price is not None]
    return min(с_ценой, key=lambda option: option.price) if с_ценой else None


def _cost(positions: Any) -> Decimal | None:
    """Себестоимость по подтверждённым вариантам.

    Только по тем позициям, где цена уже есть. Непосчитанная позиция не стоит
    ноль — она не выяснена, и молчаливый ноль сделал бы лот выгоднее, чем он
    есть, ровно в том месте, ради которого лот и собирали.
    """
    известные: list[Decimal] = []
    for position in positions:
        выбран = _picked(position)
        if выбран is not None and выбран.price is not None:
            известные.append(выбран.price * (position.quantity or Decimal(1)))
    return sum(известные, Decimal(0)) if известные else None


def _sum(values: Any) -> Decimal | None:
    known = [value for value in values if value is not None]
    return sum(known, Decimal(0)) if known else None


def _money(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _waiting(work: TenderWork) -> int | None:
    """Сколько дней лот лежит у нынешнего отдела."""
    if work.stage is WorkStage.ANALYSIS or work.sent_at is None:
        return None
    return (utcnow() - work.sent_at).days


__all__ = ["router"]
