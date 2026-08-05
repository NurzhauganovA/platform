"""Фоновые задачи и прогресс.

Разбор идёт минутами и стоит денег. Отсюда два требования: человек должен
видеть, где он находится сейчас, и должен увидеть, чем всё кончилось и во
сколько обошлось — даже назавтра, даже если очередь с тех пор перезапускали.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from conftest import FakeRedis, sign_in
from fastapi import FastAPI
from fastapi.testclient import TestClient
from platform_api.db.models import Job, JobStatus, Organization, Role
from platform_api.jobs import JobService, progress_key
from sqlalchemy.orm import Session as DbSession


class BrokenRedis(FakeRedis):
    def set(self, key: str, value: str, ex: int | None = None) -> None:
        raise ConnectionError("очередь недоступна")

    def publish(self, channel: str, message: str) -> None:
        raise ConnectionError("очередь недоступна")


@pytest.fixture
def service(db: DbSession, redis: FakeRedis) -> JobService:
    return JobService(db, redis)  # type: ignore[arg-type]


def _org(db: DbSession) -> Organization:
    org = Organization(name="Fintend", slug=f"fintend-{uuid.uuid4().hex[:6]}")
    db.add(org)
    db.flush()
    return org


def _job(service: JobService, org: Organization, total: int = 9) -> Job:
    return service.create(
        organization_id=org.id,
        created_by_id=None,
        module="tender",
        kind="analyze",
        params={"case": "Системный блок"},
        total=total,
    )


# --- учёт -----------------------------------------------------------------


def test_job_starts_queued(service: JobService, db: DbSession) -> None:
    job = _job(service, _org(db))

    assert job.status is JobStatus.QUEUED
    assert job.progress_total == 9


def test_progress_moves(service: JobService, db: DbSession, redis: FakeRedis) -> None:
    job = _job(service, _org(db))
    service.start(job.id)

    service.advance(job.id, done=3, note="КП Примеро.pdf")

    progress = service.read_progress(job)
    assert progress.done == 3
    assert progress.percent == 33
    assert progress.note == "КП Примеро.pdf"
    assert progress.status is JobStatus.RUNNING


def test_result_and_cost_survive(service: JobService, db: DbSession) -> None:
    """Вопрос «сколько мы потратили на разбор» задаётся задним числом."""
    job = _job(service, _org(db))
    service.start(job.id)

    service.finish(job.id, result={"documents": 9}, cost_usd=0.08)

    db.refresh(job)
    assert job.status is JobStatus.SUCCEEDED
    assert job.result == {"documents": 9}
    assert job.cost_usd == pytest.approx(0.08)
    assert job.finished_at is not None


def test_failure_keeps_the_reason(service: JobService, db: DbSession) -> None:
    job = _job(service, _org(db))
    service.start(job.id)

    service.fail(job.id, "Квота Gemini исчерпана")

    db.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.error is not None and "Квота" in job.error


def test_finished_job_is_not_cancelled(service: JobService, db: DbSession) -> None:
    """Отмена задним числом сделала бы вид, что разбора не было — а он оплачен."""
    job = _job(service, _org(db))
    service.finish(job.id, result={})

    service.cancel(job.id)

    db.refresh(job)
    assert job.status is JobStatus.SUCCEEDED


def test_progress_falls_back_to_the_database(
    service: JobService, db: DbSession, redis: FakeRedis
) -> None:
    """Задача закончилась вчера — в Redis её состояния уже нет."""
    job = _job(service, _org(db))
    service.start(job.id)
    service.advance(job.id, done=9, note="готово")
    service.finish(job.id, result={})
    redis.values.clear()

    progress = service.read_progress(job)

    assert progress.status is JobStatus.SUCCEEDED
    assert progress.done == 9


def test_broken_queue_does_not_break_the_run(db: DbSession) -> None:
    """Прогресс — способ посмотреть на разбор, а не сам разбор.

    Если Redis недоступен, разбор обязан продолжаться: он идёт минутами и
    стоит денег, и ронять его из-за неработающей индикации нельзя.
    """
    service = JobService(db, BrokenRedis())  # type: ignore[arg-type]
    job = _job(service, _org(db))

    service.start(job.id)
    service.advance(job.id, done=1, note="первый файл")
    service.finish(job.id, result={"documents": 9})

    db.refresh(job)
    assert job.status is JobStatus.SUCCEEDED


def test_published_payload_is_readable(
    service: JobService, db: DbSession, redis: FakeRedis
) -> None:
    job = _job(service, _org(db))
    service.start(job.id)
    service.advance(job.id, done=5, note="Справка_1824.pdf")

    _channel, message = redis.published[-1]
    data = json.loads(message)

    assert data["done"] == 5
    assert data["percent"] == 55
    assert data["note"] == "Справка_1824.pdf"
    assert redis.values[progress_key(job.id)] == message


# --- через HTTP -----------------------------------------------------------


def test_jobs_list_shows_only_our_own(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    """Чужие задачи не должны попадать в список: в них видно и предмет, и цену."""
    app.state.redis = redis
    service = JobService(db, redis)  # type: ignore[arg-type]
    stranger = _org(db)
    _job(service, stranger)

    org = sign_in(db, app_client)
    _job(service, org)
    db.commit()

    body = app_client.get("/api/jobs").json()

    assert len(body) == 1
    assert body[0]["module"] == "tender"


def test_foreign_job_is_not_found(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    """404, а не 403: иначе по коду ответа перебирается, что вообще существует."""
    app.state.redis = redis
    service = JobService(db, redis)  # type: ignore[arg-type]
    foreign = _job(service, _org(db))
    sign_in(db, app_client)
    db.commit()

    assert app_client.get(f"/api/jobs/{foreign.id}").status_code == 404


def test_job_state_is_served(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    app.state.redis = redis
    service = JobService(db, redis)  # type: ignore[arg-type]
    org = sign_in(db, app_client)
    job = _job(service, org)
    service.start(job.id)
    service.advance(job.id, done=4, note="МЗ.docx")
    db.commit()

    body = app_client.get(f"/api/jobs/{job.id}").json()

    assert body["status"] == "running"
    assert body["percent"] == 44
    assert body["note"] == "МЗ.docx"


def test_jobs_require_a_session(app_client: TestClient) -> None:
    assert app_client.get("/api/jobs").status_code == 401


def test_viewer_may_watch_jobs(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    """Наблюдателю смотреть можно: это отчёт о работе, а не сама работа."""
    app.state.redis = redis
    sign_in(db, app_client, Role.VIEWER)
    db.commit()

    assert app_client.get("/api/jobs").status_code == 200


def test_stream_sends_current_state_first(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    """Страница, открытая в середине разбора, должна сразу показать, где он."""
    app.state.redis = redis
    service = JobService(db, redis)  # type: ignore[arg-type]
    org = sign_in(db, app_client)
    job = _job(service, org)
    service.start(job.id)
    service.advance(job.id, done=6, note="Технические характеристики.docx")
    service.finish(job.id, result={"documents": 9})
    db.commit()

    with app_client.stream("GET", f"/api/jobs/{job.id}/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        first = next(response.iter_lines())

    payload: dict[str, Any] = json.loads(first.removeprefix("data: "))
    assert payload["status"] == "succeeded"
    assert payload["percent"] == 100


def test_result_is_served(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    """Ради результата задачу и запускали.

    Оценка стоимости, посчитанная в фоне, должна дойти до того, кто её просил,
    а не остаться в базе.
    """
    app.state.redis = redis
    service = JobService(db, redis)  # type: ignore[arg-type]
    org = sign_in(db, app_client)
    job = _job(service, org)
    service.start(job.id)
    service.finish(job.id, result={"usd": 0.08, "ocr_pages": 6}, cost_usd=0.0)
    db.commit()

    body = app_client.get(f"/api/jobs/{job.id}").json()

    assert body["result"] == {"usd": 0.08, "ocr_pages": 6}
