"""Окружение Alembic.

Адрес базы берётся из настроек платформы, а не из `alembic.ini`: иначе он был
бы записан в двух местах и однажды разошёлся бы — с последствиями вида
«миграция применена не к той базе».
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from platform_api.config import get_settings
from platform_api.db import models  # noqa: F401 — регистрация таблиц
from platform_api.db.base import Base
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Без импорта моделей выше автогенерация видела бы пустую схему и предлагала
# удалить всё, что есть в базе.
config.set_main_option("sqlalchemy.url", get_settings().db.url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Изменение типа колонки — тоже изменение схемы, и пропускать его
            # молча нельзя: «строка стала длиннее» замечают на бою.
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
