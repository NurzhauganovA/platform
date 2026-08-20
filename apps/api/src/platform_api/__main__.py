"""Запуск сервера: `python -m platform_api`.

Один и тот же вход и на своей машине, и в контейнере. Адрес, порт и слежение
за правками задаются настройками: второй способ запускать сервер однажды
разошёлся бы с первым — и выяснилось бы это на бою.
"""

from __future__ import annotations


def main() -> None:
    import uvicorn

    from platform_api.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "platform_api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=settings.reload_enabled,
        # Логи настраивает structlog: свой конфиг uvicorn напечатал бы то же
        # самое вторым форматом, и читать поток стало бы нечитаемо.
        log_config=None,
    )


if __name__ == "__main__":
    main()
