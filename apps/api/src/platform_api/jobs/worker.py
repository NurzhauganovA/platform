"""Исполнитель очереди.

Запускается отдельным процессом: `python -m platform_api.jobs.worker`. Отдельным
намеренно — разбор занимает процессор надолго, и в одном процессе с
веб-сервером он превратил бы каждый запрос в ожидание.

Обработчики синхронные, поэтому выполняются в потоке. Внутри цикла событий
блокирующий вызов остановил бы и приём новых задач, и отчёты о прогрессе — то
есть ровно то, ради чего очередь и заводилась.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, ClassVar

from arq import create_pool
from arq.connections import RedisSettings
from redis import Redis

from platform_api.config import Settings, get_settings
from platform_api.db.session import create_db_engine, create_session_factory
from platform_api.jobs.runner import JobRunner, collect_handlers, recover_stale_jobs
from platform_api.logging import configure_logging, get_logger
from platform_api.modules import ModuleRegistry, discover_modules
from platform_api.storage import FileStorage

logger = get_logger(__name__)

QUEUE_NAME = "fintend:jobs"
TASK_NAME = "run_job"


async def run_job(ctx: dict[str, Any], job_id: str) -> None:
    """Точка входа очереди: выполнить задачу по её идентификатору.

    В очередь кладётся только идентификатор. Параметры лежат в базе, и это не
    формальность: очередь — не хранилище, её содержимое переживает разве что
    перезапуск, а состав закупки нужен и через месяц.
    """
    runner: JobRunner = ctx["runner"]
    await asyncio.to_thread(runner.run, uuid.UUID(job_id))


async def enqueue(redis_settings: RedisSettings, job_id: uuid.UUID) -> None:
    pool = await create_pool(redis_settings, default_queue_name=QUEUE_NAME)
    try:
        await pool.enqueue_job(TASK_NAME, str(job_id))
    finally:
        await pool.aclose()


def enqueue_sync(settings: Settings, job_id: uuid.UUID) -> None:
    """Ставит задачу из синхронного кода — из обработчика запроса.

    Обработчики у нас синхронные, а клиент очереди асинхронный. Собственный
    цикл событий на один вызов дешевле, чем делать асинхронным весь слой
    ради постановки в очередь.
    """
    asyncio.run(enqueue(redis_settings(settings), job_id))


def redis_settings(settings: Settings) -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis.url)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    registry = ModuleRegistry(discover_modules())
    engine = create_db_engine(settings.db)
    session_factory = create_session_factory(engine)
    redis = Redis.from_url(settings.redis.url)
    storage = FileStorage(settings.storage.root, int(settings.storage.max_upload_mb * 1024 * 1024))

    ctx["engine"] = engine
    ctx["redis"] = redis
    ctx["runner"] = JobRunner(session_factory, redis, storage, collect_handlers(registry))

    # Задачи, оставшиеся в «выполняется» от убитого исполнителя, подбираются
    # здесь: иначе они висят в списке как живые, и человек ждёт результата,
    # которого не будет.
    recovered = await asyncio.to_thread(recover_stale_jobs, session_factory, redis)

    logger.info(
        "Исполнитель запущен",
        modules=[module.slug for module in registry.all()],
        handlers=len(collect_handlers(registry)),
        recovered=recovered,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    ctx["engine"].dispose()
    ctx["redis"].close()
    logger.info("Исполнитель остановлен")


class WorkerSettings:
    """Настройки ARQ."""

    functions: ClassVar[list[Any]] = [run_job]
    on_startup = startup
    on_shutdown = shutdown
    queue_name = QUEUE_NAME

    max_jobs = 2
    """Сколько задач одновременно.

    Немного: каждая занимает процессор разбором и упирается в ограничение
    частоты обращений к модели. Больше — не быстрее, а только дороже по
    памяти и ближе к отказам по частоте."""

    job_timeout = 3600
    """Час на задачу. Разбор папки на две тысячи документов идёт долго, и
    обрывать его на середине — значит выбросить оплаченную работу."""

    keep_result = 0
    """Итог хранится в базе, а не в очереди: он нужен и через месяц."""

    max_tries = 1
    """Повторов нет. Задача стоит денег, и молчаливый повтор после сбоя
    оплачивается второй раз; решение перезапустить принимает человек."""

    # Атрибут, а не метод: ARQ читает его как значение и на вызываемом
    # объекте падает с невнятным «у staticmethod нет host».
    redis_settings = RedisSettings.from_dsn(get_settings().redis.url)


def main() -> None:
    from arq import run_worker

    run_worker(WorkerSettings)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
