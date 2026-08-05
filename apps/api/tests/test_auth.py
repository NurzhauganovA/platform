"""Вход, сессии и права.

Самая чувствительная часть платформы: за формой входа лежат коммерческие
данные тендерного отдела и ключи к платным моделям. Проверяется не только то,
что вход работает, но и то, что он не работает там, где не должен.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from platform_api.auth import passwords
from platform_api.auth.service import (
    MAX_FAILED_LOGINS,
    AuthError,
    authenticate,
    hash_token,
    open_session,
    resolve_session,
    revoke_all_sessions,
)
from platform_api.db.base import utcnow
from platform_api.db.models import Membership, Organization, Role, User
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

PASSWORD = "закупки-2026-каратау"


def _user(db: DbSession, email: str = "tender@fintend.kz", role: Role = Role.ANALYST) -> User:
    org = Organization(name="Fintend", slug=f"fintend-{uuid.uuid4().hex[:6]}")
    db.add(org)
    user = User(email=email, full_name="Тендерщик", password_hash=passwords.hash_password(PASSWORD))
    db.add(user)
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role=role))
    db.flush()
    return user


# --- пароли ---------------------------------------------------------------


def test_password_roundtrip() -> None:
    digest = passwords.hash_password(PASSWORD)

    assert digest != PASSWORD
    assert passwords.verify_password(PASSWORD, digest)
    assert not passwords.verify_password(PASSWORD + "!", digest)


def test_short_password_is_refused() -> None:
    """Восьмизначный пароль перебирается быстрее, чем замечают попытку."""
    with pytest.raises(passwords.WeakPasswordError, match="словарю"):
        passwords.hash_password("коротко1")


def test_broken_hash_is_a_mismatch_not_a_crash() -> None:
    """Битая запись в базе — состояние «не пускать», а не пятисотка на форме."""
    assert passwords.verify_password(PASSWORD, "не хэш вовсе") is False


def test_hash_is_not_reused_across_users() -> None:
    """Соль своя у каждого: одинаковые пароли не должны давать одинаковый хэш."""
    assert passwords.hash_password(PASSWORD) != passwords.hash_password(PASSWORD)


# --- вход -----------------------------------------------------------------


def test_login_returns_membership(db: DbSession) -> None:
    user = _user(db)

    found, organization, role = authenticate(db, user.email, PASSWORD)

    assert found.id == user.id
    assert role is Role.ANALYST
    assert organization.slug.startswith("fintend")


def test_unknown_email_and_wrong_password_look_the_same(db: DbSession) -> None:
    """Разные сообщения превращают форму входа в способ узнать, кто у нас работает."""
    user = _user(db)

    with pytest.raises(AuthError) as unknown:
        authenticate(db, "чужой@example.kz", PASSWORD)
    with pytest.raises(AuthError) as wrong:
        authenticate(db, user.email, "неверный пароль такой длины")

    assert str(unknown.value) == str(wrong.value)


def test_brute_force_locks_the_account(db: DbSession) -> None:
    """Форма входа без ограничения — открытый перебор по словарю."""
    user = _user(db)

    for _ in range(MAX_FAILED_LOGINS):
        with pytest.raises(AuthError):
            authenticate(db, user.email, "неверный пароль подлиннее")

    assert user.is_locked
    # Верный пароль тоже не пускает, пока держится замок.
    with pytest.raises(AuthError, match="попыток"):
        authenticate(db, user.email, PASSWORD)


def test_successful_login_clears_the_counter(db: DbSession) -> None:
    user = _user(db)
    with pytest.raises(AuthError):
        authenticate(db, user.email, "неверный пароль подлиннее")

    authenticate(db, user.email, PASSWORD)

    assert user.failed_logins == 0
    assert user.last_login_at is not None


def test_user_without_organization_cannot_enter(db: DbSession) -> None:
    """Учётная запись есть, работать не с чем — внутрь пускать нечего."""
    orphan = User(
        email="один@fintend.kz",
        password_hash=passwords.hash_password(PASSWORD),
    )
    db.add(orphan)
    db.flush()

    with pytest.raises(AuthError):
        authenticate(db, orphan.email, PASSWORD)


def test_disabled_user_cannot_enter(db: DbSession) -> None:
    user = _user(db)
    user.is_active = False
    db.flush()

    with pytest.raises(AuthError):
        authenticate(db, user.email, PASSWORD)


# --- сессии ---------------------------------------------------------------


def test_cookie_value_is_not_stored(db: DbSession) -> None:
    """В базе только хэш: утёкшая копия не должна давать вход."""
    user = _user(db)
    session, token = open_session(db, user, user.memberships[0].organization, ttl_hours=12)

    assert session.token_hash != token
    assert session.token_hash == hash_token(token)


def test_session_resolves_to_its_owner(db: DbSession) -> None:
    user = _user(db)
    _, token = open_session(db, user, user.memberships[0].organization, ttl_hours=12)

    identity = resolve_session(db, token)

    assert identity is not None
    assert identity.user.id == user.id
    assert identity.role is Role.ANALYST


def test_expired_session_is_refused(db: DbSession) -> None:
    from datetime import timedelta

    user = _user(db)
    session, token = open_session(db, user, user.memberships[0].organization, ttl_hours=12)
    session.expires_at = utcnow() - timedelta(minutes=1)
    db.flush()

    assert resolve_session(db, token) is None


def test_revoked_session_is_refused(db: DbSession) -> None:
    """Сессию нужно уметь погасить: иначе уволившийся ходит внутрь до срока."""
    user = _user(db)
    _, token = open_session(db, user, user.memberships[0].organization, ttl_hours=12)

    revoke_all_sessions(db, user.id)

    assert resolve_session(db, token) is None


def test_removing_from_organization_kills_the_session(db: DbSession) -> None:
    """Человека вывели из организации, пока он был внутри.

    Продолжать показывать ему закупки до истечения срока сессии нельзя.
    """
    user = _user(db)
    membership = user.memberships[0]
    _, token = open_session(db, user, membership.organization, ttl_hours=12)

    db.delete(membership)
    db.flush()

    assert resolve_session(db, token) is None


def test_garbage_token_is_refused(db: DbSession) -> None:
    assert resolve_session(db, "подобранное значение") is None
    assert resolve_session(db, "") is None


# --- через HTTP -----------------------------------------------------------


def test_login_sets_a_protected_cookie(app_client: TestClient, db: DbSession) -> None:
    """Три ограничения сразу, каждое закрывает свой способ угнать куку."""
    user = _user(db)
    db.commit()

    response = app_client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})

    assert response.status_code == 200
    assert response.json()["role"] == "analyst"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    # Само значение сессии в теле ответа не появляется.
    assert "token" not in response.text.lower()


def test_me_requires_a_session(app_client: TestClient) -> None:
    assert app_client.get("/api/auth/me").status_code == 401


def test_logout_kills_the_session(app_client: TestClient, db: DbSession) -> None:
    user = _user(db)
    db.commit()
    app_client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert app_client.get("/api/auth/me").status_code == 200

    app_client.post("/api/auth/logout")

    assert app_client.get("/api/auth/me").status_code == 401


def test_logout_without_session_is_not_an_error(app_client: TestClient) -> None:
    """Выйти — действие идемпотентное, отказывать не за что."""
    assert app_client.post("/api/auth/logout").status_code == 200


def test_failed_login_is_recorded(app_client: TestClient, db: DbSession) -> None:
    """Серию промахов нужно видеть в журнале — по ней замечают подбор."""
    from platform_api.db.models import AuditEntry

    app_client.post(
        "/api/auth/login", json={"email": "чужой@example.kz", "password": "какой-то пароль"}
    )

    entries = db.scalars(select(AuditEntry).where(AuditEntry.action == "login_failed")).all()
    assert entries


def test_brute_force_is_counted_over_http(app_client: TestClient, db: DbSession) -> None:
    """Счётчик попыток обязан пережить отказ.

    Отказ уходит исключением, а оно откатывает транзакцию запроса — вместе со
    счётчиком. Без явной фиксации защита от подбора работала бы только в
    юнит-тестах: через HTTP счётчик обнулялся на каждой попытке, и перебор шёл
    бесконечно.
    """
    user = _user(db)
    db.commit()

    for _ in range(MAX_FAILED_LOGINS):
        response = app_client.post(
            "/api/auth/login", json={"email": user.email, "password": "неверный пароль тут"}
        )
        assert response.status_code == 401

    db.refresh(user)
    assert user.failed_logins >= MAX_FAILED_LOGINS
    assert user.is_locked
    # Даже верный пароль теперь не пускает.
    blocked = app_client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert blocked.status_code == 401


def test_session_survives_across_requests(app_client: TestClient, db: DbSession) -> None:
    user = _user(db)
    db.commit()
    app_client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})

    for _ in range(3):
        assert app_client.get("/api/auth/me").status_code == 200


def test_app_exposes_auth_routes(app: FastAPI) -> None:
    paths = set(app.openapi()["paths"])

    assert {"/api/auth/login", "/api/auth/logout", "/api/auth/me"} <= paths
