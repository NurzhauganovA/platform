"""Готовность модуля OMarket.

Показывается в общей сводке платформы и над рабочим списком. Смысл в том,
чтобы «почему пусто» и «почему не считается маржа» выяснялось до запуска
прогона, а не после — прогон идёт минутами и стоит денег.
"""

from __future__ import annotations

from typing import Any

from platform_api.logging import get_logger

logger = get_logger(__name__)


def check() -> dict[str, Any]:
    """Сводка о состоянии ядра OMarket.

    Не бросает исключений. Проверка готовности, падающая с ошибкой, бесполезна
    вдвойне: она и есть тот ответ, за которым человек пришёл.
    """
    from platform_api.modules.omarket import core

    try:
        return core.readiness()
    except Exception as exc:  # pragma: no cover — ядро не установилось
        logger.warning("Ядро OMarket недоступно", error=str(exc))
        return {
            "ok": False,
            "core_version": "неизвестна",
            "preorders": 0,
            "session": False,
            "market_search": False,
            "market_model": "",
            "warehouse": False,
            "problems": (f"Ядро OMarket недоступно: {exc}",),
        }


__all__ = ["check"]
