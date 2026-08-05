"""Тендерный модуль через HTTP.

Главное здесь — план загрузки. Он решает, что поедет по сети и за что мы
заплатим при разборе, и ошибка в нём стоит либо лишних гигабайт трафика,
либо повторной оплаты уже сделанной работы.
"""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi.testclient import TestClient


def _probe(name: str, *, folder: str = "", size: int = 1024, content: str | None = None) -> dict:
    relative = f"{folder}/{name}" if folder else name
    digest = hashlib.sha256((content or relative).encode()).hexdigest()
    return {
        "name": name,
        "relative_path": relative,
        "size_bytes": size,
        "sha256": digest,
    }


def test_companies_are_listed_with_their_gaps(
    client: TestClient, offline_core: dict[str, Any]
) -> None:
    """Недостающий БИН должен всплыть при выборе компании, а не в готовом КП."""
    response = client.get("/api/tender/companies")

    assert response.status_code == 200
    companies = {item["key"]: item for item in response.json()}
    assert companies["fintend"]["is_default"] is True
    assert companies["fintend"]["missing"] == []
    assert companies["ac_master"]["missing"] == ["БИН"]


def test_formats_tell_what_will_be_read(client: TestClient) -> None:
    response = client.get("/api/tender/formats")

    formats = {item["extension"]: item for item in response.json()}
    assert formats[".pdf"]["supported"] is True
    assert formats[".docx"]["supported"] is True
    # Архив сам по себе не документ: разбирается его содержимое.
    assert formats[".zip"]["is_container"] is True


def test_unreadable_formats_are_filtered_out(
    client: TestClient, signed_in: object, offline_core: dict[str, Any]
) -> None:
    """В тендерных папках лежат и видео, и служебный мусор macOS."""
    plan = client.post(
        "/api/tender/upload-plan",
        json=[_probe("ТЗ.pdf"), _probe("видео.mp4", size=500_000), _probe(".DS_Store", size=6148)],
    ).json()

    assert plan["to_upload"] == 1
    assert plan["skipped_unsupported"] == 2
    # Ни байта неподдерживаемых файлов в счёт загрузки не попало.
    assert plan["upload_bytes"] == 1024


def test_subfolders_survive_the_plan(
    client: TestClient, signed_in: object, offline_core: dict[str, Any]
) -> None:
    """«обновленные кп» — отдельная папка внутри закупки, и это важно.

    Структура каталога определяет состав закупок, и если сложить всё в одну
    кучу, обновлённые предложения смешаются с прежними.
    """
    plan = client.post(
        "/api/tender/upload-plan",
        json=[_probe("КП.pdf"), _probe("КП.pdf", folder="обновленные кп")],
    ).json()

    paths = {item["relative_path"] for item in plan["files"]}
    assert paths == {"КП.pdf", "обновленные кп/КП.pdf"}
    assert plan["to_upload"] == 2


def test_empty_plan_is_not_an_error(
    client: TestClient, signed_in: object, offline_core: dict[str, Any]
) -> None:
    """Выбрали пустую папку — это ответ, а не пятисотка."""
    plan = client.post("/api/tender/upload-plan", json=[]).json()

    assert plan == {
        "files": [],
        "total": 0,
        "to_upload": 0,
        "upload_bytes": 0,
        "skipped_known": 0,
        "skipped_unsupported": 0,
        "already_analyzed": 0,
    }


def test_broken_hash_is_refused(client: TestClient, signed_in: object) -> None:
    """Хэш считает браузер, и присланному значению верить нельзя."""
    response = client.post(
        "/api/tender/upload-plan",
        json=[{"name": "КП.pdf", "relative_path": "КП.pdf", "size_bytes": 10, "sha256": "нет"}],
    )

    assert response.status_code == 422
