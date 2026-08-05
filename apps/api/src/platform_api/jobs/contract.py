"""Что такое фоновая задача с точки зрения модуля.

Модуль объявляет задачи, а не запускает их сам. Каркас берёт на себя всё, что
одинаково для любого проекта: учёт состояния, прогресс, ошибки, стоимость,
отмену. Модулю остаётся предметная работа — разобрать документы, поискать на
рынке, собрать КП.

Обработчик синхронный намеренно. Ядра проектов синхронные: они читают PDF,
гоняют OCR и ходят в модель блокирующими вызовами. Просить их притвориться
асинхронными значит развести два способа делать одно и то же и однажды позвать
блокирующий код из цикла событий — там он остановит весь сервер.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.orm import Session as DbSession

from platform_api.storage import FileStorage


class CancelledError(Exception):
    """Задачу отменили — работу нужно прекратить.

    Отмена не ошибка: человек передумал, и разбор, за который иначе пришлось
    бы заплатить до конца, останавливается.
    """


class JobContext(Protocol):
    """Что обработчик получает от каркаса."""

    job_id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID | None

    db: DbSession
    storage: FileStorage
    workspace: Any
    """Каталоги закупок. Тип не уточняется намеренно: устройство рабочего
    каталога — дело модуля, а каркас только передаёт его обработчику."""

    def advance(self, done: int, *, total: int | None = None, note: str = "") -> None:
        """Двигает прогресс и проверяет, не отменили ли задачу.

        Проверка именно здесь, а не отдельным вызовом: обработчик и так
        сообщает о каждом шаге, и лишний повод забыть про отмену ни к чему.
        Бросает `Cancelled`, если задачу погасили.
        """
        ...


@dataclass(frozen=True, slots=True)
class JobSpec:
    """Объявление одной задачи модуля."""

    kind: str
    """Имя задачи внутри модуля: `analyze`, `sourcing`, `offer`."""

    handler: Callable[..., dict[str, Any]]
    """Что выполнять. Первым аргументом получает контекст, остальное —
    параметры задачи как есть."""

    title: str = ""
    """Как задача называется для человека."""

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("У задачи должно быть имя")


__all__ = ["CancelledError", "JobContext", "JobSpec"]
