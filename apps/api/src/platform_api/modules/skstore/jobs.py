"""Фоновые задачи модуля SKStore.

Предметной логики здесь нет: задача зовёт те же сервисы ядра, что и его CLI.
Второй способ выгружать закупы или считать маржу неизбежно разошёлся бы с
первым — и разошёлся бы на той закупке, где ошибка стоит дороже всего.

Обе задачи долгие и обе меняют картину в списке, поэтому живут в очереди, а не
в обработчике запроса. Разделены они по цене: выгрузка бесплатна и её можно
гонять хоть каждый час, пересчёт с поиском на рынках стоит денег и запускается
осознанно.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from platform_api.jobs.contract import JobContext, JobSpec
from platform_api.logging import get_logger

logger = get_logger(__name__)


def sync_sources(
    ctx: JobContext, *, skip_catalog: bool = True, analyze_new: bool = False, **_: Any
) -> dict[str, Any]:
    """Тянет с площадки то, что настроено: прайс, закупы, склад, каталог.

    Источники идут независимо: не настроенный или упавший не должен утащить за
    собой остальные. Человек нажал «Обновить» — он хочет получить максимум
    того, что доступно, а не отказ из-за одного незаполненного доступа.

    Каталог по умолчанию пропускается. Полный проход по нему — около трёхсот
    запросов и шесть минут ради двухсот тридцати тысяч чужих карточек, а
    нужен он только для медианы по ТРУ и меняется медленно.

    `analyze_new` дописывает к выгрузке разбор — но только тех закупов,
    которых в базе ещё не было. Появляется их за час пять-десять, а лежит
    шестьсот; разбор всех подряд — это часы работы модели и деньги за то, что
    посчитано вчера и с тех пор не менялось. Решает не задача, а эндпоинт: шаг
    платный, и заказывать его может только тот, кто отвечает за бюджет.
    """
    from skstore.application.container import Container
    from skstore.application.sync import SyncService
    from skstore.exceptions import SkstoreError

    from platform_api.modules.skstore.core import core_settings

    settings = core_settings()
    container = Container(settings)
    service = SyncService(container)
    # Момент до выгрузки: всё, что после него впервые попало в базу, и есть
    # новое. Время питона, а не базы, и это не небрежность — `first_seen_at`
    # проставляет тот же питон при вставке, так что сравниваются показания
    # одних часов.
    since = datetime.now(UTC) if analyze_new else None

    tasks: list[tuple[str, Any]] = []
    if settings.openrest.is_configured:
        tasks.append(("Прайс", service.sync_prices))
    if settings.cabinet.is_configured:
        tasks.append(("Закупы", service.sync_bargains))
    if settings.ourstore.is_configured:
        tasks.append(("Склад Marten", service.sync_stock))
    if not skip_catalog:
        tasks.append(("Каталог площадки", service.sync_catalog))

    if not tasks:
        return {
            "records": 0,
            "reason": "Ни один источник не настроен — заполните .env проекта",
            "cost_usd": 0.0,
        }

    ctx.advance(0, total=len(tasks), note="начинаем выгрузку")
    counts: dict[str, int] = {}
    errors: list[str] = []

    try:
        for index, (name, task) in enumerate(tasks, start=1):
            ctx.advance(index - 1, note=name)
            try:
                counts[name] = task()
            except SkstoreError as exc:
                errors.append(f"{name}: {exc}")
                logger.warning("Источник не выгрузился", source=name, error=str(exc))
            ctx.advance(index, note=f"{name} — готово")

        fresh: dict[str, Any] = {}
        if since is not None:
            ctx.advance(len(tasks), note="разбираем новые закупы")
            fresh = _analyze_fresh(container, since)
    finally:
        container.dispose()

    return {
        "records": sum(counts.values()),
        "by_source": counts,
        "errors": errors,
        **fresh,
        # Сама выгрузка модель не трогает; разбор новых — трогает, и его
        # расход считается ядром в токенах, а не в долларах.
        "cost_usd": 0.0,
    }


def _analyze_fresh(container: Any, since: Any) -> dict[str, Any]:
    """Разбирает закупы, впервые появившиеся после указанного момента.

    Ничего нового — ничего и не считаем: пустой прогон ядра всё равно поднял
    бы весь каталог по ТРУ, а это секунды на ровном месте.
    """
    from skstore.application.analysis import AnalysisService
    from skstore.domain.enums import BargainStatus

    with container.unit_of_work() as uow:
        ids = uow.bargains.ids_seen_since(since, BargainStatus.ACTIVE)
        if not ids:
            return {"analyzed_new": 0}
        service = AnalysisService(container)
        analyses = service.analyze_within(uow, BargainStatus.ACTIVE, platform_ids=ids)
        uow.commit()
        stats = service.last_run_stats

    return {
        "analyzed_new": len(analyses),
        "promising_new": sum(1 for item in analyses if item.verdict.value == "promising"),
        "market_searched": stats.market_searched if stats else 0,
        "total_tokens": stats.total_tokens if stats else 0,
    }


def analyze(ctx: JobContext, *, search_market: bool = True, **_: Any) -> dict[str, Any]:
    """Считает себестоимость и маржу по активным закупам.

    Здесь и только здесь тратятся деньги: поиск на внешних рынках идёт через
    модель. Открытая страница пересобирает вердикты бесплатно, по уже
    сохранённым находкам, — а этот прогон добывает новые.

    Ядро само решает, кого отправлять в поиск: тех, где своей цены нет, начиная
    с самых дорогих, и не больше заданного в настройках числа за прогон.
    """
    from skstore.application.analysis import AnalysisService
    from skstore.application.container import Container
    from skstore.domain.enums import BargainStatus

    from platform_api.modules.skstore.core import core_settings

    settings = core_settings()
    container = Container(settings)
    try:
        ctx.advance(0, total=1, note="считаем себестоимость и маржу")
        service = AnalysisService(container)
        analyses = service.analyze(BargainStatus.ACTIVE, search_market=search_market)
        ctx.advance(1, note="готово")
        stats = service.last_run_stats
    finally:
        container.dispose()

    promising = sum(1 for item in analyses if item.verdict.value == "promising")
    return {
        "bargains": len(analyses),
        "promising": promising,
        "market_searched": stats.market_searched if stats else 0,
        "market_priced": stats.market_priced if stats else 0,
        "total_tokens": stats.total_tokens if stats else 0,
        # Расход в долларах ядро не считает: у него нет прайса моделей.
        # Токены видно, и по ним же считается стоимость в тендерном модуле.
        "cost_usd": None,
    }


jobs = (
    JobSpec(kind="sync", handler=sync_sources, title="Обновление данных с площадки"),
    JobSpec(kind="analyze", handler=analyze, title="Расчёт себестоимости и маржи"),
)

__all__ = ["jobs"]
