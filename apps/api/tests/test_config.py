"""Настройки платформы.

Проверяется то, что уронило первый живой разбор: пустая переменная в нашем
`.env` маскировала настоящий ключ из `.env` подключённого проекта.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from platform_api import config


def test_empty_values_do_not_mask_the_real_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Главное здесь.

    Проекты читают свои `.env` следом за нашим и не перезаписывают заданное.
    Пустая строка выглядит как заданное значение — и ключ, аккуратно
    прописанный в `.env` ядра, становится невидимым. Разбор падает с «доступ
    не настроен» при заполненном файле.
    """
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=\nPLATFORM__LOG_LEVEL=DEBUG\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("PLATFORM__LOG_LEVEL", raising=False)

    config.load_dotenv_into_environment()

    assert "GEMINI_API_KEY" not in os.environ
    assert os.environ["PLATFORM__LOG_LEVEL"] == "DEBUG"


def test_environment_wins_over_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Окружение старше файла: так задают настройки при запуске."""
    env = tmp_path / ".env"
    env.write_text("PLATFORM__LOG_LEVEL=DEBUG\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("PLATFORM__LOG_LEVEL", "ERROR")

    config.load_dotenv_into_environment()

    assert os.environ["PLATFORM__LOG_LEVEL"] == "ERROR"


def test_case_folders_are_absolute() -> None:
    """Относительный путь означал бы каталог рядом с местом запуска."""
    settings = config.Settings()

    assert settings.storage.root.is_absolute()
    assert settings.storage.cases_root.is_absolute()


def test_server_slushaet_tolko_svoy_kompyuter_po_umolchaniyu() -> None:
    """Сервер разработки не должен без спроса оказаться доступен всей сети:
    за ним себестоимость и маржа. В контейнере адрес задаётся явно."""
    settings = config.Settings()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8000


def test_slezhenie_za_pravkami_po_okruzheniyu() -> None:
    """Не задано — включено в разработке и выключено в бою."""
    assert config.Settings(environment="dev").reload_enabled is True
    assert config.Settings(environment="prod").reload_enabled is False


def test_slezhenie_mozhno_vyklyuchit_yavno() -> None:
    """В контейнере код не правят, а слежение держит второй процесс."""
    assert config.Settings(environment="dev", reload=False).reload_enabled is False
