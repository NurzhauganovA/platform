"""Задачи: список, состояние и живой прогресс.

Прогресс отдаётся через Server-Sent Events, а не веб-сокетом. Поток здесь
односторонний — сервер сообщает, браузер слушает, — и SSE переживает разрыв
связи сам: браузер переподключается без нашего участия, чего у веб-сокета
нет. За минуты разбора связь рвётся регулярно.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from platform_api.auth.dependencies import CurrentUser, Db, requires_read
from platform_api.db.models import Job, JobStatus
from platform_api.jobs.service import JobService, channel_key, list_jobs
from platform_api.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["Задачи"])

HEARTBEAT_SECONDS = 15
"""Как часто в тихий поток уходит комментарий-пустышка.

Без него обратные прокси и браузеры закрывают соединение, не дождавшись
данных, — а во время разбора крупного файла пауза в минуту обычна."""


class JobOut(BaseModel):
    id: uuid.UUID
    module: str
    kind: str
    status: JobStatus

    done: int = 0
    total: int = 0
    percent: int = 0
    note: str = ""

    error: str | None = None
    cost_usd: float | None = None

    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


def _to_out(job: Job, service: JobService) -> JobOut:
    progress = service.read_progress(job)
    return JobOut(
        id=job.id,
        module=job.module,
        kind=job.kind,
        status=progress.status,
        done=progress.done,
        total=progress.total,
        percent=progress.percent,
        note=progress.note,
        error=job.error,
        cost_usd=job.cost_usd,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _service(request: Request, db: Db) -> JobService:
    return JobService(db, request.app.state.redis)


@router.get("", summary="Список задач")
def get_jobs(
    identity: CurrentUser,
    db: Db,
    request: Request,
    module: str | None = None,
    limit: int = 50,
    _guard: Annotated[None, requires_read] = None,
) -> list[JobOut]:
    service = _service(request, db)
    jobs = list_jobs(db, identity.organization.id, module=module, limit=min(limit, 200))
    return [_to_out(job, service) for job in jobs]


@router.get("/{job_id}", summary="Состояние задачи")
def get_job(
    job_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    request: Request,
    _guard: Annotated[None, requires_read] = None,
) -> JobOut:
    job = _require_own_job(db, job_id, identity)
    return _to_out(job, _service(request, db))


@router.get("/{job_id}/stream", summary="Живой прогресс")
async def stream_job(
    job_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    request: Request,
    _guard: Annotated[None, requires_read] = None,
) -> StreamingResponse:
    """Поток событий по одной задаче.

    Первым сообщением уходит текущее состояние: страница, открытая в середине
    разбора, должна сразу показать, где он находится, а не ждать следующего
    шага.
    """
    job = _require_own_job(db, job_id, identity)
    service = _service(request, db)
    initial = service.read_progress(job).to_json()
    redis = request.app.state.redis

    async def events() -> AsyncIterator[bytes]:
        yield _sse(initial)
        if job.status in _FINISHED:
            return

        pubsub = redis.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(channel_key(job_id))
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await asyncio.to_thread(pubsub.get_message, timeout=HEARTBEAT_SECONDS)
                if message is None:
                    # Тишина: держим соединение живым, иначе прокси его закроет.
                    yield b": heartbeat\n\n"
                    continue
                payload = message["data"]
                text = payload.decode() if isinstance(payload, bytes) else str(payload)
                yield _sse(text)
                if _is_final(text):
                    break
        finally:
            pubsub.close()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Отключает буферизацию в nginx: без этого события копятся и
            # приходят пачкой в конце, то есть прогресса не видно вовсе.
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{job_id}/cancel", summary="Отменить задачу")
def cancel_job(
    job_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    request: Request,
    _guard: Annotated[None, Depends(lambda: None)] = None,
) -> JobOut:
    job = _require_own_job(db, job_id, identity)
    service = _service(request, db)
    service.cancel(job.id)
    db.refresh(job)
    return _to_out(job, service)


def _require_own_job(db: Db, job_id: uuid.UUID, identity: CurrentUser) -> Job:
    """Задача своей организации — или 404.

    Именно 404, а не 403: иначе по коду ответа перебирается, какие задачи
    вообще существуют.
    """
    job = db.get(Job, job_id)
    if job is None or job.organization_id != identity.organization.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    return job


def _sse(data: str) -> bytes:
    return f"data: {data}\n\n".encode()


def _is_final(payload: str) -> bool:
    return any(f'"status": "{state.value}"' in payload for state in _FINISHED)


_FINISHED = (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)
