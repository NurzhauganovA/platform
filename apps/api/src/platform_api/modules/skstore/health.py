"""Готовность модуля SKStore.

Показывается в общей сводке платформы и над рабочим списком. Смысл в том,
чтобы «почему пусто» и «почему не считается маржа» выяснялось до запуска
прогона, а не после — прогон идёт минутами и стоит денег.
"""

from __future__ import annotations

from typing import Any

from platform_api.logging import get_logger

logger = get_logger(__name__)


def check() -> dict[str, Any]:
    """Сводка о состоянии ядра SKStore.

    Не бросает исключений. Проверка готовности, падающая с ошибкой, бесполезна
    вдвойне: она и есть тот ответ, за которым человек пришёл.
    """
    from platform_api.modules.skstore import core

    try:
        return core.readiness()
    except Exception as exc:  # pragma: no cover — ядро не установилось
        logger.warning("Ядро SKStore недоступно", error=str(exc))
        return {
            "ok": False,
            "core_version": "неизвестна",
            "bargains": 0,
            "market_search": False,
            "market_model": "",
            "warehouse": False,
            "problems": (f"Ядро SKStore недоступно: {exc}",),
        }


__all__ = ["check"]
