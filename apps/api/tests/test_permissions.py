"""Права на эндпоинтах.

Граница между ролями здесь не абстрактная: она повторяет ту, что уже
существует в документах проекта. КП для заказчика собирается без
себестоимости, задание закупщику — с ней. В вебе то же самое должно держаться
на правах, а не на том, что человек не открыл соседний адрес.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from platform_api.auth import passwords
from platform_api.auth.dependencies import require_roles, requires_money, requires_sourcing
from platform_api.auth.service import open_session
from platform_api.config import Settings
from platform_api.db.models import Membership, Organization, Role, User
from sqlalchemy.orm import Session as DbSession

PASSWORD = "закупки-2026-каратау"


@pytest.fixture
def guarded_app(app: FastAPI) -> FastAPI:
    """Приложение с эндпоинтами под каждую из готовых проверок."""
    router = APIRouter(prefix="/api/probe")

    @router.get("/money", dependencies=[requires_money])
    def money() -> dict[str, str]:
        return {"маржа": "30.5%"}

    @router.get("/sourcing", dependencies=[requires_sourcing])
    def sourcing() -> dict[str, str]:
        return {"поставщик": "eco-service.kz"}

    @router.get("/admin", dependencies=[Depends(require_roles())])
    def admin() -> dict[str, str]:
        return {"ключ": "настройки"}

    app.include_router(router)
    return app


def _login(db: DbSession, client: TestClient, role: Role) -> User:
    org = Organization(name="Fintend", slug=f"fintend-{uuid.uuid4().hex[:6]}")
    user = User(
        email=f"{role.value}-{uuid.uuid4().hex[:6]}@fintend.kz",
        password_hash=passwords.hash_password(PASSWORD),
    )
    db.add_all([org, user])
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role=role))
    db.flush()

    _, token = open_session(db, user, org, ttl_hours=12)
    db.commit()
    client.cookies.set(Settings().auth.session_cookie, token)
    return user


@pytest.mark.parametrize(
    ("role", "money", "sourcing", "admin"),
    [
        (Role.ADMIN, 200, 200, 200),
        (Role.ANALYST, 200, 200, 403),
        (Role.BUYER, 403, 200, 403),
        (Role.VIEWER, 403, 403, 403),
    ],
)
def test_roles_see_only_their_own(
    guarded_app: FastAPI,
    db: DbSession,
    role: Role,
    money: int,
    sourcing: int,
    admin: int,
) -> None:
    """Закупщик не видит маржу, наблюдатель не видит поставщиков.

    Ключевая строка таблицы — вторая с конца: закупщик работает с целевой
    ценой закупа и поставщиками, но нашей отпускной цены и маржи не видит.
    Для его работы они не нужны, а уходят вместе с ним.
    """
    with TestClient(guarded_app) as client:
        _login(db, client, role)

        assert client.get("/api/probe/money").status_code == money
        assert client.get("/api/probe/sourcing").status_code == sourcing
        assert client.get("/api/probe/admin").status_code == admin


def test_without_session_everything_is_closed(guarded_app: FastAPI) -> None:
    """Незваный получает 401, а не 403: разница видна и в логах, и в интерфейсе."""
    with TestClient(guarded_app) as client:
        for path in ("/api/probe/money", "/api/probe/sourcing", "/api/probe/admin"):
            assert client.get(path).status_code == 401


def test_roles_are_matched_by_set_not_by_seniority(guarded_app: FastAPI, db: DbSession) -> None:
    """Иерархия ролей подтолкнула бы написать «не ниже закупщика».

    Тогда закупщик получил бы доступ к марже, которую ему видеть не
    полагается. Проверка идёт по набору, и этот тест закрепляет именно это.
    """
    with TestClient(guarded_app) as client:
        _login(db, client, Role.BUYER)

        assert client.get("/api/probe/sourcing").status_code == 200
        assert client.get("/api/probe/money").status_code == 403
