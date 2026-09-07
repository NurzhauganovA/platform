"""Свой профиль: имя, почта, пароль и куда слать уведомления.

Меняет человек сам, а не администратор. Ждать администратора ради смены
фамилии после свадьбы или пароля после того, как его подсмотрели, — это день
ожидания в лучшем случае; а пароль, который неудобно сменить, не меняют вовсе.

Почта здесь не косметика. По ней входят, на неё приходит код привязки
Телеграма и код сброса пароля. Поэтому смена почты сразу уходит в сервис
уведомлений: человек ждёт, что письмо придёт на новую, а не через час.

Сброс пароля кодом, а не ссылкой. Ссылка в письме — это ссылка, которую можно
переслать, и она же не работает в Телеграме, где половина людей и получает
уведомления. Шесть цифр называют вслух и вводят руками.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from platform_api.auth.passwords import hash_password, validate_password, verify_password
from platform_api.auth.service import revoke_all_sessions
from platform_api.config import Settings
from platform_api.db.base import utcnow
from platform_api.db.models import PasswordReset, User
from platform_api.errors import SpokenError
from platform_api.logging import get_logger
from platform_api.modules import notify

logger = get_logger(__name__)

CODE_TTL = timedelta(minutes=15)
"""Сколько живёт код сброса. Столько же, сколько у сервиса уведомлений код
привязки: человек не должен помнить два разных срока."""

MAX_ATTEMPTS = 5
"""Сколько раз можно ошибиться. Шесть цифр — это миллион вариантов, и без
предела их перебирают за вечер."""

CODES_PER_HOUR = 3
"""Сколько кодов в час на человека. Без предела форма превращается в способ
завалить чужой почтовый ящик."""


@dataclass(frozen=True, slots=True)
class Sent:
    """Куда ушёл код. Пусто — никуда: ни Телеграма, ни известного адреса."""

    channel: str


def rename(db: DbSession, settings: Settings, *, user: User, full_name: str, email: str) -> User:
    """Меняет имя и почту.

    Почта проверяется на занятость: она же имя для входа, и вторая учётная
    запись с тем же адресом означала бы, что человек входит то в одну, то в
    другую и не понимает, куда делись его лоты.
    """
    clean_name = " ".join(full_name.split())
    clean_mail = email.strip().lower()
    if not clean_mail or "@" not in clean_mail:
        raise SpokenError("Почта нужна для входа и для писем — укажите рабочий адрес")

    if clean_mail != user.email:
        taken = db.execute(select(User.id).where(User.email == clean_mail)).first()
        if taken is not None:
            raise SpokenError("Этот адрес уже занят другой учётной записью")

    user.full_name = clean_name[:255]
    user.email = clean_mail[:320]
    db.flush()

    # Сразу, а не по расписанию: письмо должно прийти на новый адрес.
    notify.enroll(
        settings,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
    )
    return user


def change_password(db: DbSession, *, user: User, current: str, fresh: str) -> None:
    """Меняет пароль по старому.

    Старый спрашивается даже у вошедшего: чужой, севший за незапертый
    компьютер, иначе меняет пароль и запирает хозяина снаружи.

    Остальные сессии гасятся. Пароль меняют в том числе потому, что его
    подсмотрели, и оставить чужому открытую вкладку значит не сменить ничего.
    """
    if not verify_password(current, user.password_hash):
        raise SpokenError("Текущий пароль не подошёл")
    validate_password(fresh)
    if verify_password(fresh, user.password_hash):
        raise SpokenError("Новый пароль совпадает со старым")

    user.password_hash = hash_password(fresh)
    db.flush()
    revoke_all_sessions(db, user.id)
    logger.info("Пароль изменён", user=str(user.id))


def ask_reset(db: DbSession, settings: Settings, *, email: str) -> Sent:
    """Заводит код сброса и отдаёт его сервису уведомлений.

    Канал выбирает не платформа, а сервис: у человека может быть привязан
    Телеграм, может быть выключен, может стоять «не беспокоить». Знание об этом
    живёт там, и повторять его здесь значит однажды отправить код в чат,
    который вчера отвязали. Отметка `channel` — для разговора «код не пришёл»:
    по ней видно, куда его понесли.

    Неизвестный адрес отвечает так же, как известный. Разные ответы превратили
    бы форму в способ проверять, работает ли у нас такой-то человек, — а
    адреса сотрудников есть у каждого заказчика, которому мы писали.
    """
    clean = email.strip().lower()
    user = db.execute(select(User).where(User.email == clean)).scalar_one_or_none()
    if user is None or not user.is_active:
        return Sent(channel="")

    recent = (
        db.execute(
            select(PasswordReset).where(
                PasswordReset.user_id == user.id,
                PasswordReset.created_at > utcnow() - timedelta(hours=1),
            )
        )
        .scalars()
        .all()
    )
    if len(recent) >= CODES_PER_HOUR:
        raise SpokenError("Кодов запрошено слишком много. Попробуйте через час")

    code = f"{secrets.randbelow(1_000_000):06d}"
    where = notify.channels(settings, user_id=user.id) or {}
    linked = bool((where.get("telegram") or {}).get("linked"))
    channel = "telegram" if linked and where.get("telegram_enabled", True) else "email"

    db.add(
        PasswordReset(
            user_id=user.id,
            code_hash=hash_password(code),
            channel=channel,
            expires_at=utcnow() + CODE_TTL,
        )
    )
    db.flush()

    notify.about(
        settings,
        event="system.message",
        title="Код для смены пароля",
        body_text=(
            f"Код: {code}\n\n"
            "Он действует пятнадцать минут и нужен один раз. Если пароль "
            "меняли не вы — скажите администратору: кто-то знает вашу почту."
        ),
        payload={"text": f"Код: {code}"},
        users=[user.id],
    )
    logger.info("Код сброса отправлен", user=str(user.id), channel=channel)
    return Sent(channel=channel)


def finish_reset(db: DbSession, *, email: str, code: str, fresh: str) -> None:
    """Ставит новый пароль по коду.

    Код гасится после удачи, а не после первой попытки: человек ошибается в
    цифре, и сгоревший на опечатке код означал бы третий заход по кругу.
    Попытки при этом считаются — пять и всё.

    Все сессии гасятся: сброс пароля и есть тот случай, когда доступ мог
    достаться чужому.
    """
    clean = email.strip().lower()
    user = db.execute(select(User).where(User.email == clean)).scalar_one_or_none()
    if user is None:
        raise SpokenError("Код не подошёл")

    row = db.execute(
        select(PasswordReset)
        .where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
        .order_by(PasswordReset.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None or row.expires_at <= utcnow():
        raise SpokenError("Код устарел. Запросите новый")
    if row.attempts >= MAX_ATTEMPTS:
        raise SpokenError("Слишком много попыток. Запросите новый код")

    row.attempts += 1
    db.flush()
    if not verify_password(code.strip(), row.code_hash):
        raise SpokenError("Код не подошёл")

    validate_password(fresh)
    user.password_hash = hash_password(fresh)
    row.used_at = utcnow()
    db.flush()
    revoke_all_sessions(db, user.id)
    logger.info("Пароль сброшен по коду", user=str(user.id))


__all__ = [
    "CODES_PER_HOUR",
    "CODE_TTL",
    "MAX_ATTEMPTS",
    "Sent",
    "ask_reset",
    "change_password",
    "finish_reset",
    "rename",
]
