"""Модуль OMarket.

Тонкий слой над пакетом `omarket-analytics`: выгрузка предзаказов из кабинета,
поиск себестоимости на складе и внешних рынках, расчёт маржи и книга Excel
живут там и остаются доступными из его CLI. Здесь — только перевод этого на
язык HTTP.

Правило простое: в этом каталоге не должно появиться ни одной строки
предметной логики. Как только сюда переедет расчёт маржи или отбор
предзаказов, одно и то же начнёт считаться двумя способами — в вебе и в CLI.

Вход в кабинет платформа не делает и делать не будет: площадка требует подписи
ЭЦП в окне настоящего браузера, а ключ лежит у сотрудника. Платформа работает
с сессией, снятой командой `omarket login`, и честно показывает, когда та
кончилась.
"""

from __future__ import annotations

from platform_api.auth.dependencies import READS, names
from platform_api.modules import ModuleSpec, NavItem
from platform_api.modules.omarket import health
from platform_api.modules.omarket.jobs import jobs
from platform_api.modules.omarket.router import router

module = ModuleSpec(
    slug="omarket",
    title="OMarket",
    description="Предзаказы OMarket.kz: себестоимость, маржа и что успеть сегодня",
    router=router,
    nav=(
        NavItem(
            title="Предзаказы OMarket",
            path="/omarket/preorders",
            icon="table",
            roles=names(*READS),
            group="Площадки",
        ),
        NavItem(
            title="Аналитика предзаказов",
            path="/omarket/analytics",
            icon="chart",
            roles=names(*READS),
            group="Площадки",
        ),
    ),
    jobs=jobs,
    health=health.check,
)

__all__ = ["module"]
