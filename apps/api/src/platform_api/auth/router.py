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

from platform_api.auth import profile
from platform_api.auth.dependencies import CurrentUser, Db
from platform_api.auth.passwords import WeakPasswordError
from platform_api.auth.service import (
    AuthError,
    Identity,
    authenticate,
    open_session,
    resolve_session,
    revoke_all_sessions,
    revoke_session,
)
from platform_api.config import Settings, get_settings
from platform_api.db.models import Role, Session
from platform_api.errors import SpokenError
from platform_api.logging import get_logger
from platform_api.modules import notify

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
        # Фиксируем до отказа, и это обязательно. Ответ уходит исключением, а
        # оно откатывает транзакцию запроса — вместе со счётчиком неудачных
        # попыток и записью в журнале. То есть защита от подбора существовала
        # бы только в юнит-тестах: через HTTP счётчик всякий раз обнулялся, а
        # серия попыток не оставляла следа.
        db.commit()
        # Задержки и подсказок нет: сообщение одно на все причины отказа.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    session, token = open_session(
        db,
        user,
        organization,
        ttl_hours=settings.auth.session_ttl_hours,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=_client_ip(request),
    )
    _set_session_cookie(response, token, settings)
    # Кто вошёл — посреднику журнала. У входа нет зависимости `CurrentUser`, и
    # без этого удачный вход записывался бы действием «без входа»: в журнале
    # он есть, а чей — не сказано.
    request.state.identity = Identity(
        user=user, organization=organization, role=role, session_id=session.id
    )
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


class ProfileIn(BaseModel):
    """Что человек меняет о себе сам."""

    full_name: str = Field(max_length=255)
    email: EmailStr


class PasswordIn(BaseModel):
    current: str = Field(min_length=1)
    fresh: str = Field(min_length=1)


class ChannelsIn(BaseModel):
    """Куда слать. Пусто — не трогать: экран шлёт то, что человек переключил."""

    telegram_enabled: bool | None = None
    email_enabled: bool | None = None


class ChannelsOut(BaseModel):
    """Настройки уведомлений так, как их видит профиль.

    `ready` — поднят ли сервис вообще. Экран без этого не может отличить
    «Телеграм не привязан» от «настройки сейчас недоступны», а это разные
    ответы: в первом случае надо написать боту, во втором — подождать.
    """

    ready: bool = False
    telegram_enabled: bool = True
    email_enabled: bool = True
    telegram_linked: bool = False
    bot_username: str = ""


class ResetAskIn(BaseModel):
    email: EmailStr


class ResetAskOut(BaseModel):
    """Куда ушёл код. Пусто — никуда, но экран об этом не говорит.

    Одинаковый ответ на известный и неизвестный адрес: разные превратили бы
    форму в способ проверять, работает ли у нас такой-то человек.
    """

    channel: str = ""


class ResetDoIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)
    fresh: str = Field(min_length=1)


@router.patch("/me", summary="Изменить имя и почту")
def patch_me(
    body: ProfileIn,
    identity: CurrentUser,
    db: Db,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> MeOut:
    """Своё имя и почту человек правит сам.

    Почта — не косметика: по ней входят, на неё приходит код привязки Телеграма
    и код сброса пароля. Поэтому смена сразу уходит в сервис уведомлений.
    """
    try:
        profile.rename(
            db,
            settings,
            user=identity.user,
            full_name=body.full_name,
            email=str(body.email),
        )
    except SpokenError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return me(identity)


@router.post("/password", summary="Сменить пароль")
def post_password(
    body: PasswordIn,
    identity: CurrentUser,
    db: Db,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, bool]:
    """Меняет пароль по старому и гасит все сессии, включая эту.

    Включая эту — намеренно. Пароль меняют в том числе потому, что его
    подсмотрели; оставить открытой хотя бы одну вкладку значит не сменить
    ничего. Человек входит заново, новым паролем — это и есть проверка, что он
    его запомнил.
    """
    try:
        profile.change_password(db, user=identity.user, current=body.current, fresh=body.fresh)
    except (SpokenError, WeakPasswordError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    response.delete_cookie(
        settings.auth.session_cookie,
        httponly=True,
        samesite="lax",
        secure=settings.auth.secure_cookies,
        path="/",
    )
    return {"ok": True}


@router.get("/me/channels", summary="Куда приходят уведомления")
def get_channels(
    identity: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChannelsOut:
    """Что настроено у человека в сервисе уведомлений.

    Сервис не поднят — отвечаем `ready=false`, а не ошибкой: уведомления не
    обязательная часть работы, и профиль должен открываться без них.
    """
    if not settings.notify.ready:
        return ChannelsOut(bot_username=settings.notify.bot_username)
    found = notify.channels(settings, user_id=identity.user.id) or {}
    return ChannelsOut(
        ready=True,
        telegram_enabled=bool(found.get("telegram_enabled", True)),
        email_enabled=bool(found.get("email_enabled", True)),
        telegram_linked=bool((found.get("telegram") or {}).get("linked")),
        bot_username=settings.notify.bot_username,
    )


@router.patch("/me/channels", summary="Выбрать канал уведомлений")
def patch_channels(
    body: ChannelsIn,
    identity: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChannelsOut:
    """Канал выбирает сам сотрудник.

    Не администратор: один читает Телеграм и не открывает почту неделями,
    другой наоборот, и решать это за них значит рассылать в пустоту.
    """
    if not settings.notify.ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Сервис уведомлений сейчас недоступен",
        )
    notify.set_channels(
        settings,
        user_id=identity.user.id,
        telegram_enabled=body.telegram_enabled,
        email_enabled=body.email_enabled,
    )
    return get_channels(identity, settings)


@router.delete("/me/telegram", summary="Отвязать Телеграм")
def delete_telegram(
    identity: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChannelsOut:
    """Отвязывает чат. Уведомления после этого идут почтой: человек отказался
    от Телеграма, а не от работы."""
    if settings.notify.ready:
        notify.unlink_telegram(settings, user_id=identity.user.id)
    return get_channels(identity, settings)


@router.post("/reset/ask", summary="Запросить код смены пароля")
def post_reset_ask(
    body: ResetAskIn,
    db: Db,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ResetAskOut:
    """Шлёт шестизначный код туда, где человека можно достать.

    Куда именно — решает сервис уведомлений: привязан Телеграм, значит в него;
    нет — письмом. Повторять это знание здесь значит однажды отправить код в
    чат, который вчера отвязали.

    Без входа: сюда приходят как раз тогда, когда войти не могут.
    """
    try:
        sent = profile.ask_reset(db, settings, email=str(body.email))
    except SpokenError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    db.commit()
    return ResetAskOut(channel=sent.channel)


@router.post("/reset/confirm", summary="Сменить пароль по коду")
def post_reset_confirm(body: ResetDoIn, db: Db) -> dict[str, bool]:
    """Ставит новый пароль по коду и гасит все сессии.

    Гасит намеренно: сброс пароля и есть тот случай, когда доступ мог
    достаться чужому, и его открытая вкладка должна закрыться вместе с ним.
    """
    try:
        profile.finish_reset(db, email=str(body.email), code=body.code, fresh=body.fresh)
    except (SpokenError, WeakPasswordError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return {"ok": True}


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
