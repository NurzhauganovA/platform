"""Вход, сессии и защита от подбора.

Устройство сессии: в куке — случайное значение, в базе — только его sha256.
Утёкшая копия базы не даёт войти, а сессию можно погасить со стороны сервера.
Токен, который нельзя отозвать, означает, что уволившийся сотрудник ходит в
систему до истечения срока.

Хэш здесь без соли и намеренно: значение куки — это 32 случайных байта, а не
пароль. Словарь по ним не строится, замедлять проверку незачем, а быстрая
сверка нужна на каждом запросе.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from platform_api.auth import passwords
from platform_api.db.base import utcnow
from platform_api.db.models import Membership, Organization, Role, Session, User
from platform_api.logging import get_logger

logger = get_logger(__name__)

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15
"""После пяти промахов вход запирается на четверть часа.

Не «на всякий случай»: форма входа без такого ограничения — это открытый
перебор по словарю, а за ней лежат коммерческие данные и платные ключи."""


class AuthError(Exception):
    """Войти нельзя. Причина человеку не раскрывается."""


@dataclass(frozen=True, slots=True)
class Identity:
    """Кто пришёл с запросом."""

    user: User
    organization: Organization
    role: Role
    session_id: uuid.UUID

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(
    db: DbSession,
    email: str,
    password: str,
    *,
    organization_slug: str | None = None,
) -> tuple[User, Organization, Role]:
    """Проверяет пару «почта — пароль».

    Все отказы выглядят одинаково. Разные сообщения («нет такого пользователя»
    против «неверный пароль») превращают форму входа в способ узнать, кто у нас
    работает, — а по адресам сотрудников строится фишинг.
    """
    normalized = email.strip().lower()
    user = db.scalars(select(User).where(User.email == normalized)).one_or_none()

    if user is None:
        # Считаем хэш и здесь: без этого ответ на несуществующий адрес
        # приходит заметно быстрее, и по времени ответа перебирают адреса.
        passwords.verify_password(password, _DUMMY_HASH)
        raise AuthError("Неверная почта или пароль")

    if user.is_locked:
        raise AuthError("Слишком много неудачных попыток. Повторите через несколько минут")

    if not user.is_active:
        raise AuthError("Неверная почта или пароль")

    if not passwords.verify_password(password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.locked_until = utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
            logger.warning("Вход заперт после серии промахов", user_id=str(user.id))
        db.flush()
        raise AuthError("Неверная почта или пароль")

    # Параметры хэширования со временем ужесточаются: пересчитываем молча,
    # пока пароль у нас в руках — другого случая не будет.
    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = utcnow()

    membership = _pick_membership(db, user, organization_slug)
    db.flush()
    return user, membership.organization, membership.role


def _pick_membership(db: DbSession, user: User, organization_slug: str | None) -> Membership:
    query = (
        select(Membership)
        .join(Organization)
        .where(Membership.user_id == user.id, Organization.is_active.is_(True))
    )
    if organization_slug:
        query = query.where(Organization.slug == organization_slug)

    membership = db.scalars(query.order_by(Membership.created_at)).first()
    if membership is None:
        # Учётная запись есть, но ни в одной организации не состоит — работать
        # ей не с чем, и пускать внутрь нечего.
        raise AuthError("Неверная почта или пароль")
    return membership


def open_session(
    db: DbSession,
    user: User,
    organization: Organization,
    *,
    ttl_hours: int,
    user_agent: str = "",
    ip_address: str = "",
) -> tuple[Session, str]:
    """Заводит сессию и возвращает её вместе со значением для куки.

    Значение возвращается ровно один раз: в базе остаётся только хэш, и узнать
    его обратно нельзя ни нам, ни тому, кто получит доступ к дампу.
    """
    token = secrets.token_urlsafe(32)
    session = Session(
        user_id=user.id,
        organization_id=organization.id,
        token_hash=hash_token(token),
        expires_at=utcnow() + timedelta(hours=ttl_hours),
        user_agent=user_agent[:512],
        ip_address=ip_address[:64],
    )
    db.add(session)
    db.flush()
    return session, token


def resolve_session(db: DbSession, token: str) -> Identity | None:
    """Кто стоит за значением куки. `None`, если сессия негодная."""
    if not token:
        return None

    session = db.scalars(
        select(Session).where(Session.token_hash == hash_token(token))
    ).one_or_none()
    if session is None or not session.is_valid:
        return None

    membership = db.scalars(
        select(Membership).where(
            Membership.user_id == session.user_id,
            Membership.organization_id == session.organization_id,
        )
    ).one_or_none()
    if membership is None:
        # Человека вывели из организации, пока он был внутри. Сессию гасим:
        # иначе он продолжит видеть её закупки до истечения срока.
        revoke_session(db, session)
        return None

    user = membership.user
    if not user.is_active or not membership.organization.is_active:
        revoke_session(db, session)
        return None

    return Identity(
        user=user,
        organization=membership.organization,
        role=membership.role,
        session_id=session.id,
    )


def revoke_session(db: DbSession, session: Session) -> None:
    session.revoked_at = utcnow()
    db.flush()


def revoke_all_sessions(db: DbSession, user_id: uuid.UUID) -> int:
    """Гасит все сессии человека — при смене пароля и при увольнении."""
    sessions = db.scalars(
        select(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None))
    ).all()
    now = utcnow()
    for session in sessions:
        session.revoked_at = now
    db.flush()
    return len(sessions)


# Хэш заведомо недостижимого пароля: нужен, чтобы ответ на несуществующий
# адрес занимал столько же времени, сколько на существующий.
_DUMMY_HASH = passwords.hash_password(secrets.token_urlsafe(32))


__all__ = [
    "AuthError",
    "Identity",
    "authenticate",
    "hash_token",
    "open_session",
    "resolve_session",
    "revoke_all_sessions",
    "revoke_session",
]
