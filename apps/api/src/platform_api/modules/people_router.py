"""Сотрудники и роли: кого пускаем и что ему можно.

Только администратору. За экраном — почты всех сотрудников, их роли и право
выдать себе любое из них; вопрос «кто может видеть себестоимость» задаёт не тот,
кому её не показывают.

**Роли — это наборы прав, а не имена.** Встроенных десять, они описывают отделы
так, как те сложились у нас, и их права заданы кодом: ответ на вопрос «что
сломается, если поменять» не должен выясняться на работающей платформе. Своя
роль заводится рядом и выбирает права из того же закрытого списка — выдать
право, которого никто не проверяет, нельзя по построению.

**Человека можно выключить и можно удалить.** Выключение — обычный случай:
доступ закрыт, а всё, что он делал, осталось при нём и читается по имени.
Удаление — когда записи быть не должно вовсе: завели по ошибке, ушёл
подрядчик, попросили убрать персональные данные.

Работа переживает удаление. Подписи и лента событий держат имя автора копией
рядом со ссылкой: ссылка обнуляется, а имя остаётся — иначе «кто это одобрил»
через полгода отвечалось бы пустой строкой. Уносит удаление только его
собственное: сессии, коды восстановления и место в организации. Лоты, которые
он вёл, становятся ничьими — и это правда, вести их больше некому.

Последнего администратора не удаляем: платформа без него остаётся без
управления доступами, и вернуть их можно только руками в базе.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from platform_api.auth import passwords
from platform_api.auth.dependencies import CurrentUser, Db, requires
from platform_api.auth.permissions import (
    BUILT_IN,
    PERMISSION_ABOUT,
    PERMISSION_NAMES,
    ROLE_ABOUT,
    ROLE_NAMES,
    Permission,
)
from platform_api.db.models import CustomRole, Membership, Role, Session, User
from platform_api.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/people", tags=["Сотрудники"])

OnlyAdmin = Annotated[None, Depends(requires(Permission.ADMIN))]

# Ключ своей роли: латиницей, без пробелов. Он попадает в журнал действий и в
# ответы API, а кириллица в них превращается в проценты с цифрами.
KEY = r"^[a-z][a-z0-9_-]{1,31}$"


class PermissionOut(BaseModel):
    """Право так, как его видит администратор."""

    key: str
    title: str
    about: str


class RoleOut(BaseModel):
    """Роль и её права."""

    key: str
    title: str
    about: str
    permissions: list[str]
    built_in: bool
    """Встроенная. Права заданы кодом и не правятся; удалить нельзя."""

    people: int
    """Сколько человек её носит. По нему видно, что удалять уже поздно."""


class PersonOut(BaseModel):
    """Сотрудник в списке администратора."""

    id: str
    email: str
    full_name: str
    role: str
    role_title: str
    is_active: bool
    last_login_at: str = ""
    locked: bool = False
    """Вход заперт после серии промахов. Администратор снимает это сам —
    иначе человек ждёт полчаса и звонит."""


class PersonIn(BaseModel):
    email: EmailStr
    full_name: str = ""
    role: str = Role.VIEWER.value
    """Ключ роли: встроенной или своей. Умолчание — наблюдатель: новый человек
    получает меньше доступа, а не больше."""

    password: str = Field(min_length=1)


class PersonPatch(BaseModel):
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


class RoleIn(BaseModel):
    key: str = Field(pattern=KEY)
    title: str = Field(min_length=1, max_length=120)
    description: str = ""
    permissions: list[str] = []


class RolePatch(BaseModel):
    title: str | None = None
    description: str | None = None
    permissions: list[str] | None = None


@router.get("/permissions", summary="Какие права бывают")
def get_permissions(identity: CurrentUser, _guard: OnlyAdmin = None) -> list[PermissionOut]:
    """Список прав. Закрыт кодом: право появляется вместе с местом, которое его
    проверяет, — и выдать несуществующее нельзя."""
    return [
        PermissionOut(
            key=item.value,
            title=PERMISSION_NAMES[item],
            about=PERMISSION_ABOUT[item],
        )
        for item in Permission
    ]


@router.get("/roles", summary="Роли и их права")
def get_roles(identity: CurrentUser, db: Db, _guard: OnlyAdmin = None) -> list[RoleOut]:
    """Встроенные роли и заведённые в платформе — одним списком.

    Одним, потому что выбирают из них тоже одним движением: администратору
    неважно, откуда роль взялась, ему важно, что она даёт.
    """
    counted = _counts(db, identity.organization.id)
    out = [
        RoleOut(
            key=role.value,
            title=ROLE_NAMES[role],
            about=ROLE_ABOUT[role],
            permissions=sorted(item.value for item in BUILT_IN[role]),
            built_in=True,
            people=counted.get(role.value, 0),
        )
        for role in Role
    ]
    own = db.scalars(
        select(CustomRole)
        .where(CustomRole.organization_id == identity.organization.id)
        .order_by(CustomRole.title)
    )
    out += [
        RoleOut(
            key=role.key,
            title=role.title,
            about=role.description,
            permissions=sorted(role.permissions),
            built_in=False,
            people=counted.get(role.key, 0),
        )
        for role in own
    ]
    return out


@router.post("/roles", summary="Завести роль", status_code=201)
def post_role(body: RoleIn, identity: CurrentUser, db: Db, _guard: OnlyAdmin = None) -> RoleOut:
    """Заводит свою роль с правами из закрытого списка."""
    if body.key in {role.value for role in Role}:
        raise _spoken(f"Ключ «{body.key}» занят встроенной ролью")
    exists = db.scalar(
        select(CustomRole.id).where(
            CustomRole.organization_id == identity.organization.id,
            CustomRole.key == body.key,
        )
    )
    if exists is not None:
        raise _spoken(f"Роль с ключом «{body.key}» уже есть")

    made = CustomRole(
        organization_id=identity.organization.id,
        key=body.key,
        title=body.title.strip(),
        description=body.description.strip()[:2000],
        permissions=_clean(body.permissions),
        created_by_id=identity.user.id,
    )
    db.add(made)
    db.commit()
    logger.info("role.created", key=made.key, by=str(identity.user.id))
    return RoleOut(
        key=made.key,
        title=made.title,
        about=made.description,
        permissions=sorted(made.permissions),
        built_in=False,
        people=0,
    )


@router.patch("/roles/{key}", summary="Поправить роль")
def patch_role(
    key: str, body: RolePatch, identity: CurrentUser, db: Db, _guard: OnlyAdmin = None
) -> RoleOut:
    """Меняет название, пояснение и права своей роли.

    Права встроенных не правятся: на них держатся проверки по всей платформе, и
    «убрал деньги у тендерщика» означало бы, что половина экранов опустела у
    всех сразу. Нужна другая — заводится рядом.
    """
    role = _own(db, identity.organization.id, key)
    if body.title is not None:
        role.title = body.title.strip()[:120] or role.title
    if body.description is not None:
        role.description = body.description.strip()[:2000]
    if body.permissions is not None:
        role.permissions = _clean(body.permissions)
    db.commit()
    logger.info("role.updated", key=role.key, by=str(identity.user.id))
    return RoleOut(
        key=role.key,
        title=role.title,
        about=role.description,
        permissions=sorted(role.permissions),
        built_in=False,
        people=_counts(db, identity.organization.id).get(role.key, 0),
    )


@router.delete("/roles/{key}", summary="Убрать роль", status_code=204)
def delete_role(
    key: str,
    identity: CurrentUser,
    db: Db,
    force: Annotated[bool, Query(description="Убрать вместе с ролью у тех, кто её носит")] = False,
    _guard: OnlyAdmin = None,
) -> None:
    """Убирает свою роль.

    Занятую — только по прямой просьбе (`force`). Дело в том, что люди на ней
    остаются в платформе: роль снимается, и они получают права наблюдателя.
    Человек приходит утром, не находит своих разделов и идёт выяснять, что
    сломалось, — поэтому по умолчанию мы отказываем и называем число, а
    администратор решает: перевести их самому или снять роль вместе со всеми.

    Наблюдателя, а не «без прав»: место в организации остаётся, и войти человек
    может — он просто ничего не увидит, кроме отчётов. Выкинуть его из
    организации заодно с ролью было бы решением, которого никто не просил.

    Новые права действуют с их следующего входа: считаются они при разборе
    сессии. Тем, кто уже внутри, роль доработает до конца дня — снимать людей с
    работы посреди дня из-за правки роли хуже, чем показать им лишний раздел
    ещё несколько часов.
    """
    role = _own(db, identity.organization.id, key)
    занято = _counts(db, identity.organization.id).get(key, 0)
    if занято and not force:
        raise _spoken(
            f"Роль носят {занято} чел. Переведите их на другую роль — "
            "или уберите роль вместе с ней, тогда они станут наблюдателями"
        )
    if занято:
        for membership in db.scalars(
            select(Membership).where(Membership.custom_role_id == role.id)
        ):
            membership.custom_role_id = None
            membership.role = Role.VIEWER
    db.delete(role)
    db.commit()
    logger.warning("role.dropped", key=key, people=занято, by=str(identity.user.id))


@router.get("", summary="Сотрудники")
def get_people(identity: CurrentUser, db: Db, _guard: OnlyAdmin = None) -> list[PersonOut]:
    """Все, кто заведён в организации, вместе с ролями."""
    rows = db.execute(
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.organization_id == identity.organization.id)
        .order_by(User.full_name, User.email)
    ).all()
    return [_person(user, membership) for user, membership in rows]


@router.post("", summary="Завести сотрудника", status_code=201)
def post_person(
    body: PersonIn, identity: CurrentUser, db: Db, _guard: OnlyAdmin = None
) -> PersonOut:
    """Заводит человека и выдаёт ему роль.

    Пароль проверяется той же проверкой, что и при смене: слабый пароль,
    выданный администратором, — это тот же слабый пароль, только виноватым
    будет он.
    """
    try:
        passwords.validate_password(body.password)
    except passwords.WeakPasswordError as exc:
        raise _spoken(str(exc)) from exc

    email = str(body.email).strip().lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise _spoken("Сотрудник с такой почтой уже заведён")

    role, own = _pick(db, identity.organization.id, body.role)
    user = User(
        email=email,
        full_name=body.full_name.strip()[:255],
        password_hash=passwords.hash_password(body.password),
    )
    db.add(user)
    db.flush()
    membership = Membership(
        user_id=user.id,
        organization_id=identity.organization.id,
        role=role,
        custom_role_id=own.id if own is not None else None,
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)
    logger.info("person.created", email=email, role=body.role, by=str(identity.user.id))
    _tell_notify(identity, user, body.role)
    return _person(user, membership)


@router.patch("/{user_id}", summary="Поправить сотрудника")
def patch_person(
    user_id: uuid.UUID,
    body: PersonPatch,
    identity: CurrentUser,
    db: Db,
    _guard: OnlyAdmin = None,
) -> PersonOut:
    """Меняет имя, роль, пароль или выключает вход.

    Себя выключить нельзя и роль себе понизить нельзя: администратор,
    оставшийся без прав, не может их себе вернуть — а другого в маленькой
    компании может не быть вовсе.
    """
    user, membership = _found(db, identity.organization.id, user_id)
    свой = user.id == identity.user.id

    if body.full_name is not None:
        user.full_name = body.full_name.strip()[:255]
    if body.password is not None:
        try:
            passwords.validate_password(body.password)
        except passwords.WeakPasswordError as exc:
            raise _spoken(str(exc)) from exc
        user.password_hash = passwords.hash_password(body.password)
        # Пароль сменили — прежние входы гасим. Иначе тот, кто увёл пароль,
        # продолжает сидеть в платформе до конца срока сессии.
        _revoke(db, user.id)
    if body.role is not None:
        if свой:
            raise _spoken("Свою роль не меняют: администратор без прав их себе не вернёт")
        membership.role, own = _pick(db, identity.organization.id, body.role)
        membership.custom_role_id = own.id if own is not None else None
    if body.is_active is not None:
        if свой and not body.is_active:
            raise _spoken("Себя не выключают: войти обратно будет нечем")
        user.is_active = body.is_active
        if not body.is_active:
            _revoke(db, user.id)
    # Запертый вход снимается вместе с любой правкой: администратор открыл
    # человека — значит, разбирался, и держать замок после этого незачем.
    user.failed_logins = 0
    user.locked_until = None

    db.commit()
    db.refresh(membership)
    logger.info("person.updated", user=str(user_id), by=str(identity.user.id))
    return _person(user, membership)


@router.delete("/{user_id}", summary="Выключить или удалить сотрудника", status_code=204)
def delete_person(
    user_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    purge: Annotated[bool, Query(description="Удалить запись, а не выключить вход")] = False,
    _guard: OnlyAdmin = None,
) -> None:
    """Выключает вход или удаляет запись целиком.

    **Выключение** — обычный случай: человек ушёл, доступ закрыт, а всё, что он
    делал, осталось при нём и читается по имени.

    **Удаление** — когда записи быть не должно вовсе: завели по ошибке, ушёл
    подрядчик, попросили убрать персональные данные. Работа при этом остаётся:
    подписи, задачи и лента событий держат имя копией рядом со ссылкой, и
    ссылка обнуляется, а имя — нет. Так «кто это одобрил» отвечается и через
    полгода после удаления.

    Уносит удаление только его собственное: сессии, коды восстановления пароля
    и место в организации. Лоты, которые он вёл, становятся ничьими — их видно
    в списке как «ничьё», и это правда: вести их больше некому.
    """
    user, _ = _found(db, identity.organization.id, user_id)
    if user.id == identity.user.id:
        raise _spoken(
            "Себя не удаляют: войти обратно будет нечем"
            if purge
            else "Себя не выключают: войти обратно будет нечем"
        )

    if not purge:
        user.is_active = False
        _revoke(db, user.id)
        db.commit()
        logger.info("person.disabled", user=str(user_id), by=str(identity.user.id))
        return

    # Последнего администратора не удаляем. Платформа без него остаётся без
    # управления доступами, и вернуть их можно только руками в базе.
    if _last_admin(db, identity.organization.id, user_id):
        raise _spoken(
            "Это последний администратор. Выдайте права другому сотруднику, потом удаляйте"
        )

    email = user.email
    db.delete(user)
    db.commit()
    logger.warning("person.purged", email=email, by=str(identity.user.id))


def _last_admin(db: Db, organization_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Единственный ли он администратор в организации.

    Считается по правам, а не по имени роли: администратором делает право
    `admin`, и своя роль с ним — тоже администратор.
    """
    others = 0
    rows = db.scalars(
        select(Membership).where(
            Membership.organization_id == organization_id,
            Membership.user_id != user_id,
        )
    )
    for membership in rows:
        own = membership.custom_role
        права = (
            set(own.permissions)
            if own is not None
            else {item.value for item in BUILT_IN[membership.role]}
        )
        if Permission.ADMIN.value in права and membership.user.is_active:
            others += 1
    return others == 0


