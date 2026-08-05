"""Контракт подключения проектов.

Проверяется то, ради чего платформа и затевалась: новый проект добавляется
объявлением, а не правками в каркасе.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from platform_api.modules import ModuleRegistry, ModuleSpec, NavItem


def _module(slug: str = "demo", **overrides: object) -> ModuleSpec:
    defaults: dict[str, object] = {
        "slug": slug,
        "title": "Демо",
        "router": APIRouter(prefix=f"/{slug}"),
    }
    return ModuleSpec(**{**defaults, **overrides})  # type: ignore[arg-type]


def test_registry_keeps_declaration_order() -> None:
    """Порядок задаёт меню, и он не должен зависеть от словарей."""
    registry = ModuleRegistry([_module("tender"), _module("skstore")])

    assert [module.slug for module in registry.all()] == ["tender", "skstore"]


def test_duplicate_slug_is_refused() -> None:
    """Два модуля с одним префиксом молча перекрыли бы эндпоинты друг друга."""
    registry = ModuleRegistry([_module("tender")])

    with pytest.raises(ValueError, match="уже подключён"):
        registry.add(_module("tender"))


def test_unknown_module_names_the_known_ones() -> None:
    registry = ModuleRegistry([_module("tender")])

    with pytest.raises(KeyError, match="tender"):
        registry.get("тендеры")


def test_jobs_are_collected_from_all_modules() -> None:
    """Исполнитель очереди получает задачи всех модулей одним списком."""

    def analyze() -> None: ...

    def sourcing() -> None: ...

    def sync() -> None: ...

    registry = ModuleRegistry(
        [
            _module("tender", jobs=(analyze, sourcing)),
            _module("skstore", jobs=(sync,)),
        ]
    )

    assert set(registry.jobs) == {analyze, sourcing, sync}


def test_nav_item_roles_are_not_an_access_check() -> None:
    """Роли в пункте меню — про удобство, а не про доступ.

    Тест закрепляет намерение: `NavItem.roles` ничего не проверяет. Прятать
    кнопку и оставлять открытым эндпоинт — самый распространённый способ
    отдать себестоимость наружу, и полагаться на это поле нельзя.
    """
    item = NavItem(title="Закупки", path="/tender/cases", roles=("analyst",))

    assert item.roles == ("analyst",)
    assert not hasattr(item, "check")
