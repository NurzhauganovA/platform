"""Готовность модуля госзакупок.

Главное, о чём говорит сводка, — пуст ли список кодов. Обход идёт строго по
нему, и с пустым списком он честно не найдёт ничего; понять это по нулю в
таблице нельзя, а по сводке можно.
"""

from __future__ import annotations

from typing import Any

from platform_api.modules.goszakup import core


def check() -> dict[str, Any]:
    problems: list[str] = []
    try:
        found = core.worklist()
    except Exception as exc:
        return {
            "ok": False,
            "core_version": core.core_version(),
            "problems": [f"База госзакупок недоступна: {exc}"],
        }

    settings = core.core_settings()
    database = "PostgreSQL" if not settings.db.is_sqlite else "SQLite (файл)"
    if settings.db.is_sqlite:
        # К этой базе одновременно ходят почасовые обходы и открытые страницы,
        # а пишущий в SQLite блокирует файл целиком: читатель получает
        # «database is locked» ровно в тот час, когда работают все.
        problems.append("База — файловый SQLite: задайте GOSZAKUP__DB__URL на PostgreSQL")
    if not found.codes:
        problems.append(
            "Список кодов ЕНС ТРУ пуст — обход не найдёт ничего. "
            "Добавьте коды в настройках парсинга"
        )
    if not found.total:
        problems.append("Лотов в базе нет — запустите обновление")

    return {
        "ok": not problems,
        "core_version": core.core_version(),
        "database": database,
        "lots": found.total,
        "codes": found.codes,
        "harvested_at": found.harvested_at,
        "problems": problems,
    }
