"""Готовность тендерного модуля.

Проверка нужна до запуска разбора, а не после. Разбор платный, идёт минутами
и падает на первом же файле, если не настроен доступ к модели, — а человек к
этому моменту уже загрузил папку и ждёт результата.
"""

from __future__ import annotations

from typing import Any

from platform_api.logging import get_logger
from platform_api.modules.tender.core import companies, core_settings, core_version

logger = get_logger(__name__)


def check() -> dict[str, Any]:
    problems: list[str] = []

    settings = core_settings()
    provider = settings.llm.provider

    model_access = _has_model_access()
    if not model_access:
        key = "GEMINI_API_KEY" if provider == "gemini" else "ANTHROPIC_API_KEY"
        problems.append(f"Нет доступа к модели: задайте {key} в окружении")

    directory = companies()
    configured = [profile for profile in directory.profiles.values() if profile.is_configured]
    if not configured:
        problems.append("Не заполнены реквизиты компаний — КП будет не от кого отправлять")
    for profile in configured:
        if missing := profile.missing:
            problems.append(f"{profile.name}: не заполнено — {', '.join(missing)}")

    # Файловая база — для платформы неисправность, а не выбор. К ней
    # одновременно ходят почасовые прогоны и открытые страницы, а пишущий в
    # SQLite блокирует файл целиком. Молчать об этом нельзя: сломается оно не
    # сразу, а в первый час, когда работают все.
    if settings.db.url.startswith("sqlite"):
        problems.append(
            "Ядро работает с файлом SQLite, а не с общей базой — задайте TENDER__DB__URL"
        )

    return {
        "ok": not problems,
        "core_version": core_version(),
        "database": _database(settings),
        "provider": provider,
        "model_access": model_access,
        "companies_configured": len(configured),
        "problems": tuple(problems),
    }


def _database(settings: Any) -> str:
    """С какой базой работает ядро — словами, на страницу готовности.

    Не украшение: URL задаётся окружением, и забытая переменная не ломает
    ничего заметного — ядро просто продолжает писать в старое место.
    Обнаруживается это через неделю по тому, что свежих разборов нет, хотя
    прогоны отработали.
    """
    return "SQLite (файл)" if settings.db.url.startswith("sqlite") else "PostgreSQL"


def _has_model_access() -> bool:
    """Создаёт клиента ядра — этим и проверяется доступ.

    Клиент создаётся лениво и именно на этом шаге выясняет, есть ли ключ;
    сетевого запроса здесь нет, поэтому проверка бесплатна.
    """
    from tender_analyze.application.container import Container
    from tender_analyze.exceptions import ConfigurationError

    container = Container(core_settings())
    try:
        _ = container.llm_client
    except ConfigurationError:
        return False
    except Exception as exc:  # pragma: no cover — неожиданный сбой SDK
        logger.warning("Проверка доступа к модели сорвалась", error=str(exc))
        return False
    finally:
        container.dispose()
    return True
