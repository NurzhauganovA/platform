"""Выполнение задач.

Проверяется поведение вокруг предметной работы, а не она сама: что исход
записан, что упавшая задача не уносит с собой очередь и что отмена
останавливает разбор в течение шага, а не по его завершении.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from conftest import FakeRedis
from fastapi import APIRouter
from platform_api.db.models import Job, JobStatus, Organization
from platform_api.errors import SpokenError
from platform_api.jobs.contract import JobSpec
from platform_api.jobs.runner import JobRunner, collect_handlers, recover_stale_jobs
from platform_api.jobs.service import JobService
from platform_api.modules import ModuleRegistry, ModuleSpec
from platform_api.storage import FileStorage
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def factory(connection: Any) -> sessionmaker[DbSession]:
    return sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


def _org(db: DbSession) -> Organization:
    org = Organization(name="Fintend", slug=f"fintend-{uuid.uuid4().hex[:6]}")
    db.add(org)
    db.flush()
    db.commit()
    return org


def _queue(db: DbSession, redis: FakeRedis, kind: str = "demo", **params: Any) -> Job:
    job = JobService(db, redis).create(  # type: ignore[arg-type]
        organization_id=_org(db).id,
        created_by_id=None,
        module="probe",
        kind=kind,
        params=params,
        total=3,
    )
    db.commit()
    return job


def _runner(
    factory: sessionmaker[DbSession],
    redis: FakeRedis,
    tmp_path: Any,
    handler: Any,
    kind: str = "demo",
) -> JobRunner:
    return JobRunner(
        factory,
        redis,
        FileStorage(tmp_path, max_bytes=1024),
        {("probe", kind): JobSpec(kind=kind, handler=handler)},
    )


def test_result_and_cost_are_recorded(
    db: DbSession, factory: sessionmaker[DbSession], redis: FakeRedis, tmp_path: Any
) -> None:
    def handler(ctx: Any, **_: Any) -> dict[str, Any]:
        ctx.advance(3, note="готово")
        return {"documents": 9, "cost_usd": 0.08}

    job = _queue(db, redis)
    _runner(factory, redis, tmp_path, handler).run(job.id)

    db.refresh(job)
    assert job.status is JobStatus.SUCCEEDED
    assert job.result == {"documents": 9}
    # Стоимость вынута из результата в своё поле: вопрос «сколько потратили»
    # задают по всем задачам сразу, а не по одной.
    assert job.cost_usd == pytest.approx(0.08)


def test_failed_job_does_not_stop_the_queue(
    db: DbSession, factory: sessionmaker[DbSession], redis: FakeRedis, tmp_path: Any
) -> None:
    """Один битый архив не должен останавливать разбор для всех остальных."""

    def handler(ctx: Any, **_: Any) -> dict[str, Any]:
        # Обработчик говорит человеку сам: текст написан для него и доходит
        # как есть. Внутренние поломки так не делают — их текст заменяется
        # фразой с кодом обращения, и на это есть свой тест.
        raise SpokenError("битый архив")

    job = _queue(db, redis)

    _runner(factory, redis, tmp_path, handler).run(job.id)

    db.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.error is not None and "битый архив" in job.error


def test_cancel_stops_within_a_step(
    db: DbSession, factory: sessionmaker[DbSession], redis: FakeRedis, tmp_path: Any
) -> None:
    """Кнопка «отменить» должна останавливать разбор в течение шага.

    Каждый шаг — разобранный файл, а он стоит денег: дожидаться конца прогона
    после отмены значит платить за то, от чего человек уже отказался.
    """
    seen: list[int] = []

    def handler(ctx: Any, **_: Any) -> dict[str, Any]:
        for step in range(1, 10):
            seen.append(step)
            if step == 2:
                # Отмена приходит из другого процесса — веб-сервера.
                JobService(db, redis).cancel(ctx.job_id)  # type: ignore[arg-type]
            ctx.advance(step, note=f"файл {step}")
        return {"documents": 9}

    job = _queue(db, redis)
    _runner(factory, redis, tmp_path, handler).run(job.id)

    db.refresh(job)
    assert job.status is JobStatus.CANCELLED
    # Остановились сразу после шага, на котором пришла отмена.
    assert seen == [1, 2]


def test_missing_handler_is_a_failure_not_a_crash(
    db: DbSession, factory: sessionmaker[DbSession], redis: FakeRedis, tmp_path: Any
) -> None:
    """Модуль отключили, а задачи от него остались в очереди."""
    job = _queue(db, redis, kind="unknown")
    runner = JobRunner(factory, redis, FileStorage(tmp_path, max_bytes=1024), {})

    runner.run(job.id)

    db.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.error is not None and "не подключён" in job.error


def test_job_is_not_run_twice(
    db: DbSession, factory: sessionmaker[DbSession], redis: FakeRedis, tmp_path: Any
) -> None:
    """Очередь может доставить сообщение повторно.

    Второй запуск оплаченного разбора — это второй счёт за ту же работу.
    """
    calls: list[int] = []

    def handler(ctx: Any, **_: Any) -> dict[str, Any]:
        calls.append(1)
        return {}

    job = _queue(db, redis)
    runner = _runner(factory, redis, tmp_path, handler)
    runner.run(job.id)
    runner.run(job.id)

    assert len(calls) == 1


def test_parameters_reach_the_handler(
    db: DbSession, factory: sessionmaker[DbSession], redis: FakeRedis, tmp_path: Any
) -> None:
    received: dict[str, Any] = {}

    def handler(ctx: Any, **params: Any) -> dict[str, Any]:
        received.update(params)
        return {}

    job = _queue(db, redis, file_ids=["a", "b"], with_market=True)
    _runner(factory, redis, tmp_path, handler).run(job.id)

    assert received == {"file_ids": ["a", "b"], "with_market": True}


def test_stale_jobs_are_picked_up(
    db: DbSession, factory: sessionmaker[DbSession], redis: FakeRedis
) -> None:
    """Исполнителя убили посреди разбора.

    Задача осталась бы в «выполняется» навсегда, и человек ждал бы результата,
    которого не будет. Честное «прервано» говорит, что прогон надо повторить.
    """
    from datetime import timedelta

    from platform_api.db.base import utcnow

    job = _queue(db, redis)
    service = JobService(db, redis)  # type: ignore[arg-type]
    service.start(job.id)
    job.started_at = utcnow() - timedelta(hours=3)
    db.commit()

    recovered = recover_stale_jobs(factory, redis)

    db.refresh(job)
    assert recovered == 1
    assert job.status is JobStatus.FAILED
    assert job.error is not None and "прерван" in job.error


# --- сбор обработчиков ----------------------------------------------------


def test_handlers_are_keyed_by_module_and_kind() -> None:
    """`analyze` есть и у тендеров, и у SKStore — сталкиваться они не должны."""
    registry = ModuleRegistry(
        [
            ModuleSpec(
                slug="tender",
                title="Тендеры",
                router=APIRouter(),
                jobs=(JobSpec(kind="analyze", handler=lambda ctx: {}),),
            ),
            ModuleSpec(
                slug="skstore",
                title="SKStore",
                router=APIRouter(),
                jobs=(JobSpec(kind="analyze", handler=lambda ctx: {}),),
            ),
        ]
    )

    handlers = collect_handlers(registry)

    assert set(handlers) == {("tender", "analyze"), ("skstore", "analyze")}


def test_duplicate_job_in_one_module_is_refused() -> None:
    registry = ModuleRegistry(
        [
            ModuleSpec(
                slug="tender",
                title="Тендеры",
                router=APIRouter(),
                jobs=(
                    JobSpec(kind="analyze", handler=lambda ctx: {}),
                    JobSpec(kind="analyze", handler=lambda ctx: {}),
                ),
            )
        ]
    )

    with pytest.raises(ValueError, match="дважды"):
        collect_handlers(registry)


def test_fail_vnutrennyaya_polomka_ne_pokazyvaetsya_slovami_pitona(
    db: DbSession, factory: sessionmaker[DbSession], redis: FakeRedis, tmp_path: Any
) -> None:
    """Сотрудники — закупщики, а не программисты.

    «TypeError: 'NoneType' object is not subscriptable» на экране выглядит
    так, будто человек что-то испортил сам, и заканчивается звонком «у меня
    всё сломалось». Наружу уходит фраза и код обращения, по которому запись
    находится в журнале одним поиском.
    """

    def handler(ctx: Any, **_: Any) -> dict[str, Any]:
        raise TypeError("'NoneType' object is not subscriptable")

    job = _queue(db, redis)

    _runner(factory, redis, tmp_path, handler).run(job.id)

    db.refresh(job)
    assert job.error is not None
    assert "NoneType" not in job.error and "TypeError" not in job.error
    assert "код" in job.error
