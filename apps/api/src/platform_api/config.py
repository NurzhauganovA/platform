"""Настройки платформы.

Читаются из окружения и файла `.env` с префиксом `PLATFORM__`. Вложенность —
двойным подчёркиванием: `PLATFORM__DB__URL` попадает в `settings.db.url`.

Префикс свой, отличный от `TENDER__`: платформа и подключённые к ней проекты
настраиваются раздельно. Иначе смена, скажем, каталога выгрузок в тендерном
модуле молча меняла бы поведение всей платформы.

Ключи провайдеров моделей здесь намеренно не дублируются: их читают SDK самих
проектов из окружения. Хранить их ещё и в настройках — лишний путь утечки
в лог или в repr.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[4]
"""Корень монорепо: `apps/api/src/platform_api/config.py` → четыре уровня вверх."""


class DatabaseSettings(BaseModel):
    url: str = "postgresql+psycopg://fintend:fintend@localhost:5432/fintend"
    echo: bool = False

    pool_size: int = Field(default=10, ge=1)
    max_overflow: int = Field(default=20, ge=0)


class RedisSettings(BaseModel):
    url: str = "redis://localhost:6379/0"


class AuthSettings(BaseModel):
    """Вход в платформу.

    Сессии в httpOnly-куке, а не токен в localStorage: токен, доступный
    скриптам страницы, крадётся любой найденной XSS, и тогда чужой человек
    видит наши закупки, себестоимость и маржу.
    """

    secret_key: str = ""
    """Ключ подписи сессий. Пустой в разработке — генерируется на запуск,
    и все сессии слетают при перезапуске. В бою обязателен."""

    session_cookie: str = "fintend_session"
    session_ttl_hours: int = Field(default=12, ge=1)
    secure_cookies: bool = False
    """В бою — обязательно `true`: иначе кука уходит по открытому HTTP."""


class StorageSettings(BaseModel):
    """Хранилище загруженных файлов.

    Раскладка по sha256, как и кэш разбора: один и тот же файл в трёх закупках
    хранится один раз. В тендерных папках дубликаты — норма, а не исключение.
    """

    # Значения по умолчанию тоже прогоняются через валидаторы. Без этого
    # относительный путь остаётся неразвёрнутым, и веб с исполнителем,
    # запущенные из разных каталогов, работают с разными папками: файл,
    # загруженный через браузер, при разборе просто не находится.
    model_config = ConfigDict(validate_default=True)

    root: Path = Path("storage")

    cases_root: Path = Path("storage/cases")
    """Каталоги закупок. Файлы попадают туда жёсткими ссылками на
    хранилище: содержимое лежит один раз, а в каталоге видно под своим
    именем — ядру нужна обычная папка, как на диске у тендерщика."""

    max_upload_mb: float = Field(default=64.0, gt=0)
    """Потолок на один файл. Совпадает с порогом обхода в тендерном ядре:
    крупнее в тендерных папках лежат архивы и видео, а не документы."""

    @field_validator("root", "cases_root")
    @classmethod
    def _absolute(cls, value: Path) -> Path:
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="PLATFORM__",
        env_nested_delimiter="__",
        extra="ignore",
        validate_default=True,
    )

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)

    environment: Literal["dev", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["console", "json"] = "console"

    cors_origins: tuple[str, ...] = ("http://localhost:5173",)
    """Откуда пускаем фронтенд. По умолчанию — дев-сервер Vite."""

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"


def load_dotenv_into_environment() -> None:
    """Подхватывает `.env` в переменные окружения процесса.

    Свои настройки платформа читает через pydantic-settings, но ключи моделей
    (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`) ищут сами SDK подключённых
    проектов — и смотрят они именно в окружение. Без этого ключ, аккуратно
    записанный в `.env`, оставался бы для них невидимым.

    Уже заданные переменные не перезаписываются: окружение старше файла.

    Пустые значения не выставляются вовсе, и это не мелочь. Подключённые
    проекты читают свои `.env` следом за нашим, тоже не перезаписывая
    заданное, — и пустая строка здесь оказывается «уже заданным значением».
    Ключ, аккуратно прописанный в `.env` ядра, становится невидимым, а разбор
    падает с «доступ не настроен» при заполненном файле.
    """
    import os

    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    from dotenv import dotenv_values

    for name, value in dotenv_values(env_file).items():
        if value and name not in os.environ:
            os.environ[name] = value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Настройки читаются один раз за процесс."""
    load_dotenv_into_environment()
    return Settings()
