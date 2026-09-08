"""Модуль госзакупок.

Тонкий слой над пакетом `goszakup-analytics`: обход портала, разбор карточек,
хранение лотов и книга Excel живут там и остаются доступными из его CLI.
Здесь — только перевод этого на язык HTTP.

Отличие раздела от площадок в том, что задаёт объём работы. У SKStore и
OMarket мы видим всё, что они показывают; на государственном портале сотни
тысяч лотов, и обход идёт **строго по списку кодов ЕНС ТРУ**. Список ведёт
администратор, и он же определяет, что попадёт в отбор.
"""

from __future__ import annotations

from platform_api.auth.dependencies import READS, REMARKS, names
from platform_api.db.models import Role
from platform_api.modules import ModuleSpec, NavItem
from platform_api.modules.goszakup import health
from platform_api.modules.goszakup.jobs import jobs
from platform_api.modules.goszakup.router import router

module = ModuleSpec(
    slug="goszakup",
    title="Госзакупки",
    description="Лоты zakup.gov.kz по нашей номенклатуре",
    router=router,
    nav=(
        # Роли перечислены явно, хотя это «всем кроме юриста». Пункт без
        # ролей виден всем, а за рабочим списком цены и маржа: юрист получил
        # бы кнопку, отвечающую отказом, — самый ходовой способ научить людей
        # не доверять меню.
        NavItem(
            title="Лоты портала",
            path="/goszakup/lots",
            group="Площадки",
            icon="table",
            roles=names(*READS),
        ),
        # Настройка обхода — только администратору, хотя список читается всем
        # с доступом к разделу. Пункт меню про удобство: остальным он ведёт
        # туда, где нечего нажать, а сайдбар и так на двенадцать строк.
        NavItem(
            title="Обход портала",
            path="/goszakup/codes",
            group="Площадки",
            icon="settings",
            roles=names(Role.ADMIN),
        ),
        NavItem(
            title="Обсуждения",
            path="/goszakup/remarks",
            # В «Моём столе», а не в «Площадках». Обсуждение — это работа со
            # сроком в два рабочих дня, и спрашивают его утром, вместе с
            # лотами и очередью отдела. В «Площадках» оно лежало рядом с
            # выгрузками, куда заходят раз в неделю, — и о своём горящем
            # обсуждении человек узнавал, когда срок уже прошёл.
            group="Мой стол",
            icon="chat",
            roles=names(*REMARKS),
        ),
    ),
    jobs=jobs,
    health=health.check,
)

__all__ = ["module"]
