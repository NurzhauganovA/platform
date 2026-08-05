"""Запуск сервера разработки: `python -m platform_api`."""

from __future__ import annotations


def main() -> None:
    import uvicorn

    from platform_api.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "platform_api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        reload=not settings.is_prod,
        # Логи настраивает structlog: свой конфиг uvicorn напечатал бы то же
        # самое вторым форматом, и читать поток стало бы нечитаемо.
        log_config=None,
    )


if __name__ == "__main__":
    main()
