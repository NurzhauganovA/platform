"""Уведомления глазами администратора: работают или нет и почему.

Только администратору. За реестром — почты всех сотрудников и то, кто из них
что себе отключил; вопрос «почему Ивану не приходит» задаёт не Иван.

**Состояние берётся у сервиса, а не собирается здесь.** Реестр его: человек
привязывает Телеграм в боте и там же отключает канал, и платформа об этом не
узнаёт до следующего запроса. Свой список означал бы экран, который бодро
показывает привязку, снятую вчера.

Нужен затем, что молчание уведомлений выглядит одинаково при пяти разных
причинах: сервис не поднят, до него нет хода из контейнера, ключи разошлись,
человека нет в реестре, Телеграм не привязан. Платформа ни одну из них наружу
не бросает — отказ сервиса пишется предупреждением, а человеку отвечают
дальше, — и разбирать это приходилось по журналам трёх наборов контейнеров.

Отдельная страница, а не строка в сводке готовности. `/api/health` опрашивает
Docker раз в несколько секунд, и поход по сети в чужой сервис на каждый такой
опрос — это пять секунд ожидания в проверке, у которой срок пять секунд:
здоровый API помечался бы больным, а на его здоровье построен `depends_on`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from platform_api.auth.dependencies import CurrentUser, Db, require_roles
from platform_api.config import Settings
from platform_api.db.models import Membership, Role, User
from platform_api.logging import get_logger
from platform_api.modules import notify

logger = get_logger(__name__)

router = APIRouter(prefix="/notify", tags=["Уведомления"])

OnlyAdmin = Annotated[None, Depends(require_roles(Role.ADMIN))]


class ServiceOut(BaseModel):
    """Что сейчас с сервисом уведомлений."""

    configured: bool
    """Задан ли адрес и ключ. Нет — уведомления выключены, и это не поломка:
    у разработчика сервис обычно не поднят."""

    url: str
    reachable: bool
    """Дошли ли до него из контейнера платформы. Именно из контейнера: с самой
    машины сервис отвечает и тогда, когда из сети платформы хода нет."""

    trouble: str
    """Чем кончилась попытка, если не дошли. Словами, как их сказал httpx."""

    telegram: bool = False
    email: bool = False
    environment: str = ""
    problems: list[str] = []
    """Пробелы в настройках, которые сервис нашёл у себя сам."""

    database: bool = False
    """Жива ли база сервиса. Отдельно от `reachable`: его собственная проверка
    готовности смотрит настройки каналов и отвечает «всё на месте» с
    недоступным PostgreSQL — поэтому спрашивается сводка, она без базы не
    собирается."""

    recipients: int = 0
    active: int = 0
    telegram_linked: int = 0
    pending: int = 0
    sent_24h: int = 0
    failed_24h: int = 0
    skipped_24h: int = 0

    people_here: int = 0
    """Сколько сотрудников в базе платформы. Рядом с `recipients` отвечает на
    вопрос, доехал ли реестр: ноль против десяти — это не «никому не приходит»,
    а «сервис не знает никого»."""


class PersonOut(BaseModel):
    """Сотрудник и его уведомления."""

    user_id: str
    email: str
    full_name: str
    role: str
    is_active: bool = True
    known: bool = False
    """Знает ли его сервис. Нет — до него не доехал реестр, и бот на его почту
    отвечает «если такая почта заведена, код отправлен», не отправляя ничего:
    ответ одинаков для известного и неизвестного адреса намеренно, иначе по
    нему проверяют, кто у нас работает."""

    telegram_linked: bool = False
    telegram_name: str = ""
    telegram_enabled: bool = True
    email_enabled: bool = True
    stop_reason: str = ""
    """Человек остановил бота. Тогда Телеграм молчит, а привязка на месте."""


class DeliveryOut(BaseModel):
    """Одна попытка доставки — та, у которой лежит причина неудачи."""

    channel: str
    status: str
    target: str = ""
    error: str = ""


class SentOut(BaseModel):
    """Что отправляли человеку и чем это кончилось."""

    at: str
    event: str
    title: str
    deliveries: list[DeliveryOut] = []


@router.get("", summary="Состояние уведомлений")
def state(identity: CurrentUser, db: Db, request: Request, _guard: OnlyAdmin = None) -> ServiceOut:
    """Сводка: дошли ли до сервиса, жива ли его база, что у него настроено."""
    settings: Settings = request.app.state.settings
    return _state(db, settings)


def _state(db: Db, settings: Settings) -> ServiceOut:
    people_here = len(list(db.scalars(select(User.id).where(User.is_active.is_(True)))))

    if not settings.notify.ready:
        return ServiceOut(
            configured=False,
            url=settings.notify.url,
            reachable=False,
            trouble="Адрес или ключ не заданы: PLATFORM__NOTIFY__URL и PLATFORM__NOTIFY__TOKEN",
            people_here=people_here,
        )

    health = notify.alive(settings)
    if health is None:
        return ServiceOut(
            configured=True,
            url=settings.notify.url,
            reachable=False,
            trouble=(
                "Сервис не ответил. Он не поднят, либо из контейнера платформы "
                "до него нет хода: на Linux `host.docker.internal` ведёт на мост "
                "Docker, а порт сервиса открыт только на петле машины — в его "
                "`.env` для этого есть `API_BIND`."
            ),
            people_here=people_here,
        )

    numbers = notify.counters(settings)
    return ServiceOut(
        configured=True,
        url=settings.notify.url,
        reachable=True,
        trouble="",
        telegram=bool(health.get("telegram")),
        email=bool(health.get("email")),
        environment=str(health.get("environment", "")),
        problems=[str(one) for one in health.get("problems", [])],
        database=numbers is not None,
        recipients=int((numbers or {}).get("recipients", 0)),
        active=int((numbers or {}).get("active", 0)),
        telegram_linked=int((numbers or {}).get("telegram_linked", 0)),
        pending=int((numbers or {}).get("pending", 0)),
        sent_24h=int((numbers or {}).get("sent_24h", 0)),
        failed_24h=int((numbers or {}).get("failed_24h", 0)),
        skipped_24h=int((numbers or {}).get("skipped_24h", 0)),
        people_here=people_here,
    )


@router.get("/people", summary="Сотрудники и их уведомления")
def people(
    identity: CurrentUser, db: Db, request: Request, _guard: OnlyAdmin = None
) -> list[PersonOut]:
    """Список сотрудников платформы, дополненный состоянием из сервиса.

    Список ведёт платформа, состояние — сервис. Так видно и тех, кого сервис не
    знает вовсе: именно они и есть самая частая причина молчания, а в списке
    сервиса их по определению нет.
    """
    settings: Settings = request.app.state.settings
    rows = db.execute(
        select(User, Membership.role)
        .join(Membership, Membership.user_id == User.id, isouter=True)
        .order_by(User.full_name, User.email)
    ).all()

    known: dict[str, dict[str, Any]] = {}
    for one in notify.everyone(settings) or ():
        known[str(one.get("user_id"))] = one

    out: list[PersonOut] = []
    for user, role in rows:
        there = known.get(str(user.id))
        tg = (there or {}).get("telegram") or {}
        out.append(
            PersonOut(
                user_id=str(user.id),
                email=user.email,
                full_name=user.full_name,
                role=str(role.value) if role is not None else "",
                is_active=bool(user.is_active),
                known=there is not None,
                telegram_linked=bool(tg.get("linked")),
                telegram_name=str(tg.get("username") or tg.get("display_name") or ""),
                telegram_enabled=bool((there or {}).get("telegram_enabled", True)),
                email_enabled=bool((there or {}).get("email_enabled", True)),
                stop_reason=str(tg.get("stop_reason") or ""),
            )
        )
    return out


@router.post("/sync", summary="Выгрузить сотрудников в сервис")
def sync(identity: CurrentUser, db: Db, request: Request, _guard: OnlyAdmin = None) -> ServiceOut:
    """Отдаёт сервису список сотрудников целиком.

    Кнопкой, а не только при запуске платформы. Выгрузка идёт один раз — на
    старте, — и если сервис в тот момент был недоступен, реестр остаётся пустым
    до следующей перезагрузки платформы. Выглядит это как полностью неработающие
    уведомления: бот не находит почту, письмо с кодом не уходит, и починка
    сводится к перезапуску всей платформы посреди рабочего дня.
    """
    settings: Settings = request.app.state.settings
    if not settings.notify.ready:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Сервис уведомлений не настроен: нет адреса или ключа",
        )

    rows = db.execute(
        select(User, Membership.role).join(Membership, Membership.user_id == User.id, isouter=True)
    ).all()
    notify.sync_all(
        settings,
        [
            {
                "user_id": str(user.id),
                "email": user.email,
                "full_name": user.full_name,
                "role": str(role.value) if role is not None else "",
                "is_active": bool(user.is_active),
            }
            for user, role in rows
        ],
    )
    logger.info("Реестр выгружен вручную", by=str(identity.user.id), count=len(rows))
    return _state(db, settings)


@router.get("/people/{user_id}/history", summary="Что отправляли человеку")
def sent(
    user_id: uuid.UUID, identity: CurrentUser, request: Request, _guard: OnlyAdmin = None
) -> list[SentOut]:
    """Последние отправки и причина неудачи у каждой.

    Причина лежит у доставки, а не у уведомления: «Телеграм не привязан»,
    «тихие часы», отказ почтового сервера словами. Это и есть ответ на «почему
    не пришло» — остальное про него только догадки.
    """
    settings: Settings = request.app.state.settings
    return [
        SentOut(
            at=str(one.get("created_at", "")),
            event=str(one.get("event", "")),
            title=str(one.get("title", "")),
            deliveries=[
                DeliveryOut(
                    channel=str(way.get("channel", "")),
                    status=str(way.get("status", "")),
                    target=str(way.get("target", "")),
                    error=str(way.get("error", "")),
                )
                for way in one.get("deliveries", [])
            ],
        )
        for one in notify.history(settings, user_id=user_id, limit=10)
    ]


@router.post("/people/{user_id}/test", summary="Отправить проверочное")
def test(
    user_id: uuid.UUID, identity: CurrentUser, request: Request, _guard: OnlyAdmin = None
) -> SentOut:
    """Ставит человеку проверочное сообщение и отдаёт, чем это кончилось.

    Настройку канала проверяют не разбором журнала, а сообщением, которое либо
    пришло, либо нет.
    """
    settings: Settings = request.app.state.settings
    if not notify.check(settings, user_id=user_id):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Сервис уведомлений заявку не принял. Проверьте состояние выше.",
        )
    recent = notify.history(settings, user_id=user_id, limit=1)
    one = recent[0] if recent else {}
    return SentOut(
        at=str(one.get("created_at", "")),
        event=str(one.get("event", "")),
        title=str(one.get("title", "")),
        deliveries=[
            DeliveryOut(
                channel=str(way.get("channel", "")),
                status=str(way.get("status", "")),
                target=str(way.get("target", "")),
                error=str(way.get("error", "")),
            )
            for way in one.get("deliveries", [])
        ],
    )