def _person(user: User, membership: Membership) -> PersonOut:
    own = membership.custom_role
    return PersonOut(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=own.key if own is not None else membership.role.value,
        role_title=own.title if own is not None else ROLE_NAMES[membership.role],
        is_active=user.is_active,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else "",
        locked=user.is_locked,
    )


def _pick(db: Db, organization_id: uuid.UUID, key: str) -> tuple[Role, CustomRole | None]:
    """Роль по ключу: встроенная или своя.

    У своей встроенная часть — наблюдатель: колонка обязательная, а произвольный
    набор прав в неё не уложить. Наблюдатель выбран как самое безопасное
    значение — место, которое ещё смотрит на встроенную роль, даст меньше
    доступа, а не больше.
    """
    try:
        return Role(key), None
    except ValueError:
        pass
    own = db.scalar(
        select(CustomRole).where(
            CustomRole.organization_id == organization_id, CustomRole.key == key
        )
    )
    if own is None:
        raise _spoken(f"Роли «{key}» нет")
    return Role.VIEWER, own


def _own(db: Db, organization_id: uuid.UUID, key: str) -> CustomRole:
    role = db.scalar(
        select(CustomRole).where(
            CustomRole.organization_id == organization_id, CustomRole.key == key
        )
    )
    if role is None:
        if key in {item.value for item in Role}:
            raise _spoken("Встроенную роль править нельзя — заведите свою рядом")
        raise _spoken(f"Роли «{key}» нет")
    return role


