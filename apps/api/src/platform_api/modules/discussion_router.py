"""Эндпоинты обсуждения.

Общие для всех разделов: раздел передаётся в адресе. Свой набор в каждом
модуле означал бы четыре одинаковых обработчика и четыре места, где правила
о правке чужих сообщений расходятся.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from platform_api.auth.dependencies import CurrentUser, Db, requires_read
from platform_api.errors import SpokenError
from platform_api.modules import discussion

router = APIRouter(prefix="/discussion", tags=["Обсуждение"])


class MessageOut(BaseModel):
    """Реплика в ветке."""

    id: str
    body: str
    author: str
    author_id: str = ""
    created_at: str
    edited_at: str = ""


class MessageIn(BaseModel):
    """Что пишут."""

    body: str


@router.get("/{module}/{row_id:path}", summary="Обсуждение строки")
def get_thread(
    module: str,
    row_id: str,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_read] = None,
) -> list[MessageOut]:
    found = discussion.messages(db, identity.organization.id, module, row_id)
    return [MessageOut(**asdict(item)) for item in found]


@router.post("/{module}/{row_id:path}", summary="Написать", status_code=201)
def post_message(
    module: str,
    row_id: str,
    body: MessageIn,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_read] = None,
) -> MessageOut:
    """Добавляет реплику в ветку строки.

    Писать может любой, у кого есть доступ к разделу: обсуждение затем и
    заводили, чтобы снабженец мог сказать «этого поставщика мы ждали три
    месяца» там же, где тендерщик смотрит цену.
    """
    try:
        added = discussion.add(
            db,
            identity.organization.id,
            identity.user.id,
            module=module,
            row_id=row_id,
            body=body.body,
        )
    except SpokenError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return MessageOut(**asdict(added))


@router.patch("/messages/{message_id}", summary="Поправить своё")
def patch_message(
    message_id: uuid.UUID,
    body: MessageIn,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_read] = None,
) -> MessageOut:
    try:
        changed = discussion.edit(
            db, identity.organization.id, identity.user.id, message_id, body.body
        )
    except SpokenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    db.commit()
    return MessageOut(**asdict(changed))


@router.delete("/messages/{message_id}", summary="Убрать", status_code=204)
def delete_message(
    message_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_read] = None,
) -> None:
    try:
        discussion.remove(db, identity.organization.id, identity.user, identity.role, message_id)
    except SpokenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    db.commit()


__all__ = ["router"]
