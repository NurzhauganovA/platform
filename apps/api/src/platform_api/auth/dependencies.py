"""Зависимости доступа.

Права проверяются здесь — на эндпоинте, а не в интерфейсе. Скрытая кнопка при
открытом эндпоинте выглядит как защита ровно до первого человека, который
откроет адрес руками; в нашем случае за таким адресом лежит себестоимость.

Роли сравниваются по набору, а не по старшинству. Иерархия «админ выше
аналитика выше закупщика» подталкивает написать «не ниже закупщика» — и
закупщик получает доступ к марже, которую ему видеть не полагается.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DbSession

from platform_api.auth.service import Identity, resolve_session
from platform_api.config import Settings, get_settings
from platform_api.db.models import Role


def get_db(request: Request) -> Iterator[DbSession]:
    """Сессия базы на время запроса.

    Фиксация по выходу, откат при ошибке: обработчику не нужно помнить про
    `commit`, а наполовину применённое изменение не доживает до ответа.
    """
    factory = request.app.state.session_factory
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


Db = Annotated[DbSession, Depends(get_db)]


def get_current_identity(
    request: Request,
    db: Db,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Identity:
    """Кто пришёл. Без годной сессии — 401."""
    token = request.cookies.get(settings.auth.session_cookie, "")
    identity = resolve_session(db, token)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется вход",
        )
    return identity


CurrentUser = Annotated[Identity, Depends(get_current_identity)]


def require_roles(*roles: Role) -> Callable[[Identity], Identity]:
    """Пускает только перечисленные роли.

    Администратор проходит везде — он и так управляет доступами, и запирать
    его от раздела значит заставить выдать себе роль, чтобы посмотреть.
    """
    allowed = {Role.ADMIN, *roles}

    def guard(identity: CurrentUser) -> Identity:
        if identity.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для этого раздела",
            )
        return identity

    return guard


# Готовые проверки под задачи, а не под роли. Читается на эндпоинте как
# требование к делу: «сюда пускаем тех, кому положено видеть деньги».
requires_admin = Depends(require_roles())

# Наборы ролей объявлены здесь и отсюда же берутся пунктами меню
# (`NavItem.roles` через `names`). Раздельные списки в модулях и в проверках
# разъезжаются молча: пункт остаётся видимым, а эндпоинт отвечает отказом — и
# человек перестаёт доверять меню. Или наоборот: доступ есть, а работы не
# найти.

# Кто принимает решение об участии: цифры нужны всем троим. Менеджер поставки
# ведёт лот и отвечает за него, руководитель и коммерческий директор решают,
# когда цифры спорные. Решать «берём или нет», не видя маржи, нельзя.
_DECIDES = (Role.MANAGER, Role.HEAD, Role.COMMERCIAL)

MONEY = (Role.ADMIN, Role.ANALYST, *_DECIDES)
"""Кому видно себестоимость, маржу и нашу отпускную цену.

Закупщика здесь нет намеренно: для его работы это не нужно, а уходит вместе с
ним. Технолога и сборщика тоже — они подтверждают товар и сроки, а не цену.
"""

READS = (Role.ADMIN, Role.ANALYST, Role.BUYER, Role.VIEWER, *_DECIDES)
"""Кому открыты рабочие списки, очередь задач и справочники.

Юриста, технолога и сборщика здесь нет намеренно. За списками цены, а их
работа идёт от карточки лота: юрист пишет замечания, технолог и сборщик
ставят подписи. Список закупок им не нужен, а показать его — значит показать
и цифры.
"""

SOURCING = (Role.ADMIN, Role.ANALYST, Role.BUYER, Role.MANAGER)
"""Задание закупщику: поставщики, целевая цена закупа, статусы."""

REMARKS = (Role.ADMIN, Role.ANALYST, Role.LAWYER)
"""Замечания к спецификациям и жалобы.

Юрист есть здесь и нет в `READS`: за рабочими списками цены, а ему для
обращения к заказчику нужны требования спецификации, а не наша себестоимость.
Закупщика нет наоборот — замечание к документации не его работа, и подпись под
обращением от имени компании тоже.
"""

CRM = tuple(role for role in Role if role is not Role.VIEWER)
"""Кому открыта карточка лота.

Всем, кто с лотами работает: у каждого отдела в ней своё. Наблюдателя нет — он
смотрит отчёты, а карточка это стол с задачами и подписями.
"""


def names(*roles: Role) -> tuple[str, ...]:
    """Имена ролей для `NavItem.roles`.

    Пункт меню принимает строки, а проверки — перечисление. Переписывать один
    и тот же набор в двух видах значит однажды поправить только один.
    """
    return tuple(role.value for role in roles)


requires_money = Depends(require_roles(*MONEY))
requires_sourcing = Depends(require_roles(*SOURCING))
requires_read = Depends(require_roles(*READS))
requires_remarks = Depends(require_roles(*REMARKS))


__all__ = [
    "CRM",
    "MONEY",
    "READS",
    "REMARKS",
    "SOURCING",
    "CurrentUser",
    "Db",
    "get_current_identity",
    "get_db",
    "names",
    "require_roles",
    "requires_admin",
    "requires_money",
    "requires_read",
    "requires_remarks",
    "requires_sourcing",
]
