"""Фоновые задачи: учёт и прогресс.

Разбор идёт минутами и стоит денег, поэтому живёт в очереди, а не в
обработчике запроса. Состояние задачи пишется в базу, а не только в очередь:
человек должен увидеть, чем закончился вчерашний прогон и во сколько он
обошёлся, даже если очередь с тех пор перезапускали.

Прогресс идёт двумя путями и намеренно. В базу — редко, чтобы не устраивать
запись на каждый разобранный файл; в Redis — на каждый шаг, потому что оттуда
его читает открытая страница. Потеря промежуточного значения в Redis не
страшна: следующий шаг перекроет, а итог всё равно окажется в базе.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from platform_api.db.base import utcnow
from platform_api.db.models import Job, JobStatus
from platform_api.logging import get_logger

logger = get_logger(__name__)

PROGRESS_TTL_SECONDS = 3600
"""Сколько прогресс живёт в Redis после последнего обновления.

Час: столько же, сколько самый долгий прогон, и достаточно, чтобы страницу
успели открыть после его окончания. Дальше состояние берётся из базы."""

_DB_UPDATE_EVERY = 10
"""Раз во столько шагов прогресс попадает ещё и в базу.

Запись на каждый файл превратила бы разбор двух тысяч документов в две тысячи
транзакций — при том, что читает их одна открытая страница."""


@dataclass(frozen=True, slots=True)
class Progress:
    """Состояние выполняющейся задачи."""

    done: int
    total: int
    note: str
    status: JobStatus

    @property
    def percent(self) -> int:
        if self.total <= 0:
            return 0
        return min(100, int(self.done / self.total * 100))

    def to_json(self) -> str:
        return json.dumps(
            {
                "done": self.done,
                "total": self.total,
                "note": self.note,
                "status": self.status.value,
                "percent": self.percent,
            },
            ensure_ascii=False,
        )


def progress_key(job_id: uuid.UUID) -> str:
    return f"job:progress:{job_id}"


def channel_key(job_id: uuid.UUID) -> str:
    return f"job:events:{job_id}"


class JobService:
    """Заведение задач и учёт их выполнения."""

    def __init__(self, db: DbSession, redis: Redis) -> None:
        self._db = db
        self._redis = redis

    def create(
        self,
        *,
        organization_id: uuid.UUID,
        created_by_id: uuid.UUID | None,
        module: str,
        kind: str,
        params: dict[str, Any] | None = None,
        total: int = 0,
    ) -> Job:
        job = Job(
            organization_id=organization_id,
            created_by_id=created_by_id,
            module=module,
            kind=kind,
            params=params or {},
            progress_total=total,
        )
        self._db.add(job)
        self._db.flush()
        logger.info("Задача поставлена", job_id=str(job.id), module=module, kind=kind)
        return job

    def start(self, job_id: uuid.UUID) -> None:
        job = self._require(job_id)
        job.status = JobStatus.RUNNING
        job.started_at = utcnow()
        self._db.commit()
        self._publish(job)

    def advance(
        self, job_id: uuid.UUID, *, done: int, total: int | None = None, note: str = ""
    ) -> None:
        """Двигает прогресс.

        В базу — раз в несколько шагов, в Redis — каждый раз: страницу читает
        человек, и рывками по десять файлов прогресс выглядит зависшим.
        """
        job = self._require(job_id)
        job.progress_done = done
        if total is not None:
            job.progress_total = total
        job.progress_note = note[:512]

        if done % _DB_UPDATE_EVERY == 0 or done >= job.progress_total:
            self._db.commit()
        self._publish(job)

    def finish(
        self,
        job_id: uuid.UUID,
        *,
        result: dict[str, Any] | None = None,
        cost_usd: float | None = None,
    ) -> None:
        job = self._require(job_id)
        job.status = JobStatus.SUCCEEDED
        job.finished_at = utcnow()
        job.result = result
        job.cost_usd = cost_usd
        job.progress_done = job.progress_total or job.progress_done
        self._db.commit()
        self._publish(job)
        logger.info("Задача выполнена", job_id=str(job.id), cost_usd=cost_usd)

    def fail(self, job_id: uuid.UUID, error: str) -> None:
        job = self._require(job_id)
        job.status = JobStatus.FAILED
        job.finished_at = utcnow()
        job.error = error[:4000]
        self._db.commit()
        self._publish(job)
        logger.warning("Задача не выполнена", job_id=str(job.id), error=error)

    def cancel(self, job_id: uuid.UUID) -> None:
        job = self._require(job_id)
        if job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
            return
        job.status = JobStatus.CANCELLED
        job.finished_at = utcnow()
        self._db.commit()
        self._publish(job)

    def read_progress(self, job: Job) -> Progress:
        """Текущее состояние: из Redis, если есть, иначе из базы.

        Redis свежее — он обновляется на каждом шаге. Но задача могла
        закончиться вчера, и тогда её состояние живёт только в базе.
        """
        raw = self._redis.get(progress_key(job.id))
        if isinstance(raw, bytes | str):
            data = json.loads(raw)
            return Progress(
                done=int(data["done"]),
                total=int(data["total"]),
                note=str(data["note"]),
                status=JobStatus(data["status"]),
            )
        return Progress(
            done=job.progress_done,
            total=job.progress_total,
            note=job.progress_note,
            status=job.status,
        )

    def _publish(self, job: Job) -> None:
        """Кладёт прогресс в Redis и оповещает подписчиков.

        Оба действия нужны: значение — для того, кто откроет страницу позже,
        оповещение — для того, у кого она открыта сейчас.
        """
        progress = Progress(
            done=job.progress_done,
            total=job.progress_total,
            note=job.progress_note,
            status=job.status,
        ).to_json()
        try:
            self._redis.set(progress_key(job.id), progress, ex=PROGRESS_TTL_SECONDS)
            self._redis.publish(channel_key(job.id), progress)
        except Exception as exc:  # pragma: no cover — очередь недоступна
            # Потеря прогресса не должна ронять сам разбор: он идёт минутами
            # и стоит денег, а прогресс — это способ на него посмотреть.
            logger.warning("Прогресс не опубликован", job_id=str(job.id), error=str(exc))

    def _require(self, job_id: uuid.UUID) -> Job:
        job = self._db.get(Job, job_id)
        if job is None:
            raise LookupError(f"Задачи {job_id} нет")
        return job


def list_jobs(
    db: DbSession, organization_id: uuid.UUID, *, module: str | None = None, limit: int = 50
) -> list[Job]:
    query = select(Job).where(Job.organization_id == organization_id)
    if module:
        query = query.where(Job.module == module)
    return list(db.scalars(query.order_by(Job.created_at.desc()).limit(limit)))


def stale_running_jobs(db: DbSession, older_than: datetime) -> list[Job]:
    """Задачи, застрявшие в «выполняется».

    Исполнителя могли убить посреди разбора — тогда задача остаётся в этом
    состоянии навсегда и висит в списке как живая. Такие подбираются при
    запуске и помечаются неудавшимися: лучше честное «прервано», чем
    бесконечное «идёт».
    """
    return list(
        db.scalars(
            select(Job).where(
                Job.status == JobStatus.RUNNING,
                Job.started_at.is_not(None),
                Job.started_at < older_than.astimezone(UTC),
            )
        )
    )


__all__ = [
    "JobService",
    "Progress",
    "channel_key",
    "list_jobs",
    "progress_key",
    "stale_running_jobs",
]
