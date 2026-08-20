"""Фоновые задачи модуля OMarket.

Предметной логики здесь нет: задача зовёт те же сервисы ядра, что и его CLI.

Выгрузка работает на сессии, снятой при `omarket login`. Сам вход сюда не
переносится: площадка требует подписи ЭЦП в окне настоящего браузера, а
безоконный режим она отсекает ещё до формы. Ключ лежит у человека, и это
правильное место для ключа. Без живой сессии задача не пытается ходить в
кабинет вслепую, а сразу говорит, что делать.
"""

from __future__ import annotations

from typing import Any

from platform_api.jobs.contract import JobContext, JobSpec
from platform_api.logging import get_logger

logger = get_logger(__name__)


_DETAILS_PER_RUN = 50
"""Сколько карточек читать за прогон.

Карточка — это переход на страницу, а их сотни: полный обход занимает минуты,
тогда как список забирается за двадцать секунд. Читаются те, которые ещё не
открывали, начиная с самых срочных, — за несколько прогонов охват набирается
сам. То же значение по умолчанию стоит в CLI ядра.
"""


def sync_sources(
    ctx: JobContext, *, with_details: bool = True, details_limit: int = _DETAILS_PER_RUN, **_: Any
) -> dict[str, Any]:
    """Тянет предзаказы из кабинета, карточки и склад Marten.

    Карточки идут отдельным проходом и по делу: комиссия площадки и цена
    конкурентов видны только в них, а без комиссии маржа завышена ровно на её
    величину.
    """
    from omarket.application.container import Container
    from omarket.application.sync import SyncService
    from omarket.exceptions import OmarketError

    from platform_api.modules.omarket.core import core_settings, has_session

    if not has_session():
        return {
            "records": 0,
            "reason": (
                "Нет сессии кабинета. Вход идёт по ЭЦП в окне браузера, "
                "поэтому выполняется на своей машине: `omarket login`"
            ),
            "cost_usd": 0.0,
        }

    settings = core_settings()
    container = Container(settings)
    service = SyncService(container)

    tasks: list[tuple[str, Any]] = [("Предзаказы", service.sync_preorders)]
    if with_details:
        tasks.append(("Карточки предзаказов", lambda: service.sync_details(limit=details_limit)))
    if settings.ourstore.is_configured:
        tasks.append(("Склад Marten", service.sync_stock))

    ctx.advance(0, total=len(tasks), note="начинаем выгрузку")
    counts: dict[str, int] = {}
    errors: list[str] = []

    try:
        for index, (name, task) in enumerate(tasks, start=1):
            ctx.advance(index - 1, note=name)
            try:
                counts[name] = task()
            except OmarketError as exc:
                errors.append(f"{name}: {exc}")
                logger.warning("Источник не выгрузился", source=name, error=str(exc))
            ctx.advance(index, note=f"{name} — готово")
    finally:
        container.dispose()

    return {
        "records": sum(counts.values()),
        "by_source": counts,
        "errors": errors,
        # Выгрузка идёт в кабинет площадки и модель не трогает.
        "cost_usd": 0.0,
    }


def analyze(ctx: JobContext, *, search_market: bool = True, **_: Any) -> dict[str, Any]:
    """Считает себестоимость и маржу по актуальным предзаказам.

    Здесь и только здесь тратятся деньги: поиск на внешних рынках идёт через
    модель. Открытая страница показывает уже посчитанное и не платит.
    """
    from omarket.application.analysis import AnalysisService
    from omarket.application.container import Container

    from platform_api.modules.omarket.core import core_settings

    container = Container(core_settings())
    try:
        ctx.advance(0, total=1, note="считаем себестоимость и маржу")
        service = AnalysisService(container)
        stored = service.analyze(search_market=search_market)
        ctx.advance(1, note="готово")
        stats = service.last_run
    finally:
        container.dispose()

    return {
        "preorders": stored,
        "matched_stock": stats.matched_stock if stats else 0,
        "market_searched": stats.market_searched if stats else 0,
        "market_priced": stats.market_priced if stats else 0,
        "total_tokens": stats.market_tokens if stats else 0,
        # Расход в долларах ядро не считает: у него нет прайса моделей.
        "cost_usd": None,
    }


jobs = (
    JobSpec(kind="sync", handler=sync_sources, title="Обновление данных с площадки"),
    JobSpec(kind="analyze", handler=analyze, title="Расчёт себестоимости и маржи"),
)

__all__ = ["jobs"]
