"""Выполнение задач.

Здесь всё, что одинаково для любого проекта: взять задачу из базы, отдать её
обработчику модуля, довести до конца и записать, чем кончилось. Модуль об этом
не знает — он получает контекст и делает свою работу.

Отдельного внимания требует отмена. Разбор идёт минутами и стоит денег, и
кнопка «отменить» должна останавливать его в течение шага, а не по завершении.
Проверка вшита в `advance`: обработчик сообщает о каждом разобранном файле, и
на этом же вызове узнаёт, что его погасили.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from platform_api.db.base import utcnow
from platform_api.db.models import Job, JobStatus
from platform_api.jobs.contract import CancelledError, JobSpec
from platform_api.jobs.service import JobService, stale_running_jobs
from platform_api.logging import get_logger
from platform_api.storage import FileStorage

logger = get_logger(__name__)

CANCEL_CHECK_EVERY = 1
"""Через сколько шагов проверять отмену. Каждый: шаг — это разобранный файл,
а он стоит денег."""


@dataclass
class RunContext:
    """Контекст, который получает обработчик задачи."""

    job_id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID | None
    db: DbSession
    storage: FileStorage
    workspace: Any
    service: JobService = field(repr=False)

    def advance(self, done: int, *, total: int | None = None, note: str = "") -> None:
        self.service.advance(self.job_id, done=done, total=total, note=note)
        if self._is_cancelled():
            raise CancelledError(f"Задача {self.job_id} отменена")

    def _is_cancelled(self) -> bool:
        """Смотрит состояние в базе, а не в памяти.

        Отменяет человек через другой процесс — веб-сервер, — и объект задачи
        в нашей сессии об этом не узнает без перечитывания.
        """
        job = self.db.get(Job, self.job_id)
        if job is None:
            return True
        self.db.refresh(job, ["status"])
        return job.status is JobStatus.CANCELLED


class JobRunner:
    """Выполняет задачу и записывает исход."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        redis: Any,
        storage: FileStorage,
        handlers: dict[tuple[str, str], JobSpec],
        workspace: Any = None,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis
        self._storage = storage
        self._handlers = handlers
        self._workspace = workspace

    def run(self, job_id: uuid.UUID) -> None:
        """Выполняет задачу целиком. Исключения наружу не выпускает.

        Упавшая задача — это состояние в базе, а не падение исполнителя:
        иначе один битый архив останавливает очередь для всех остальных.
        """
        session = self._session_factory()
        try:
            service = JobService(session, self._redis)
            job = session.get(Job, job_id)
            if job is None:
                logger.warning("Задачи нет в базе", job_id=str(job_id))
                return
            if job.status is not JobStatus.QUEUED:
                # Повторная доставка из очереди: задачу уже брали в работу.
                logger.info("Задача не в очереди — пропускаем", job_id=str(job_id))
                return

            spec = self._handlers.get((job.module, job.kind))
            if spec is None:
                service.fail(job_id, f"Обработчик {job.module}/{job.kind} не подключён")
                return

            context = RunContext(
                job_id=job.id,
                organization_id=job.organization_id,
                user_id=job.created_by_id,
                db=session,
                storage=self._storage,
                workspace=self._workspace,
                service=service,
            )

            service.start(job_id)
            try:
                result = spec.handler(context, **dict(job.params))
            except CancelledError:
                # Отметку ставит исполнитель, а не тот, кто нажал «отменить».
                # Нажатие — только просьба остановиться: пока обработчик её не
                # услышал, разбор идёт и деньги тратятся. Состояние «отменена»
                # должно означать, что работа действительно прекращена.
                service.cancel(job_id)
                logger.info("Задача отменена", job_id=str(job_id))
                return
            except Exception as exc:
                logger.exception("Задача упала", job_id=str(job_id))
                service.fail(job_id, f"{type(exc).__name__}: {exc}")
                return

            payload = dict(result or {})
            cost = payload.pop("cost_usd", None)
            service.finish(
                job_id,
                result=payload,
                cost_usd=float(cost) if cost is not None else None,
            )
        finally:
            session.close()


def recover_stale_jobs(
    session_factory: sessionmaker[DbSession], redis: Any, *, older_than_minutes: int = 60
) -> int:
    """Помечает задачи, застрявшие в «выполняется».

    Исполнителя могли убить посреди разбора — тогда задача висит в списке как
    живая, и человек ждёт результата, которого не будет. Честное «прервано»
    лучше бесконечного «идёт»: по нему видно, что прогон надо повторить.
    """
    session = session_factory()
    try:
        service = JobService(session, redis)
        stale = stale_running_jobs(session, utcnow() - timedelta(minutes=older_than_minutes))
        for job in stale:
            service.fail(job.id, "Разбор прерван: исполнитель остановлен")
        if stale:
            logger.warning("Подобраны прерванные задачи", count=len(stale))
        return len(stale)
    finally:
        session.close()


def collect_handlers(modules: Any) -> dict[tuple[str, str], JobSpec]:
    """Собирает обработчики всех модулей в один указатель.

    Ключ — пара «модуль и вид задачи». Одноимённые задачи в разных проектах
    (`analyze` есть и у тендеров, и у SKStore) не должны сталкиваться.
    """
    handlers: dict[tuple[str, str], JobSpec] = {}
    for module in modules.all():
        for spec in module.jobs:
            key = (module.slug, spec.kind)
            if key in handlers:
                raise ValueError(f"Задача {module.slug}/{spec.kind} объявлена дважды")
            handlers[key] = spec
    return handlers


__all__ = [
    "CANCEL_CHECK_EVERY",
    "JobRunner",
    "RunContext",
    "collect_handlers",
    "recover_stale_jobs",
]
