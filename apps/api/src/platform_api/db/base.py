"""Основание для таблиц платформы.

Общие соглашения собраны здесь, а не повторяются в каждой модели: единый
именователь ограничений (без него Alembic не умеет их удалять), время в UTC
и первичный ключ-UUID.

UUID, а не автоинкремент. Идентификатор закупки и файла попадает в адресную
строку, в ссылку на скачивание КП и в лог; последовательный номер сообщает
постороннему, сколько у нас закупок и как быстро они прибавляются, и позволяет
перебрать чужие, подставляя соседние числа.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Единый именователь: иначе имена ограничений придумывает СУБД, и миграция,
# написанная на одной машине, не находит их на другой.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    """Время всегда в UTC и всегда с зоной.

    Наивное время в базе — источник ошибок ровно в тот момент, когда его
    сравнивают с чем-то осведомлённым: сессия «истекает» на три часа раньше
    или живёт лишние три часа.
    """
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: DateTime(timezone=True),
    }


class UUIDPrimaryKey:
    """Первичный ключ-UUID."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class Timestamps:
    """Когда запись создана и когда изменена в последний раз."""

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), default=utcnow, onupdate=utcnow, nullable=False
    )
