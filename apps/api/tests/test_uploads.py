"""Загрузка файлов.

Два предмета проверки. Первый — что мы не верим клиенту: хэш он считает сам,
и подменённое содержимое не должно занять чужое место в хранилище. Второй —
что план загрузки не превращается в способ добраться до чужих документов.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from platform_api.auth import passwords
from platform_api.auth.service import open_session
from platform_api.config import Settings
from platform_api.db.models import Membership, Organization, Role, StoredFile, User
from platform_api.storage import ChecksumMismatchError, FileStorage, FileTooLargeError
from sqlalchemy.orm import Session as DbSession

PASSWORD = "закупки-2026-каратау"
# Байты, а не текст: хранилище работает с содержимым файла, и кириллица в нём
# должна пережить дорогу до диска и обратно.
PDF = "%PDF-1.4 КП Примеро".encode()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _member(db: DbSession, role: Role = Role.ANALYST) -> tuple[User, Organization]:
    org = Organization(name="Fintend", slug=f"fintend-{uuid.uuid4().hex[:6]}")
    user = User(
        email=f"{uuid.uuid4().hex[:8]}@fintend.kz",
        password_hash=passwords.hash_password(PASSWORD),
    )
    db.add_all([org, user])
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role=role))
    db.flush()
    return user, org


def _sign_in(db: DbSession, client: TestClient, role: Role = Role.ANALYST) -> Organization:
    user, org = _member(db, role)
    _, token = open_session(db, user, org, ttl_hours=12)
    db.commit()
    client.cookies.set(Settings().auth.session_cookie, token)
    return org


# --- хранилище ------------------------------------------------------------


def test_content_is_laid_out_by_hash(tmp_path: Path) -> None:
    """Два уровня подкаталогов: иначе в одном окажутся десятки тысяч файлов."""
    storage = FileStorage(tmp_path, max_bytes=1024)

    saved = storage.save(io.BytesIO(PDF), expected_sha256=_digest(PDF))

    assert saved.path.exists()
    assert saved.path.relative_to(tmp_path).parts[:2] == (saved.sha256[:2], saved.sha256[2:4])


def test_same_content_is_stored_once(tmp_path: Path) -> None:
    """В тендерных папках один образец МЗ встречается в пяти папках."""
    storage = FileStorage(tmp_path, max_bytes=1024)
    storage.save(io.BytesIO(PDF), expected_sha256=_digest(PDF))

    again = storage.save(io.BytesIO(PDF), expected_sha256=_digest(PDF))

    assert again.already_existed
    assert len(list(tmp_path.rglob("*"))) == 3  # два каталога и один файл


def test_forged_hash_is_refused(tmp_path: Path) -> None:
    """Главное здесь.

    Хэш считает клиент. Тот, кто подменит содержимое под чужой хэш, положит
    свой файл на место чужого — и дальше его получит каждый, кто запросит
    оригинал.
    """
    storage = FileStorage(tmp_path, max_bytes=1024)

    with pytest.raises(ChecksumMismatchError):
        storage.save(io.BytesIO("подделка".encode()), expected_sha256=_digest(PDF))

    # И ничего не осталось на диске: ни под правильным именем, ни обрывком.
    assert list(tmp_path.rglob("*.part")) == []
    assert not storage.exists(_digest(PDF))


def test_oversized_file_is_refused(tmp_path: Path) -> None:
    storage = FileStorage(tmp_path, max_bytes=10)
    payload = b"x" * 100

    with pytest.raises(FileTooLargeError):
        storage.save(io.BytesIO(payload), expected_sha256=_digest(payload))

    assert list(tmp_path.rglob("*.part")) == []


def test_saved_file_reads_back(tmp_path: Path) -> None:
    storage = FileStorage(tmp_path, max_bytes=1024)
    storage.save(io.BytesIO(PDF), expected_sha256=_digest(PDF))

    assert b"".join(storage.read_chunks(_digest(PDF))) == PDF


# --- через HTTP -----------------------------------------------------------


def test_upload_requires_a_session(app_client: TestClient) -> None:
    response = app_client.post(
        "/api/tender/files",
        data={"sha256": _digest(PDF), "relative_path": "КП.pdf"},
        files={"file": ("КП.pdf", PDF, "application/pdf")},
    )

    assert response.status_code == 401


def test_upload_stores_the_file(
    app: FastAPI, app_client: TestClient, db: DbSession, tmp_path: Path
) -> None:
    app.state.storage = FileStorage(tmp_path, max_bytes=1024 * 1024)
    org = _sign_in(db, app_client)

    response = app_client.post(
        "/api/tender/files",
        data={"sha256": _digest(PDF), "relative_path": "обновленные кп/КП.pdf"},
        files={"file": ("КП.pdf", PDF, "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["sha256"] == _digest(PDF)
    assert body["relative_path"] == "обновленные кп/КП.pdf"

    stored = db.scalars(
        StoredFile.__table__.select().where(StoredFile.organization_id == org.id)  # type: ignore[arg-type]
    ).all()
    assert len(stored) == 1


def test_upload_with_wrong_hash_is_refused(
    app: FastAPI, app_client: TestClient, db: DbSession, tmp_path: Path
) -> None:
    app.state.storage = FileStorage(tmp_path, max_bytes=1024 * 1024)
    _sign_in(db, app_client)

    response = app_client.post(
        "/api/tender/files",
        data={"sha256": _digest(PDF), "relative_path": "КП.pdf"},
        files={"file": ("КП.pdf", "совсем другое содержимое".encode(), "application/pdf")},
    )

    assert response.status_code == 400


# --- план загрузки --------------------------------------------------------


def _probe(name: str, data: bytes = PDF) -> dict[str, object]:
    return {
        "name": name,
        "relative_path": name,
        "size_bytes": len(data),
        "sha256": _digest(data),
    }


def test_plan_skips_our_own_uploads(
    app_client: TestClient, db: DbSession, offline_core: dict[str, object]
) -> None:
    org = _sign_in(db, app_client)
    db.add(
        StoredFile(
            organization_id=org.id, sha256=_digest(PDF), size_bytes=len(PDF), original_name="КП.pdf"
        )
    )
    db.commit()

    plan = app_client.post("/api/tender/upload-plan", json=[_probe("КП.pdf")]).json()

    assert plan["skipped_known"] == 1
    assert plan["to_upload"] == 0


def test_plan_does_not_reveal_other_organizations(
    app_client: TestClient, db: DbSession, offline_core: dict[str, object]
) -> None:
    """Главное здесь.

    Файл загружен другой организацией. Если ответить «уже есть, грузить не
    надо», чужой документ окажется прикреплён к нашей закупке — достаточно
    знать его хэш. Хэш не угадывают, но он попадает в ссылки, логи и
    выгрузки, а тендерные папки ходят между людьми.
    """
    _stranger, other_org = _member(db)
    db.add(
        StoredFile(
            organization_id=other_org.id,
            sha256=_digest(PDF),
            size_bytes=len(PDF),
            original_name="чужое КП.pdf",
        )
    )
    db.flush()
    _sign_in(db, app_client)

    plan = app_client.post("/api/tender/upload-plan", json=[_probe("КП.pdf")]).json()

    assert plan["skipped_known"] == 0
    assert plan["to_upload"] == 1


def test_plan_marks_already_paid_analysis(
    app_client: TestClient, db: DbSession, offline_core: dict[str, object]
) -> None:
    """Разбор такого содержимого оплачен: файл грузим, а денег он не стоит."""
    known: set[str] = offline_core["known"]  # type: ignore[assignment]
    known.add(_digest(PDF))
    _sign_in(db, app_client)

    plan = app_client.post("/api/tender/upload-plan", json=[_probe("КП.pdf")]).json()

    assert plan["to_upload"] == 1
    assert plan["already_analyzed"] == 1
    assert plan["files"][0]["analysis_cached"] is True


def test_plan_requires_a_session(app_client: TestClient) -> None:
    assert app_client.post("/api/tender/upload-plan", json=[]).status_code == 401


def test_viewer_cannot_upload(
    app_client: TestClient, db: DbSession, offline_core: dict[str, object]
) -> None:
    """Наблюдатель смотрит отчёты, а не пополняет закупки документами."""
    _sign_in(db, app_client, Role.VIEWER)

    assert app_client.post("/api/tender/upload-plan", json=[]).status_code == 403
