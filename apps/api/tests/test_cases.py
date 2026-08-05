"""Закупки через HTTP.

Закупка — то, вокруг чего вращается работа тендерщика: в неё складываются
документы, по ней идёт разбор, из неё выходит наше предложение. Здесь
проверяется, что состав закупки собирается верно и что чужие документы в неё
попасть не могут.
"""

from __future__ import annotations

import uuid
from typing import Any

from conftest import FakeRedis, sign_in
from fastapi import FastAPI
from fastapi.testclient import TestClient
from platform_api.db.models import Organization, Role, StoredFile
from sqlalchemy.orm import Session as DbSession


def _stored(db: DbSession, org: Organization, name: str, digest: str) -> StoredFile:
    row = StoredFile(
        organization_id=org.id,
        sha256=digest,
        size_bytes=1024,
        original_name=name,
    )
    db.add(row)
    db.flush()
    return row


def _case(client: TestClient, title: str = "Системный блок от 27.07.2027 г") -> dict[str, Any]:
    return client.post("/api/tender/cases", json={"title": title}).json()


def test_case_is_created_with_its_folder_name(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    """Тендерщик узнаёт закупку по имени папки, а не по номеру."""
    app.state.redis = redis
    sign_in(db, app_client)

    case = _case(app_client)

    assert case["title"] == "Системный блок от 27.07.2027 г"
    assert case["status"] == "draft"
    assert case["files_count"] == 0


def test_files_land_in_the_case(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    app.state.redis = redis
    org = sign_in(db, app_client)
    first = _stored(db, org, "КП Примеро.pdf", "a" * 64)
    second = _stored(db, org, "КП.pdf", "b" * 64)
    db.commit()
    case = _case(app_client)

    body = app_client.post(
        f"/api/tender/cases/{case['id']}/files",
        json=[
            {"file_id": str(first.id), "relative_path": "КП Примеро.pdf"},
            {"file_id": str(second.id), "relative_path": "обновленные кп/КП.pdf"},
        ],
    ).json()

    assert body["files_count"] == 2
    # Подпапка сохранена: по ней ядро отличает обновлённые предложения.
    assert {item["relative_path"] for item in body["files"]} == {
        "КП Примеро.pdf",
        "обновленные кп/КП.pdf",
    }
    assert body["status"] == "ready"


def test_repeated_attach_does_not_double(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    """Браузер может прислать список дважды — при обрыве связи или повторе."""
    app.state.redis = redis
    org = sign_in(db, app_client)
    stored = _stored(db, org, "КП.pdf", "a" * 64)
    db.commit()
    case = _case(app_client)
    payload = [{"file_id": str(stored.id), "relative_path": "КП.pdf"}]

    app_client.post(f"/api/tender/cases/{case['id']}/files", json=payload)
    body = app_client.post(f"/api/tender/cases/{case['id']}/files", json=payload).json()

    assert body["files_count"] == 1


def test_foreign_file_cannot_be_attached(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    """Главное здесь.

    Идентификатор файла приходит от клиента. Без проверки принадлежности
    достаточно подставить чужой — и документ другой организации оказался бы
    в нашей закупке и в нашем разборе.
    """
    app.state.redis = redis
    stranger = Organization(name="Чужие", slug=f"other-{uuid.uuid4().hex[:6]}")
    db.add(stranger)
    db.flush()
    foreign = _stored(db, stranger, "чужое КП.pdf", "c" * 64)
    sign_in(db, app_client)
    db.commit()
    case = _case(app_client)

    response = app_client.post(
        f"/api/tender/cases/{case['id']}/files",
        json=[{"file_id": str(foreign.id), "relative_path": "чужое КП.pdf"}],
    )

    assert response.status_code == 400
    assert "не найден" in response.json()["detail"]


def test_foreign_case_is_not_found(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    """404, а не 403: иначе перебирается, какие закупки вообще существуют."""
    app.state.redis = redis
    stranger = Organization(name="Чужие", slug=f"other-{uuid.uuid4().hex[:6]}")
    db.add(stranger)
    db.flush()
    sign_in(db, app_client)
    db.commit()
    other_client_case = uuid.uuid4()

    assert app_client.get(f"/api/tender/cases/{other_client_case}").status_code == 404


def test_list_shows_only_our_own(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    app.state.redis = redis
    sign_in(db, app_client)
    _case(app_client, "Наша закупка")

    from platform_api.modules.tender.models import TenderCaseRow

    stranger = Organization(name="Чужие", slug=f"other-{uuid.uuid4().hex[:6]}")
    db.add(stranger)
    db.flush()
    db.add(TenderCaseRow(organization_id=stranger.id, title="Чужая закупка"))
    db.commit()

    titles = {item["title"] for item in app_client.get("/api/tender/cases").json()}

    assert titles == {"Наша закупка"}


def test_analysis_needs_files(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    """Пустая закупка — не повод занимать очередь и платить за разбор."""
    app.state.redis = redis
    sign_in(db, app_client)
    case = _case(app_client)

    response = app_client.post(f"/api/tender/cases/{case['id']}/analyze")

    assert response.status_code == 400
    assert "нет файлов" in response.json()["detail"]


def test_buyer_may_collect_but_not_pay(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    """Закупщик собирает документы, но платный разбор запускает тендерщик.

    Разбор стоит денег, и решение потратить их — не его.
    """
    app.state.redis = redis
    org = sign_in(db, app_client, Role.BUYER)
    stored = _stored(db, org, "КП.pdf", "a" * 64)
    db.commit()

    case = _case(app_client)
    attached = app_client.post(
        f"/api/tender/cases/{case['id']}/files",
        json=[{"file_id": str(stored.id), "relative_path": "КП.pdf"}],
    )
    assert attached.status_code == 200

    assert app_client.post(f"/api/tender/cases/{case['id']}/analyze").status_code == 403


def test_cases_require_a_session(app_client: TestClient) -> None:
    assert app_client.get("/api/tender/cases").status_code == 401
    assert app_client.post("/api/tender/cases", json={"title": "Закупка"}).status_code == 401


def test_decision_needs_analyzed_documents(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    """Решать по неразобранной закупке не по чему.

    Спросить модель наугад — это заплатить за ответ, построенный на пустоте.
    """
    app.state.redis = redis
    org = sign_in(db, app_client)
    stored = _stored(db, org, "КП.pdf", "a" * 64)
    db.commit()
    case = _case(app_client)
    app_client.post(
        f"/api/tender/cases/{case['id']}/files",
        json=[{"file_id": str(stored.id), "relative_path": "КП.pdf"}],
    )

    response = app_client.post(f"/api/tender/cases/{case['id']}/decide")

    assert response.status_code == 400
    assert "разберите" in response.json()["detail"].lower()


def test_buyer_cannot_ask_for_a_decision(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    """Решение — про деньги, и запускает его тот, кто за них отвечает."""
    from platform_api.modules.tender.models import CaseStatus, TenderCaseRow

    app.state.redis = redis
    org = sign_in(db, app_client, Role.BUYER)
    row = TenderCaseRow(organization_id=org.id, title="Закупка", status=CaseStatus.ANALYZED)
    db.add(row)
    db.commit()

    assert app_client.post(f"/api/tender/cases/{row.id}/decide").status_code == 403


def _analyzed(db: DbSession, org: Organization, title: str = "Закупка") -> Any:
    from platform_api.modules.tender.models import CaseStatus, TenderCaseRow

    row = TenderCaseRow(organization_id=org.id, title=title, status=CaseStatus.ANALYZED)
    db.add(row)
    db.commit()
    return row


def test_sourcing_needs_analyzed_documents(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    """Искать на рынках по неразобранной закупке нечего — а запросы платные."""
    app.state.redis = redis
    sign_in(db, app_client)
    case = _case(app_client)

    response = app_client.post(f"/api/tender/cases/{case['id']}/sourcing")

    assert response.status_code == 400


def test_buyer_cannot_spend_on_market_search(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    app.state.redis = redis
    org = sign_in(db, app_client, Role.BUYER)
    case = _analyzed(db, org)

    assert app_client.post(f"/api/tender/cases/{case.id}/sourcing").status_code == 403
    assert (
        app_client.post(f"/api/tender/cases/{case.id}/offer", json={"companies": []}).status_code
        == 403
    )


def test_documents_of_a_fresh_case_are_empty(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    app.state.redis = redis
    org = sign_in(db, app_client)
    case = _analyzed(db, org)

    assert app_client.get(f"/api/tender/cases/{case.id}/documents").json() == []


def test_download_refuses_to_leave_the_case(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    """Главное здесь.

    Имя файла приходит из адреса. `../../.env` в этом поле — первое, что
    пробуют, а рядом с каталогом закупки лежат чужие закупки и настройки.
    """
    app.state.redis = redis
    org = sign_in(db, app_client)
    case = _analyzed(db, org)

    for name in ("../.env", "..%2F.env", "../../companies.toml", ".hidden"):
        response = app_client.get(f"/api/tender/cases/{case.id}/documents/{name}")
        # Любой отказ годится: 400 — поймали проверкой, 404 — нет такого файла,
        # 422 — путь вообще не разобрался. Важно, что файла не отдали.
        assert response.status_code in (400, 404, 422), name
        assert not response.content.startswith(b"PLATFORM__"), name


def test_buyer_may_download_the_worksheet(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis, tmp_path: Any
) -> None:
    """Задание закупщику — его рабочий файл, прятать незачем."""
    from platform_api.modules.tender.core import core_settings
    from platform_api.modules.tender.workspace import CaseWorkspace
    from platform_api.storage import FileStorage

    app.state.redis = redis
    app.state.workspace = CaseWorkspace(tmp_path, FileStorage(tmp_path / "s", max_bytes=1024))
    org = sign_in(db, app_client, Role.BUYER)
    case = _analyzed(db, org)

    folder = app.state.workspace.path_for(case.id, case.title) / core_settings().results_dirname
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Задание_закупщику.xlsx").write_bytes(b"xlsx")

    listing = app_client.get(f"/api/tender/cases/{case.id}/documents").json()
    assert [item["kind"] for item in listing] == ["worksheet"]

    download = app_client.get(f"/api/tender/cases/{case.id}/documents/Задание_закупщику.xlsx")
    assert download.status_code == 200
    assert download.content == b"xlsx"
