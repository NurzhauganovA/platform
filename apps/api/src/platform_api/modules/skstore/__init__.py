"""Модуль SKStore.

Тонкий слой над пакетом `skstore-analytics`: выгрузка закупов с площадки,
поиск себестоимости на складе и внешних рынках, расчёт маржи и книга Excel
живут там и остаются доступными из его CLI. Здесь — только перевод этого на
язык HTTP.

Правило простое: в этом каталоге не должно появиться ни одной строки
предметной логики. Как только сюда переедет расчёт маржи или отбор закупов,
одно и то же начнёт считаться двумя способами — в вебе и в CLI, — и они
разойдутся ровно на том закупе, где ошибка стоит дороже всего.

Таблица в браузере намеренно собирается из тех же `Column`, что и лист книги.
Сотрудник работает в двух местах сразу и сверяет одно с другим; колонки,
разошедшиеся на одну, стоят получаса выяснений, кто из двух прав.
"""

from __future__ import annotations

from platform_api.modules import ModuleSpec, NavItem
from platform_api.modules.skstore import health
from platform_api.modules.skstore.jobs import jobs
from platform_api.modules.skstore.router import router

module = ModuleSpec(
    slug="skstore",
    title="SKStore",
    description="Закупы Самрук-Қазына: себестоимость, маржа и что брать сегодня",
    router=router,
    nav=(
        NavItem(title="Закупы", path="/skstore/bargains", icon="table"),
        NavItem(title="Аналитика", path="/skstore/analytics", icon="chart"),
    ),
    jobs=jobs,
    health=health.check,
)

__all__ = ["module"]
