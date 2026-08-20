"""Контракт подключаемого проекта.

Платформа объединяет самостоятельные проекты — тендерный разбор, аналитику
SKStore и те, что появятся дальше. Каждый из них остаётся отдельным пакетом со
своим доменом, своей базой и своим CLI: платформа даёт им вход, права, очередь
задач и хранилище файлов, но не забирает их логику себе.

Соединяются они одним объявлением. Модуль отдаёт `ModuleSpec` — свои
эндпоинты, свои фоновые задачи, свои пункты меню, — а каркас сам их
подхватывает. Добавление нового проекта не должно требовать правок в каркасе:
как только для этого понадобится «ещё одно место, где перечислены модули»,
контракт перестал работать.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter

from platform_api.jobs.contract import JobSpec


@dataclass(frozen=True, slots=True)
class NavItem:
    """Пункт меню, который модуль показывает в оболочке."""

    title: str
    path: str
    icon: str | None = None

    roles: tuple[str, ...] = ()
    """Кому пункт виден. Пусто — всем, у кого есть доступ к модулю.

    Права проверяются на эндпоинтах, а не здесь: скрытый пункт меню — это
    удобство, а не защита. Прятать кнопку и оставлять открытым эндпоинт —
    самый распространённый способ отдать себестоимость наружу."""


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    """Всё, что модуль сообщает о себе платформе."""

    slug: str
    """Короткое имя: префикс путей (`/api/tender/...`) и ключ в настройках."""

    title: str
    router: APIRouter

    nav: tuple[NavItem, ...] = ()

    jobs: tuple[JobSpec, ...] = ()
    """Фоновые задачи модуля. Разбор идёт минутами и стоит денег, поэтому
    живёт в очереди, а не в обработчике запроса."""

    health: Callable[[], dict[str, Any]] | None = None
    """Проверка готовности модуля: доступ к модели, наличие реквизитов.
    Показывается в общей сводке — чтобы «почему не работает» выяснялось до
    запуска платного разбора, а не после."""

    description: str = ""


class ModuleRegistry:
    """Реестр подключённых модулей."""

    def __init__(self, modules: Sequence[ModuleSpec] = ()) -> None:
        self._modules: dict[str, ModuleSpec] = {}
        for module in modules:
            self.add(module)

    def add(self, module: ModuleSpec) -> None:
        if module.slug in self._modules:
            raise ValueError(f"Модуль «{module.slug}» уже подключён")
        self._modules[module.slug] = module

    def get(self, slug: str) -> ModuleSpec:
        try:
            return self._modules[slug]
        except KeyError:
            known = ", ".join(sorted(self._modules)) or "ни одного"
            raise KeyError(f"Модуль «{slug}» не подключён. Известные: {known}") from None

    def all(self) -> tuple[ModuleSpec, ...]:
        return tuple(self._modules.values())

    @property
    def jobs(self) -> tuple[JobSpec, ...]:
        """Все задачи всех модулей — то, что получает исполнитель очереди."""
        return tuple(job for module in self._modules.values() for job in module.jobs)

    def __len__(self) -> int:
        return len(self._modules)

    def __contains__(self, slug: object) -> bool:
        return slug in self._modules


def discover_modules() -> list[ModuleSpec]:
    """Собирает модули, которые нужно подключить.

    Пока список задан явно. Автопоиск по точкам входа выглядит красивее, но
    молча пропускает модуль, который не установился, — а «в меню нет раздела»
    гораздо труднее связать с причиной, чем упавший импорт при запуске.
    """
    from platform_api.modules.omarket import module as omarket
    from platform_api.modules.skstore import module as skstore
    from platform_api.modules.tender import module as tender

    # Порядок задаёт и порядок разделов в меню. Сверху то, с чем работают
    # каждый день: площадки обновляются сами и требуют решения к сроку, а
    # тендерная папка приходит по почте и ждёт, пока её откроют.
    return [skstore, omarket, tender]


__all__ = ["ModuleRegistry", "ModuleSpec", "NavItem", "discover_modules"]
