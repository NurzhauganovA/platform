"""Эндпоинты замечаний к технической спецификации.

Общие для всех площадок: раздел передаётся в теле или в отборе. Свой набор в
каждом модуле означал бы три одинаковых обработчика и три места, где правила
об отправке расходятся, — а отправка необратима.

Права проверяются здесь, а не в интерфейсе. Список доступных действий приходит
в ответе (`can`), и это не замена проверке, а способ не рисовать кнопку,
которая ответит отказом.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import asdict
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from platform_api.auth.dependencies import CurrentUser, Db, requires_remarks
from platform_api.db.models import DiscussionOutcome, DiscussionStage
from platform_api.errors import SpokenError
from platform_api.modules import remarks

router = APIRouter(prefix="/remarks", tags=["Обсуждения"])


class RemarkOut(BaseModel):
    """Замечание в том виде, в каком его показывают.

    Себестоимости и маржи здесь нет и быть не может: сумма закупки — это
    плановая цена заказчика, она опубликована на портале. Наши цифры в
    обращение к заказчику не попадают ни при каких обстоятельствах.
    """

    id: str
    module: str
    row_id: str
    code: str
    title: str
    customer: str
    amount: float | None
    """Плановая сумма заказчика.

    Числом, а не точным десятичным. Точное уходит строкой «1603448.00», и в
    таблице оно так и стоит — без разрядов, слитно, нечитаемо. Копейки здесь и
    не нужны: цифра эта справочная, опубликована на портале, и решают по ней
    «крупная закупка или мелкая», а не сводят баланс.
    """

    enstru_code: str

    stage: str
    stage_name: str
    outcome: str
    outcome_name: str
    writing: str
    trouble: str

    deadline: str
    left: str
    burning: bool
    overdue: bool

    assignee: str
    assignee_id: str
    text: str
    ai_text: str
    ai_model: str
    answer: str
    sent_at: str
    answered_at: str
    can: list[str]


class TextIn(BaseModel):
    text: str


class MoveIn(BaseModel):
    to: DiscussionStage


class ResolveIn(BaseModel):
    outcome: DiscussionOutcome
    answer: str = ""


class AssignIn(BaseModel):
    assignee_id: uuid.UUID | None = None


@router.get("", summary="Очередь обсуждений")
def get_remarks(
    identity: CurrentUser,
    db: Db,
    module: Annotated[str | None, Query(description="Раздел площадки")] = None,
    stage: Annotated[DiscussionStage | None, Query(description="Этап")] = None,
    outcome: Annotated[DiscussionOutcome | None, Query(description="Итог")] = None,
    mine: Annotated[bool, Query(description="Только мои")] = False,
    burning: Annotated[bool, Query(description="Только горящие и просроченные")] = False,
    assignee_id: Annotated[uuid.UUID | None, Query(description="Ответственный")] = None,
    unowned: Annotated[bool, Query(description="Ничьи")] = False,
    category: Annotated[str | None, Query(description="Категория товара")] = None,
    enstru_code: Annotated[str | None, Query(description="Код ЕНС ТРУ")] = None,
    amount_from: Annotated[Decimal | None, Query(description="Сумма от")] = None,
    amount_to: Annotated[Decimal | None, Query(description="Сумма до")] = None,
    ends: Annotated[
        str | None,
        Query(description="Срок окончания: today, tomorrow, later, none"),
    ] = None,
    _guard: Annotated[None, requires_remarks] = None,
) -> list[RemarkOut]:
    found = remarks.listing(
        db,
        organization_id=identity.organization.id,
        role=identity.role,
        user_id=identity.user.id,
        module=module,
        stage=stage,
        outcome=outcome,
        mine=mine,
        burning=burning,
        assignee_id=assignee_id,
        unowned=unowned,
        category=category,
        enstru_code=enstru_code,
        amount_from=amount_from,
        amount_to=amount_to,
        ends=ends,
    )
    return [_out(item) for item in found]


@router.get("/{remark_id}", summary="Одно обсуждение")
def get_remark(
    remark_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_remarks] = None,
) -> RemarkOut:
    return _out(_one(db, identity, remark_id))


@router.put("/{remark_id}/text", summary="Поправить текст")
def put_text(
    remark_id: uuid.UUID,
    body: TextIn,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_remarks] = None,
) -> RemarkOut:
    """Правка перед отправкой.

    Написанное моделью остаётся нетронутым: сравнить отправленное с исходным
    нужно ровно тогда, когда пришёл отказ.
    """
    _act(
        lambda: remarks.save_text(
            db,
            organization_id=identity.organization.id,
            remark_id=remark_id,
            role=identity.role,
            user_id=identity.user.id,
            text=body.text,
        )
    )
    db.commit()
    return _out(_one(db, identity, remark_id))


@router.post("/{remark_id}/move", summary="Перевести на этап")
def post_move(
    remark_id: uuid.UUID,
    body: MoveIn,
    identity: CurrentUser,
    db: Db,
    request: Request,
    _guard: Annotated[None, requires_remarks] = None,
) -> RemarkOut:
    """Следующий этап: на проверку, юристам, отправлено, не требуется.

    Отправка необратима, и назад пути нет: замечание уже у заказчика.
    """
    _act(
        lambda: remarks.move(
            db,
            organization_id=identity.organization.id,
            remark_id=remark_id,
            role=identity.role,
            user_id=identity.user.id,
            to=body.to,
            settings=request.app.state.settings,
        )
    )
    db.commit()
    return _out(_one(db, identity, remark_id))


@router.post("/{remark_id}/resolve", summary="Записать итог")
def post_resolve(
    remark_id: uuid.UUID,
    body: ResolveIn,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_remarks] = None,
) -> RemarkOut:
    _act(
        lambda: remarks.resolve(
            db,
            organization_id=identity.organization.id,
            remark_id=remark_id,
            role=identity.role,
            outcome=body.outcome,
            answer=body.answer,
        )
    )
    db.commit()
    return _out(_one(db, identity, remark_id))


@router.post("/{remark_id}/assign", summary="Назначить ответственного")
def post_assign(
    remark_id: uuid.UUID,
    body: AssignIn,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_remarks] = None,
) -> RemarkOut:
    """Пустой ответственный снимает назначение.

    Ничьё горящее обсуждение и есть то, что теряется, поэтому снять
    ответственного можно так же просто, как назначить.
    """
    _act(
        lambda: remarks.assign(
            db,
            organization_id=identity.organization.id,
            remark_id=remark_id,
            assignee_id=body.assignee_id,
        )
    )
    db.commit()
    return _out(_one(db, identity, remark_id))


def _one(db: Db, identity: CurrentUser, remark_id: uuid.UUID) -> remarks.Remark:
    try:
        return remarks.one(
            db,
            organization_id=identity.organization.id,
            remark_id=remark_id,
            role=identity.role,
            user_id=identity.user.id,
        )
    except SpokenError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _act(what: Callable[[], object]) -> None:
    """Переводит отказ службы в ответ 403.

    Именно 403, а не 400: все отказы здесь про право сделать шаг, а не про
    испорченные данные, и человеку нужно понять, что дело в роли, а не в том,
    что он что-то не так ввёл.
    """
    try:
        what()
    except SpokenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


def _out(item: remarks.Remark) -> RemarkOut:
    fields = asdict(item)
    fields["can"] = list(item.can)
    fields["amount"] = float(item.amount) if item.amount is not None else None
    return RemarkOut(**fields)


__all__ = ["router"]
