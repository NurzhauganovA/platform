"""Вход, выход и «кто я».

Кука ставится с тремя ограничениями сразу, и каждое закрывает свой способ её
угнать: `httponly` — от чтения скриптом при XSS, `samesite=lax` — от перехода
с чужого сайта, `secure` — от передачи по открытому HTTP.

`samesite=lax` вместо `strict` осознанно: при `strict` человек, пришедший по
ссылке на закупку из почты, попадает на форму входа, хотя вошёл минуту назад.
Опасны здесь запросы, меняющие данные, а они у нас идут методом POST, который
`lax` и так не пропускает с чужого сайта.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from platform_api.auth.dependencies import CurrentUser, Db
from platform_api.auth.service import (
    AuthError,
    authenticate,
    open_session,
    resolve_session,
    revoke_all_sessions,
    revoke_session,
)
from platform_api.config import Settings, get_settings
from platform_api.db.base import utcnow
from platform_api.db.models import AuditEntry, Role, Session
from platform_api.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Доступ"])


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    organization: str | None = Field(
        default=None, description="Организация, если человек состоит в нескольких"
    )


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str


class MeOut(BaseModel):
    """Кто вошёл и что ему доступно."""

    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    organization: OrganizationOut
    last_login_at: datetime | None = None


@router.post("/login", summary="Войти")
def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    db: Db,
    settings: Annotated[Settings, Depends(get_settings)],
) -> MeOut:
    try:
        user, organization, role = authenticate(
            db, payload.email, payload.password, organization_slug=payload.organization
        )
    except AuthError as exc:
        _audit(db, None, None, "login_failed", str(payload.email), request)
        # Фиксируем до отказа, и это обязательно. Ответ уходит исключением, а
        # оно откатывает транзакцию запроса — вместе со счётчиком неудачных
        # попыток и записью в журнале. То есть защита от подбора существовала
        # бы только в юнит-тестах: через HTTP счётчик всякий раз обнулялся, а
        # серия попыток не оставляла следа.
        db.commit()
        # Задержки и подсказок нет: сообщение одно на все причины отказа.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    _session, token = open_session(
        db,
        user,
        organization,
        ttl_hours=settings.auth.session_ttl_hours,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=_client_ip(request),
    )
    _set_session_cookie(response, token, settings)
    _audit(db, user.id, organization.id, "login", str(user.email), request)
    logger.info("Вход выполнен", user_id=str(user.id), organization=organization.slug)

    return MeOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=role,
        organization=OrganizationOut(
            id=organization.id, name=organization.name, slug=organization.slug
        ),
        last_login_at=user.last_login_at,
    )


@router.post("/logout", summary="Выйти")
def logout(
    request: Request,
    response: Response,
    db: Db,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, bool]:
    """Гасит сессию и стирает куку.

    Без входа тоже отвечает успехом: «выйти» — действие идемпотентное, и
    отказывать здесь не за что.
    """
    token = request.cookies.get(settings.auth.session_cookie, "")
    identity = resolve_session(db, token) if token else None
    if identity is not None:
        session = db.get(Session, identity.session_id)
        if session is not None:
            revoke_session(db, session)
        _audit(db, identity.user.id, identity.organization.id, "logout", "", request)

    response.delete_cookie(
        settings.auth.session_cookie,
        httponly=True,
        samesite="lax",
        secure=settings.auth.secure_cookies,
        path="/",
    )
    return {"ok": True}


@router.get("/me", summary="Кто я")
def me(identity: CurrentUser) -> MeOut:
    return MeOut(
        id=identity.user.id,
        email=identity.user.email,
        full_name=identity.user.full_name,
        role=identity.role,
        organization=OrganizationOut(
            id=identity.organization.id,
            name=identity.organization.name,
            slug=identity.organization.slug,
        ),
        last_login_at=identity.user.last_login_at,
    )


@router.post("/logout-everywhere", summary="Выйти на всех устройствах")
def logout_everywhere(
    identity: CurrentUser,
    response: Response,
    db: Db,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, int]:
    """Гасит все сессии.

    Нужно ровно тогда, когда есть подозрение, что чужой получил доступ, — и в
    этот момент важно, чтобы кнопка была под рукой, а не в переписке с
    администратором.
    """
    count = revoke_all_sessions(db, identity.user.id)
    _audit(db, identity.user.id, identity.organization.id, "logout_everywhere", "", request)
    response.delete_cookie(
        settings.auth.session_cookie,
        httponly=True,
        samesite="lax",
        secure=settings.auth.secure_cookies,
        path="/",
    )
    return {"revoked": count}


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        settings.auth.session_cookie,
        token,
        max_age=settings.auth.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.auth.secure_cookies,
        path="/",
    )


def _client_ip(request: Request) -> str:
    """Адрес обратившегося.

    За обратным прокси настоящий адрес приходит заголовком, но верить ему
    можно только когда прокси наш: иначе любой подставит в журнал чужой адрес.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded and request.app.state.settings.is_prod:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _audit(
    db: Db,
    user_id: uuid.UUID | None,
    organization_id: uuid.UUID | None,
    action: str,
    target: str,
    request: Request,
) -> None:
    db.add(
        AuditEntry(
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            target=target[:255],
            ip_address=_client_ip(request),
            created_at=utcnow(),
        )
    )
