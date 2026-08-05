"""Общие приспособления тестов.

Тендерное ядро в тестах не трогается по-настоящему: у него своя база, свои
реквизиты компаний и свой ключ к модели. Тесты платформы проверяют перевод на
язык HTTP, а не разбор документов — за это отвечают тесты самого ядра.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from platform_api.app import create_app
from platform_api.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="dev")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def offline_core(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Отвязывает модуль от настоящих реквизитов и базы ядра.

    Без этого тесты зависели бы от того, что лежит в `companies.toml` и в
    базе разработчика: сегодня три компании, завтра одна — и падают тесты,
    к которым это отношения не имеет.
    """
    from platform_api.modules.tender import core
    from tender_analyze.config import CompanyDirectory, CompanyProfile

    directory = CompanyDirectory(
        default="fintend",
        profiles={
            "fintend": CompanyProfile(
                key="fintend",
                name="ТОО «Fintend»",
                bin="130540008049",
                address="г. Алматы",
                phone="+7 727 000 00 00",
                director="Иванов И.И.",
            ),
            "ac_master": CompanyProfile(
                key="ac_master",
                name="ТОО «АСМастер»",
                address="г. Шымкент",
                phone="+7 700 000 00 00",
                director="Адихаов Т.Ә.",
                notes="БИН не заполнен",
            ),
        },
    )
    known: set[str] = set()

    monkeypatch.setattr(core, "companies", lambda: directory)
    monkeypatch.setattr(core, "known_hashes", lambda hashes: {h for h in hashes if h in known})
    return {"directory": directory, "known": known}