def _found(db: Db, organization_id: uuid.UUID, user_id: uuid.UUID) -> tuple[User, Membership]:
    row = db.execute(
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(User.id == user_id, Membership.organization_id == organization_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сотрудник не найден")
    return row[0], row[1]


def _counts(db: Db, organization_id: uuid.UUID) -> dict[str, int]:
    """Сколько человек носит каждую роль — одним запросом.

    Считается и по встроенным, и по своим: у первых ключ лежит в
    `memberships.role`, у вторых — в связанной роли.
    """
    out: dict[str, int] = {}
    rows = db.execute(
        select(Membership.role, func.count())
        .where(
            Membership.organization_id == organization_id,
            Membership.custom_role_id.is_(None),
        )
        .group_by(Membership.role)
    ).all()
    for role, count in rows:
        out[role.value] = int(count)

    own = db.execute(
        select(CustomRole.key, func.count())
        .join(Membership, Membership.custom_role_id == CustomRole.id)
        .where(CustomRole.organization_id == organization_id)
        .group_by(CustomRole.key)
    ).all()
    for key, count in own:
        out[key] = int(count)
    return out


def _clean(items: list[str]) -> list[str]:
    """Оставляет только известные права.

    Молча: список прав закрыт кодом, и незнакомое значение — это либо опечатка
    в запросе, либо право, которое убрали вместе с местом, которое его
    проверяло. Ни то ни другое не повод отказывать в сохранении роли целиком.
    """
    known = {item.value for item in Permission}
    return sorted({item for item in items if item in known})


def _revoke(db: Db, user_id: uuid.UUID) -> None:
    """Гасит входы человека: смена пароля и выключение должны действовать
    сразу, а не к концу срока сессии."""
    from platform_api.db.base import utcnow

    for session in db.scalars(
        select(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None))
    ):
        session.revoked_at = utcnow()


def _tell_notify(identity: CurrentUser, user: User, role: str) -> None:
    """Заводит человека в сервисе уведомлений сразу, а не при следующем
    запуске платформы: иначе бот на его почту отвечает «если такая заведена,
    код отправлен» и не отправляет ничего."""
    from platform_api.config import get_settings
    from platform_api.modules import notify

    settings = get_settings()
    if not settings.notify.ready:
        return
    notify.enroll(
        settings,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=role,
        is_active=user.is_active,
    )


def _spoken(text: str) -> HTTPException:
    """Отказ словами.

    Готовым ответом, а не `SpokenError`: тот ловится обёрткой служб, а здесь
    роутер — бросать через него значит полагаться на чужой обработчик там, где
    его нет.
    """
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=text)
