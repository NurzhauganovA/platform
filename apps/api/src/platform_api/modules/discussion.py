"""Обсуждение строки рабочего списка.

Идёт до разбора и вместо переписки. Решение «берём или нет» редко принимает
один человек: тендерщик видит цену, снабженец знает, что этого поставщика
ждали три месяца, а руководитель помнит, чем кончилась прошлая закупка у
этого заказчика. Пока это живёт в мессенджере, через неделю никто не
вспомнит, почему прошли мимо.

Общее для всех разделов. Ключ — раздел плюс устойчивое имя строки, тот же,
что у её кода: заводить своё обсуждение в каждом модуле значило бы четыре
одинаковых таблицы и четыре набора правил о том, кто что может править.

Правит только автор. Убирает автор или администратор — но не любой коллега:
чужая реплика, исчезнувшая из общей ветки, это спор о том, кто что сказал, и
ради него обсуждение и заводили.

Упоминание зовёт человека, а не красит слово. Реплика «@Айша, посмотри пункт
4.2» без уведомления — это надежда, что Айша зайдёт сама; а заходят в ветку
тогда, когда о ней напомнили. Поэтому позванные приходят списком
идентификаторов, а не выискиваются в тексте: имя в тексте — это буквы, и
однофамильцы, смена фамилии и опечатка превращают «кому ушло» в вопрос без
ответа. `all` зовёт всех действующих сотрудников организации.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from platform_api.config import Settings
from platform_api.db.base import utcnow
from platform_api.db.models import DiscussionMessage, Membership, Role, User
from platform_api.errors import SpokenError
from platform_api.modules import alerts

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session as DbSession

MAX_LENGTH = 4000
"""Предел длины сообщения. Не про базу, а про жанр: обсуждение — это реплики,
а не докладные. Длинное всё равно никто не дочитает до конца ветки."""

EVERYONE = "all"
"""Кого зовёт «@all». Словом, а не списком людей: позвали всех, а не тех
тринадцать, кто работал в организации в тот вторник."""


@dataclass(frozen=True, slots=True)
class Message:
    """Реплика в том виде, в каком её показывают."""

    id: str
    body: str
    author: str
    author_id: str
    created_at: str
    edited_at: str
    mentions: list[str]
    """Кого позвали: идентификаторы сотрудников и `all`."""


@dataclass(frozen=True, slots=True)
class Summary:
    """Сколько реплик у строки и о чём последняя.

    Нужна списку: без неё человек открывает каждую строку, чтобы проверить,
    не написал ли кто-нибудь. Первая же проверка вхолостую отучает смотреть
    вовсе.
    """

    count: int
    last: str


def messages(db: DbSession, organization_id: uuid.UUID, module: str, row_id: str) -> list[Message]:
    """Ветка по строке, снизу свежие: читают её сверху вниз, как разговор."""
    rows = db.execute(
        select(DiscussionMessage, User)
        .outerjoin(User, User.id == DiscussionMessage.author_id)
        .where(
            DiscussionMessage.organization_id == organization_id,
            DiscussionMessage.module == module,
            DiscussionMessage.row_id == row_id,
        )
        .order_by(DiscussionMessage.created_at)
    ).all()
    return [_out(message, user) for message, user in rows]


def summaries(
    db: DbSession, organization_id: uuid.UUID, module: str, rows: Sequence[str]
) -> dict[str, Summary]:
    """Счётчики по многим строкам разом.

    Одним запросом на весь список, а не по строке: строк восемьсот, и
    обращение на каждую было бы восемьюстами запросов ради нескольких десятков
    обсуждений.
    """
    if not rows:
        return {}

    counted = db.execute(
        select(DiscussionMessage.row_id, func.count())
        .where(
            DiscussionMessage.organization_id == organization_id,
            DiscussionMessage.module == module,
            DiscussionMessage.row_id.in_(list(rows)),
        )
        .group_by(DiscussionMessage.row_id)
    ).all()
    if not counted:
        return {}

    # Текст последней реплики — вторым запросом и только по тем строкам, где
    # обсуждение есть. Их десятки на восемьсот строк, и тянуть тексты всех
    # сообщений ради подсказки было бы дороже самой таблицы.
    latest: dict[str, str] = dict(
        db.execute(  # type: ignore[arg-type]
            select(DiscussionMessage.row_id, DiscussionMessage.body)
            .where(
                DiscussionMessage.organization_id == organization_id,
                DiscussionMessage.module == module,
                DiscussionMessage.row_id.in_([row_id for row_id, _ in counted]),
            )
            .order_by(DiscussionMessage.row_id, DiscussionMessage.created_at)
        ).all()
    )
    return {row_id: Summary(count=count, last=latest.get(row_id, "")) for row_id, count in counted}


def add(
    db: DbSession,
    organization_id: uuid.UUID,
    author_id: uuid.UUID | None,
    *,
    module: str,
    row_id: str,
    body: str,
    mentions: Sequence[str] = (),
    settings: Settings | None = None,
) -> Message:
    """Добавляет реплику и зовёт упомянутых.

    Зовёт отсюда, а не из обработчика: реплику пишет и человек, и прогон —
    например, когда модель дописала замечание, — и оповещение, оставленное в
    обработчике HTTP, второй путь молча пропускает.
    """
    text = _clean(body)
    called = _called(db, organization_id, mentions, author_id)
    message = DiscussionMessage(
        organization_id=organization_id,
        author_id=author_id,
        module=module,
        row_id=row_id,
        body=text,
        mentions=called,
    )
    db.add(message)
    db.flush()
    author = db.get(User, author_id) if author_id else None
    if settings is not None and called:
        alerts.mentioned(
            db,
            settings,
            organization_id=organization_id,
            module=module,
            row_id=row_id,
            author=author,
            text=text,
            mentions=called,
            message_id=message.id,
        )
    return _out(message, author)


def edit(
    db: DbSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID | None,
    message_id: uuid.UUID,
    body: str,
    mentions: Sequence[str] = (),
    settings: Settings | None = None,
) -> Message:
    """Правит свою реплику. Чужую — нельзя никому, включая администратора.

    Администратор может убрать чужое, но не переписать: убранное видно по
    отсутствию, переписанное не видно никак.

    Дописанное упоминание зовёт человека, уже позванных — не зовёт повторно.
    Позвать забывают ровно так же, как ошибаются в тексте, и правка через
    минуту после отправки — обычный ход; а второе уведомление по той же реплике
    читается как второе сообщение, которого никто не писал.
    """
    message = _own(db, organization_id, message_id)
    if message.author_id != user_id:
        raise SpokenError("Править можно только свои сообщения")
    text = _clean(body)
    called = _called(db, organization_id, mentions, message.author_id)
    fresh = [one for one in called if one not in set(message.mentions or ())]
    message.body = text
    message.mentions = called
    message.edited_at = utcnow()
    db.flush()
    author = db.get(User, message.author_id) if message.author_id else None
    if settings is not None and fresh:
        alerts.mentioned(
            db,
            settings,
            organization_id=organization_id,
            module=message.module,
            row_id=message.row_id,
            author=author,
            text=text,
            mentions=fresh,
            message_id=message.id,
        )
    return _out(message, author)


def remove(
    db: DbSession, organization_id: uuid.UUID, user: User, role: Role, message_id: uuid.UUID
) -> None:
    """Убирает реплику: свою — автор, любую — администратор."""
    message = _own(db, organization_id, message_id)
    if message.author_id != user.id and role is not Role.ADMIN:
        raise SpokenError("Убрать чужое сообщение может только администратор")
    db.delete(message)
    db.flush()


def _own(db: DbSession, organization_id: uuid.UUID, message_id: uuid.UUID) -> DiscussionMessage:
    """Сообщение своей организации. Чужой — как будто его нет."""
    message = db.execute(
        select(DiscussionMessage).where(
            DiscussionMessage.id == message_id,
            DiscussionMessage.organization_id == organization_id,
        )
    ).scalar_one_or_none()
    if message is None:
        raise SpokenError("Такого сообщения нет")
    return message


def _called(
    db: DbSession,
    organization_id: uuid.UUID,
    raw: Sequence[str],
    author_id: uuid.UUID | None,
) -> list[str]:
    """Оставляет из присланного тех, кого действительно можно позвать.

    Сверяется с составом организации, а не верит браузеру: подставленный
    идентификатор чужого сотрудника означал бы уведомление о нашей закупке
    человеку из другой компании.

    Себя из списка убираем. Позвать себя можно только по ошибке — @ поставили
    и выбрали первого в списке, — а уведомление о собственной реплике
    обесценивает все остальные.
    """
    wanted = {one.strip() for one in raw if one and one.strip()}
    if not wanted:
        return []

    called: list[str] = [EVERYONE] if EVERYONE in wanted else []
    wanted.discard(EVERYONE)

    ids: set[uuid.UUID] = set()
    for one in wanted:
        try:
            ids.add(uuid.UUID(one))
        except ValueError:
            # Мусор молча пропускаем: реплика важнее того, кого в ней не нашли.
            continue
    if author_id is not None:
        ids.discard(author_id)
    if not ids:
        return called

    members = set(
        db.scalars(
            select(User.id)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.organization_id == organization_id,
                User.id.in_(ids),
                User.is_active.is_(True),
            )
        )
    )
    called.extend(str(one) for one in sorted(members, key=str))
    return called


def _clean(body: str) -> str:
    text = body.strip()
    if not text:
        raise SpokenError("Пустое сообщение отправлять незачем")
    return text[:MAX_LENGTH]


def _out(message: DiscussionMessage, author: User | None) -> Message:
    return Message(
        id=str(message.id),
        body=message.body,
        author=_name(author),
        author_id=str(message.author_id) if message.author_id else "",
        created_at=message.created_at.isoformat(),
        edited_at=message.edited_at.isoformat() if message.edited_at else "",
        mentions=list(message.mentions or ()),
    )


def _name(author: User | None) -> str:
    """Как подписать реплику.

    Имя, а если его не заполнили — почта до собачки. Пустая подпись в ветке
    означает «кто-то написал», и спорить с этим не с кем.
    """
    if author is None:
        return "сотрудник"
    return author.full_name or author.email.split("@", 1)[0]


__all__ = [
    "EVERYONE",
    "MAX_LENGTH",
    "Message",
    "Summary",
    "add",
    "edit",
    "messages",
    "remove",
    "summaries",
]
