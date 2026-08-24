"""Таблицы каркаса платформы.

Здесь только общее: кто работает, в какой организации, с какими правами, что
загружено и какие задачи выполняются. Предметных таблиц — закупок, документов,
цен — тут нет и быть не должно: они живут в базах своих проектов.

Организация введена сразу, хотя пока она одна. Добавить её потом означает
пройтись по каждому запросу и каждому индексу в системе, где уже лежат чужие
коммерческие данные, и один пропущенный запрос показывает одному заказчику
закупки другого.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from platform_api.db.base import Base, Timestamps, UUIDPrimaryKey


class Role(StrEnum):
    """Кто что видит.

    Разделение уже существует в документах, которые проект выпускает: КП для
    заказчика собирается без себестоимости, задание закупщику — с ней. В вебе
    эта же граница проходит по правам, иначе она держится только на том, что
    человек не открыл соседнюю страницу.
    """

    ADMIN = "admin"
    """Настройки, ключи, реквизиты компаний, управление людьми."""

    ANALYST = "analyst"
    """Тендерщик: закупки, разбор, себестоимость, маржа, наши КП."""

    BUYER = "buyer"
    """Закупщик: задание, поставщики, целевая цена закупа и статусы.
    Нашей отпускной цены и маржи не видит — ему они для работы не нужны,
    а утечь могут вместе с ним."""

    VIEWER = "viewer"
    """Только чтение отчётов."""


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Organization(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class User(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")

    password_hash: Mapped[str] = mapped_column(Text)
    """Argon2id. Пароль в открытом виде не хранится и не логируется нигде."""

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)

    failed_logins: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(nullable=True)
    """Защита от подбора пароля. Без неё форма входа — открытый перебор по
    словарю, а за ней лежат коммерческие данные и ключи к платным моделям."""

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_locked(self) -> bool:
        from platform_api.db.base import utcnow

        return self.locked_until is not None and self.locked_until > utcnow()


class Membership(Base, UUIDPrimaryKey, Timestamps):
    """Человек в организации и его роль."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", name="user_organization"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=32))

    user: Mapped[User] = relationship(back_populates="memberships")
    organization: Mapped[Organization] = relationship(back_populates="memberships")


class Session(Base, UUIDPrimaryKey, Timestamps):
    """Вход, живущий в httpOnly-куке.

    В куке лежит только идентификатор — сама сессия здесь, и поэтому её можно
    отозвать. Токен, который нельзя погасить со стороны сервера, означает, что
    уволившийся сотрудник ходит в систему до истечения срока.
    """

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    """Хэш от значения из куки, а не само значение: утёкшая копия базы не
    должна давать вход."""

    expires_at: Mapped[datetime] = mapped_column(index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)

    user_agent: Mapped[str] = mapped_column(String(512), default="")
    ip_address: Mapped[str] = mapped_column(String(64), default="")

    user: Mapped[User] = relationship()

    @property
    def is_valid(self) -> bool:
        from platform_api.db.base import utcnow

        return self.revoked_at is None and self.expires_at > utcnow()


class StoredFile(Base, UUIDPrimaryKey, Timestamps):
    """Загруженный файл.

    Ключ — sha256 содержимого, как и в кэше разбора: один и тот же документ в
    трёх закупках хранится один раз. В тендерных папках дубликаты не
    исключение, а норма — там же встречается один образец МЗ, разложенный по
    пяти папкам заказчиков.
    """

    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("organization_id", "sha256", name="organization_sha256"),
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )

    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(String(255), default="")
    original_name: Mapped[str] = mapped_column(String(512), default="")

    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Job(Base, UUIDPrimaryKey, Timestamps):
    """Фоновая задача.

    Разбор идёт минутами и стоит денег, поэтому живёт в очереди, а не в
    обработчике запроса. Состояние хранится в базе, а не только в Redis:
    человек должен увидеть, чем закончился вчерашний прогон и сколько он
    стоил, даже если очередь с тех пор перезапускали.
    """

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_org_created", "organization_id", "created_at"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    module: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=32),
        default=JobStatus.QUEUED,
        server_default=JobStatus.QUEUED.value,
        index=True,
    )

    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    progress_done: Mapped[int] = mapped_column(default=0, server_default="0")
    progress_total: Mapped[int] = mapped_column(default=0, server_default="0")
    progress_note: Mapped[str] = mapped_column(String(512), default="")

    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    cost_usd: Mapped[float | None] = mapped_column(nullable=True)
    """Во сколько обошёлся прогон. Хранится вместе с задачей: вопрос «сколько
    мы потратили на разбор» задаётся всегда и обычно задним числом."""


class AuditEntry(Base, UUIDPrimaryKey):
    """Кто что сделал.

    Пишется по действиям, меняющим деньги и доступ: вход, выдача роли, запуск
    платного разбора, выпуск КП. Не для отчётности — для ответа на вопрос
    «кто отправил заказчику это предложение», который однажды будет задан.
    """

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_org_created", "organization_id", "created_at"),)

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str] = mapped_column(String(255), default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    ip_address: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(index=True)


class TenderLot(Base, UUIDPrimaryKey, Timestamps):
    """Закупка, которую ведут целиком, а не позициями по отдельности.

    Решение человека, а не свойство данных. В заключении заказчика позиций
    бывает три. По одной из них заработок выглядит отличным, её берут в
    работу — и там выясняется, что поставить придётся все три, а на остальных
    двух убыток. В сумме сделка убыточна, и увидеть это надо до подачи.

    Из данных лот не вывести. Позиции одного заключения иногда разыгрываются
    порознь, а бывает и наоборот: заказчик разложил один лот по двум папкам, и
    ни один признак в документах об этом не говорит.
    """

    __tablename__ = "tender_lots"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    positions: Mapped[list[TenderLotPosition]] = relationship(
        back_populates="lot", cascade="all, delete-orphan", lazy="selectin"
    )


class TenderLotPosition(Base, UUIDPrimaryKey, Timestamps):
    """Позиция в составе лота.

    Хранится папкой и названием, а не идентификатором строки: тот считается
    от них же и меняется с каждым новым разбором, и после перезапуска ядра
    лот распался бы на пустые ссылки.

    Одна позиция — не больше чем в одном лоте организации: два лота с общей
    позицией дают два разных итога по одной и той же поставке, и какой из них
    правда, потом не выяснить.
    """

    __tablename__ = "tender_lot_positions"
    __table_args__ = (
        UniqueConstraint("organization_id", "folder_path", "title", name="organization_position"),
    )

    lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tender_lots.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )

    folder_path: Mapped[str] = mapped_column(String(1024))
    """Папка закупки — та же, что в базе ядра, абсолютным путём."""

    title: Mapped[str] = mapped_column(String(512))
    """Название позиции, как его дало ядро."""

    lot: Mapped[TenderLot] = relationship(back_populates="positions")


__all__ = [
    "AuditEntry",
    "Job",
    "JobStatus",
    "Membership",
    "Organization",
    "Role",
    "Session",
    "StoredFile",
    "TenderLot",
    "TenderLotPosition",
    "User",
]
