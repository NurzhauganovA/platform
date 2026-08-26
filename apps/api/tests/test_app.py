"""Каркас платформы: сводка и навигация."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from platform_api.db.models import Role
from tests.conftest import sign_in


def test_modules_describe_themselves(client: TestClient, db: Any) -> None:
    """Оболочка строит меню по этому ответу, а не по своему списку разделов."""
    sign_in(db, client, Role.ANALYST)
    modules = client.get("/api/modules").json()

    tender = next(item for item in modules if item["slug"] == "tender")
    assert tender["title"] == "Тендеры"
    # Только то, что открывается. «История цен» и «Конкуренты» в ядре есть,
    # но страниц под них пока нет, и в меню их держать нельзя: пункт, молча
    # уводящий на чужой раздел, читается как поломка входа. Заведение закупки
    # папкой убрано с глаз по той же причине наоборот: страница и эндпоинты
    # живы, но разбор пока идёт на машине тендерщика.
    assert [item["path"] for item in tender["nav"]] == [
        "/tender/worklist",
        "/tender/works",
        "/tender/analytics",
    ]


def test_health_collects_checks_from_modules(
    client: TestClient, monkeypatch: Any, offline_core: dict[str, Any]
) -> None:
    """Платформа не знает, что значит готовность тендерного разбора.

    Она спрашивает об этом сам модуль — иначе каркас пришлось бы править при
    подключении каждого нового проекта.
    """
    from platform_api.modules.tender import health as health_module

    monkeypatch.setattr(health_module, "_has_model_access", lambda: True)

    body = client.get("/api/health").json()

    assert body["environment"] == "dev"
    assert "tender" in body["modules"]
    assert body["modules"]["tender"]["provider"] in {"gemini", "anthropic"}


def test_health_is_not_ok_when_a_module_complains(
    client: TestClient, monkeypatch: Any, offline_core: dict[str, Any]
) -> None:
    """Нет доступа к модели — платформа обязана сказать это до разбора.

    Разбор идёт минутами и стоит денег, а падает на первом же файле: человек
    к этому моменту уже загрузил папку и ждёт результата.
    """
    from platform_api.modules.tender import health as health_module

    monkeypatch.setattr(health_module, "_has_model_access", lambda: False)

    body = client.get("/api/health").json()

    assert body["ok"] is False
    problems = body["modules"]["tender"]["problems"]
    assert any("доступа к модели" in problem for problem in problems)


def test_openapi_is_served(client: TestClient) -> None:
    """По схеме генерируется клиент фронтенда: закрыть её — отключить сборку."""
    schema = client.get("/api/openapi.json").json()

    assert "/api/tender/upload-plan" in schema["paths"]
