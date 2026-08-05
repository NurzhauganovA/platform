"""Закупка в платформе.

Тендерное ядро работает каталогом на диске — так же, как при запуске из
терминала. Платформе нужно нечто устойчивее временной папки: закупку открывают
через месяц, к ней возвращаются, по ней собирают КП.

Отсюда устройство. Закупка — запись в базе со своим каталогом, а файлы в этот
каталог попадают жёсткими ссылками на хранилище: содержимое лежит по sha256
один раз, а в каталоге закупки оно видно под своим именем и в своей подпапке.
Место при этом не тратится дважды, и ядро получает обычную папку, ничего не
зная ни о платформе, ни о хранилище.

Таблицы этого модуля живут в базе платформы, а не ядра. Ядро остаётся
самостоятельным проектом со своей базой разборов; здесь — только то, чего у
него нет и быть не должно: чья это закупка, кто её завёл и где её файлы.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from platform_api.db.base import Base, Timestamps, UUIDPrimaryKey


class CaseStatus(StrEnum):
    """Где закупка находится в работе."""

    DRAFT = "draft"
    """Файлы загружаются."""

    READY = "ready"
    """Файлы на месте, разбор не запускался."""

    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    """Разобрана: документы прочитаны, предложения сравнены."""

    ARCHIVED = "archived"


class TenderCaseRow(Base, UUIDPrimaryKey, Timestamps):
    """Одна закупка."""

    __tablename__ = "tender_cases"
    __table_args__ = (Index("ix_tender_cases_org_created", "organization_id", "created_at"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(String(512))
    """Как закупку называет человек. По умолчанию — имя выбранной папки:
    тендерщик узнаёт её именно так, а не по номеру."""

    customer: Mapped[str] = mapped_column(String(512), default="")
    subject: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, native_enum=False, length=32),
        default=CaseStatus.DRAFT,
        server_default=CaseStatus.DRAFT.value,
        index=True,
    )

    deadline: Mapped[datetime | None] = mapped_column(nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")

    files: Mapped[list[CaseFileRow]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="CaseFileRow.relative_path"
    )

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.files)


class CaseFileRow(Base, UUIDPrimaryKey, Timestamps):
    """Файл в закупке.

    Отдельно от самого файла в хранилище: содержимое ключуется по sha256 и
    общее, а место в закупке — своё. Один и тот же образец МЗ лежит в пяти
    папках заказчиков, но на диске он один.
    """

    __tablename__ = "tender_case_files"
    __table_args__ = (UniqueConstraint("case_id", "relative_path", name="case_relative_path"),)

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tender_cases.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="RESTRICT"), index=True
    )

    relative_path: Mapped[str] = mapped_column(String(1024))
    """Путь внутри закупки, включая подпапки.

    «обновленные кп/КП Примеро.pdf» — не украшение: по структуре каталога ядро
    определяет состав закупок, и если сложить всё в одну кучу, обновлённые
    предложения смешаются с прежними."""

    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)

    case: Mapped[TenderCaseRow] = relationship(back_populates="files")


__all__ = ["CaseFileRow", "CaseStatus", "TenderCaseRow"]
