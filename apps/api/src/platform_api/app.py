"""Сборка приложения.

Каркас не знает, какие проекты к нему подключены: он берёт их из реестра
модулей и монтирует то, что они о себе объявили. Всё, что специфично для
тендеров или SKStore, живёт в их модулях — здесь только общее.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from platform_api.config import Settings, get_settings
from platform_api.logging import configure_logging, get_logger
from platform_api.modules import ModuleRegistry, discover_modules

logger = get_logger(__name__)


class ModuleOut(BaseModel):
    """Модуль так, как его видит оболочка интерфейса."""

    slug: str
    title: str
    description: str = ""
    nav: list[dict[str, Any]] = []


class HealthOut(BaseModel):
    ok: bool
    environment: str
    modules: dict[str, Any] = {}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)
    registry = ModuleRegistry(discover_modules())

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "Платформа запущена",
            environment=settings.environment,
            modules=[module.slug for module in registry.all()],
        )
        yield
        logger.info("Платформа остановлена")

    app = FastAPI(
        title="Fintend",
        description="Платформа тендерного отдела: разбор документации и наши предложения",
        version="0.1.0",
        lifespan=lifespan,
        # Схема отдаётся всегда: по ней генерируется клиент фронтенда, и
        # закрывать её значит отключать сборку интерфейса.
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        # Вход по куке, поэтому браузеру нужно разрешение слать её с запросом.
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = APIRouter(prefix="/api")

    @api.get("/health", summary="Готовность платформы", tags=["Платформа"])
    def health() -> HealthOut:
        """Сводка по всем модулям.

        Собирается из их собственных проверок: платформа не знает, что значит
        готовность тендерного разбора, и спрашивает об этом сам модуль.
        """
        checks = {
            module.slug: module.health() for module in registry.all() if module.health is not None
        }
        return HealthOut(
            ok=all(bool(check.get("ok")) for check in checks.values()),
            environment=settings.environment,
            modules=checks,
        )

    @api.get("/modules", summary="Подключённые проекты", tags=["Платформа"])
    def modules() -> list[ModuleOut]:
        """То, из чего оболочка строит навигацию."""
        return [
            ModuleOut(
                slug=module.slug,
                title=module.title,
                description=module.description,
                nav=[
                    {"title": item.title, "path": item.path, "icon": item.icon}
                    for item in module.nav
                ],
            )
            for module in registry.all()
        ]

    for module in registry.all():
        api.include_router(module.router)

    app.include_router(api)
    app.state.modules = registry
    app.state.settings = settings
    return app
