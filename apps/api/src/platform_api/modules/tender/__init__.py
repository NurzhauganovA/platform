"""Тендерный модуль платформы.

Тонкий слой над пакетом `tender-analyze`: разбор документов, сравнение
предложений, поиск на рынках и сборка нашего КП живут там и остаются
доступными из его CLI. Здесь — только перевод этого на язык HTTP.

Правило простое: в этом каталоге не должно появиться ни одной строки
предметной логики. Как только сюда переедет расчёт цены или разбор документа,
одно и то же начнёт считаться двумя способами — в вебе и в CLI, — и они
разойдутся ровно на той закупке, где ошибка стоит дороже всего.
"""

from __future__ import annotations

from platform_api.modules import ModuleSpec, NavItem
from platform_api.modules.tender import health
from platform_api.modules.tender.jobs import jobs
from platform_api.modules.tender.router import router

module = ModuleSpec(
    slug="tender",
    title="Тендеры",
    description="Разбор тендерной документации, сравнение КП и наши предложения",
    router=router,
    nav=(
        NavItem(title="Закупки", path="/tender/cases", icon="folder"),
        NavItem(title="История цен", path="/tender/prices", icon="chart"),
        NavItem(title="Конкуренты", path="/tender/competitors", icon="users"),
    ),
    jobs=jobs,
    health=health.check,
)

__all__ = ["module"]
