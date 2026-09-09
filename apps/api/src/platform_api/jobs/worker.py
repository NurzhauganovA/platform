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
from functools import partial
from typing import Any, ClassVar

from arq import create_pool
from arq.connections import RedisSettings
from redis import Redis
from sqlalchemy import select

from platform_api.config import Settings, get_settings
from platform_api.db.session import create_db_engine, create_session_factory
from platform_api.jobs.runner import (
    JobRunner,
    collect_handlers,
    recover_stale_jobs,
    requeue_lost_jobs,
)
from platform_api.logging import configure_logging, get_logger
from platform_api.modules import ModuleRegistry, discover_modules
from platform_api.storage import FileStorage

logger = get_logger(__name__)

QUEUE_NAME = "fintend:jobs"
TASK_NAME = "run_job"

CONCURRENCY_CEILING = 8
"""Больше этого одновременно не запускаем даже на большой машине: упрёмся не
в процессор, а в частоту обращений к модели."""


def _concurrency() -> int:
    """Сколько задач держать одновременно. Одно ядро — веб-части."""
    from os import cpu_count

    cores = cpu_count() or 2
    return max(2, min(CONCURRENCY_CEILING, cores - 1))


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
    ctx["sessions"] = session_factory
    from platform_api.modules.tender.workspace import CaseWorkspace

    handlers = collect_handlers(registry)
    ctx["runner"] = JobRunner(
        session_factory,
        redis,
        storage,
        handlers,
        CaseWorkspace(settings.storage.cases_root, storage),
    )

    # Задачи, оставшиеся в «выполняется» от убитого исполнителя, подбираются
    # здесь: иначе они висят в списке как живые, и человек ждёт результата,
    # которого не будет.
    recovered = await asyncio.to_thread(
        partial(recover_stale_jobs, session_factory, redis, handlers=handlers)
    )

    # А оставшиеся в «очереди» — отдаются очереди заново. Redis перезапускают
    # вместе с выкладкой, и всё, что стояло в нём на доставку, пропадает:
    # строка в базе есть, работать по ней некому, а на экране «Ставим в
    # очередь…» до конца дня.
    returned = await asyncio.to_thread(partial(requeue_lost_jobs, session_factory, settings))

    logger.info(
        "Исполнитель запущен",
        modules=[module.slug for module in registry.all()],
        handlers=len(collect_handlers(registry)),
        recovered=recovered,
        returned=returned,
        concurrency=WorkerSettings.max_jobs,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    ctx["engine"].dispose()
    ctx["redis"].close()
    logger.info("Исполнитель остановлен")


def scheduled_run(slug: str, kind: str) -> Any:
    """Обёртка расписания вокруг обычной задачи.

    Задача заводится в базе так же, как заведённая кнопкой, и с тем же
    учётом прогресса и стоимости. Отличие одно: автора нет — `created_by_id`
    пуст, и в списке видно, что прогон был по расписанию, а не чей-то.
    """

    async def run(ctx: dict[str, Any]) -> None:
        await asyncio.to_thread(_run_scheduled, ctx, slug, kind)

    # ARQ различает задачи расписания по имени функции. Без переименования
    # все три обёртки зовутся `run`, и остаётся одна — молча.
    run.__name__ = f"scheduled_{slug}_{kind}"
    return run


def _run_scheduled(ctx: dict[str, Any], slug: str, kind: str) -> None:
    from platform_api.db.models import Job, JobStatus, Organization
    from platform_api.jobs import JobService

    runner: JobRunner = ctx["runner"]
    db = ctx["sessions"]()
    try:
        organizations = list(db.execute(select(Organization.id)).scalars())
        service = JobService(db, ctx["redis"])
        started: list[uuid.UUID] = []
        for organization_id in organizations:
            # Предыдущий прогон ещё идёт — второй не заводим. Выгрузка бывает
            # длиннее часа, и без этой проверки к утру в очереди стоит десяток
            # одинаковых, а раздел всё это время пересобирается.
            busy = db.execute(
                select(Job.id)
                .where(Job.organization_id == organization_id)
                .where(Job.module == slug, Job.kind == kind)
                .where(Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)))
                .limit(1)
            ).first()
            if busy is not None:
                logger.info("Прогон по расписанию пропущен", module=slug, kind=kind)
                continue
            job = service.create(
                organization_id=organization_id,
                created_by_id=None,
                module=slug,
                kind=kind,
                params={},
            )
            started.append(job.id)
        db.commit()
    finally:
        db.close()

    for job_id in started:
        runner.run(job_id)


