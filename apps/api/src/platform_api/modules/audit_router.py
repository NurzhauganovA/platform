"""Журнал действий: кто что сделал и когда.

Только администратору. Журнал отвечает на вопрос «кто это сделал», и человек, о
котором его спрашивают, не должен видеть, что именно о нём записано, — иначе
первым делом он посмотрит, попал ли туда.

Отбор с сервера, а не в браузере. Записей растёт по строке на каждое изменение:
за месяц работы отдела это десятки тысяч, и тянуть их в память вкладки ради
одного дня — мегабайты по сети на каждое нажатие.

Страницами, а не целиком. Журнал читают с конца: интересно последнее, а не всё.
Порядок обратный по времени — тот же, в каком о событиях спрашивают.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import String, func, or_, select

from platform_api.auth.dependencies import CurrentUser, Db, require_roles
from platform_api.db.models import AuditEntry, Role, User

# Префикс без `/api`: роутер подключается внутрь общего, у которого он уже
# есть. Свой полный путь дал бы `/api/api/audit`.
router = APIRouter(prefix="/audit", tags=["Журнал"])

OnlyAdmin = Annotated[None, Depends(require_roles(Role.ADMIN))]

PAGE = 50
"""Сколько записей на странице. Полсотни — экран с прокруткой на один поворот
колеса: больше человек за раз не читает, а меньше означает лишнее нажатие."""


class EntryOut(BaseModel):
    """Одна запись журнала."""

    id: str
    at: str
    who: str
    """Имя на сегодня. Пусто — действие без входа: неудачная попытка войти или
    прогон по расписанию."""

    who_id: str
    role: str
    """Роль на момент действия, а не сегодняшняя: роли меняют, и «юрист
    отправил» через полгода превращается в «менеджер отправил»."""

    action: str
    target: str
    method: str
    path: str
    status: int
    duration_ms: int
    ip: str
    payload: dict[str, Any]


class PageOut(BaseModel):
    items: list[EntryOut]
    total: int
    page: int
    pages: int


class PersonOut(BaseModel):
    id: str
    name: str


@router.get("", summary="Журнал действий")
def listing(
    identity: CurrentUser,
    db: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    user_id: uuid.UUID | None = None,
    method: str = "",
    since: datetime | None = None,
    until: datetime | None = None,
    only_failed: bool = False,
    search: str = "",
    _guard: OnlyAdmin = None,
) -> PageOut:
    """Страница журнала под отбором.

    `only_failed` — отдельным признаком, а не поиском по коду ответа. Отказы
    спрашивают чаще остального: «кто пытался и не смог» — первый вопрос, когда
    что-то пошло не так, а набирать «403 или 404 или 500» руками никто не станет.
    """
    query = select(AuditEntry).where(
        or_(
            AuditEntry.organization_id == identity.organization.id,
            AuditEntry.organization_id.is_(None),
        )
    )
    if user_id is not None:
        query = query.where(AuditEntry.user_id == user_id)
    if method:
        query = query.where(AuditEntry.method == method.upper())
    if since is not None:
        query = query.where(AuditEntry.created_at >= since)
    if until is not None:
        query = query.where(AuditEntry.created_at <= until)
    if only_failed:
        query = query.where(AuditEntry.status >= 400)
    if search.strip():
        needle = f"%{search.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(AuditEntry.action).like(needle),
                func.lower(AuditEntry.path).like(needle),
                func.lower(AuditEntry.target).like(needle),
                func.lower(AuditEntry.payload.cast(String)).like(needle),
            )
        )

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(
        db.scalars(
            query.order_by(AuditEntry.created_at.desc()).offset((page - 1) * PAGE).limit(PAGE)
        )
    )

    known = _people(db, rows)
    return PageOut(
        items=[_out(row, known) for row in rows],
        total=total,
        page=page,
        pages=max(1, (total + PAGE - 1) // PAGE),
    )


@router.get("/people", summary="Кто есть в журнале")
def people(identity: CurrentUser, db: Db, _guard: OnlyAdmin = None) -> list[PersonOut]:
    """Сотрудники для отбора. Все действующие, а не только наследившие: отбор по
    человеку без записей отвечает «ничего не делал», и это ответ."""
    rows = db.execute(
        select(User.id, User.full_name, User.email)
        .where(User.is_active.is_(True))
        .order_by(User.full_name, User.email)
    ).all()
    return [PersonOut(id=str(one), name=name or email) for one, name, email in rows]


def _people(db: Db, rows: list[AuditEntry]) -> dict[uuid.UUID, str]:
    """Имена разом, а не по запросу на строку: пятьдесят строк — пятьдесят
    обращений к базе, и это заметно на каждом листании."""
    ids = {row.user_id for row in rows if row.user_id}
    if not ids:
        return {}
    found = db.execute(select(User.id, User.full_name, User.email).where(User.id.in_(ids))).all()
    return {one: (name or email) for one, name, email in found}


def _out(row: AuditEntry, known: dict[uuid.UUID, str]) -> EntryOut:
    return EntryOut(
        id=str(row.id),
        at=row.created_at.isoformat(),
        who=known.get(row.user_id, "") if row.user_id else "",
        who_id=str(row.user_id) if row.user_id else "",
        role=row.role,
        action=row.action,
        target=row.target,
        method=row.method,
        path=row.path,
        status=row.status,
        duration_ms=row.duration_ms,
        ip=row.ip_address,
        payload=row.payload or {},
    )


__all__ = ["router"]
