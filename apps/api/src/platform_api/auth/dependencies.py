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
requires_money = Depends(require_roles(Role.ANALYST))
"""Себестоимость, маржа, наша отпускная цена. Закупщику не видно намеренно:
для его работы это не нужно, а уходит вместе с ним."""

requires_sourcing = Depends(require_roles(Role.ANALYST, Role.BUYER))
"""Задание закупщику: поставщики, целевая цена закупа, статусы."""

requires_read = Depends(require_roles(Role.ANALYST, Role.BUYER, Role.VIEWER))


__all__ = [
    "CurrentUser",
    "Db",
    "get_current_identity",
    "get_db",
    "require_roles",
    "requires_admin",
    "requires_money",
    "requires_read",
    "requires_sourcing",
]