async def sweep_lost(ctx: dict[str, Any]) -> None:
    """Каждую минуту возвращает в очередь то, что до неё не дошло.

    Подбора при запуске мало: исполнитель перезапускается раз в выкладку, а
    щель между «записали в базу» и «положили в Redis» открывается в любой
    момент — сеть моргнула, Redis перезагрузился, обработчик упал между двумя
    строками. Задача при этом висит в «очереди» до следующей выкладки, а
    человек смотрит на «Ставим в очередь…».

    Выдержка в две минуты: только что поставленная задача лежит в Redis и
    ждёт своей очереди законно — подбирать её незачем.
    """
    returned = await asyncio.to_thread(
        partial(requeue_lost_jobs, ctx["sessions"], get_settings(), older_than_minutes=2)
    )
    if returned:
        logger.info("Потерянные задачи возвращены в очередь", count=returned)


def collect_schedule() -> list[Any]:
    """Расписание, объявленное модулями.

    Собирается здесь, а не перечисляется: вписанный сюда список означал бы,
    что следующая площадка обновляется руками, пока кто-нибудь не вспомнит про
    этот файл. Ровно так два раздела и простояли пустыми три недели.
    """
    from arq import cron

    registry = ModuleRegistry(discover_modules())
    # Подбор потерянных — первым и каждую минуту. Он не про предметную область,
    # поэтому и не объявляется модулем: чинить щель между базой и очередью —
    # забота каркаса.
    planned: list[Any] = [
        cron(
            sweep_lost,
            minute=set(range(60)),
            name="jobs:sweep",
            run_at_startup=False,
        )
    ]
    for module in registry.all():
        for spec in module.jobs:
            if not spec.every_hours:
                continue
            planned.append(
                cron(
                    scheduled_run(module.slug, spec.kind),
                    hour=set(range(0, 24, spec.every_hours)),
                    minute={spec.at_minute},
                    name=f"{module.slug}:{spec.kind}",
                    # Не при запуске: перезапуск исполнителя не повод гонять
                    # выгрузку заново, а перезапускают его на каждой выкатке.
                    run_at_startup=False,
                )
            )
    return planned


class WorkerSettings:
    """Настройки ARQ."""

    functions: ClassVar[list[Any]] = [run_job]

    cron_jobs: ClassVar[list[Any]] = []
    """Расписание. Заполняется при запуске, а не здесь.

    Здесь нельзя: сборка расписания поднимает модули, а модули импортируют
    постановку задачи из этого же файла. На объявлении класса он ещё не
    доимпортирован, и получается круг."""
    on_startup = startup
    on_shutdown = shutdown
    queue_name = QUEUE_NAME

    max_jobs = _concurrency()
    """Сколько задач одновременно — по числу ядер машины.

    Было два на любой машине, и это упиралось в потолок ровно там, где работы
    много: взяли пять лотов — обсуждение и разбор каждого встают в очередь по
    двое, и пятый ждёт четверть часа. Работа при этом наполовину не своя:
    задача ждёт ответа модели, а процессор в это время свободен.

    Считается от ядер, а не задаётся числом: у ноутбука их восемь, у сервера
    четыре, и одно и то же число означало бы на одном простой, на другом
    драку за процессор. Одно ядро оставляется веб-части: она отвечает
    человеку, и её нельзя оставлять без времени.

    Потолок в восемь — не про память, а про модель: она отвечает отказом по
    частоте, и десять одновременных разборов приходят к нему быстрее, чем
    заканчиваются."""

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

    WorkerSettings.cron_jobs = collect_schedule()
    logger.info(
        "Расписание собрано",
        jobs=[job.name for job in WorkerSettings.cron_jobs],
    )
    run_worker(WorkerSettings)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
