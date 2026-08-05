"""Сравнение предложений и граница по деньгам.

Здесь проходит та же граница, что уже существует в документах проекта: КП для
заказчика собирается без себестоимости, задание закупщику — с ней. Проверяется
не «отдаёт ли API данные», а то, что закупщик и наблюдатель не получают
себестоимость и маржу.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

import pytest
from conftest import FakeRedis, sign_in
from fastapi import FastAPI
from fastapi.testclient import TestClient
from platform_api.db.models import Organization, Role
from platform_api.modules.tender.models import TenderCaseRow
from sqlalchemy.orm import Session as DbSession


class FakeCase:
    """Закупка, какой её собирает ядро."""

    def __init__(self) -> None:
        self.subject = "Системные блоки"
        self.customer = None
        self.documents = (1, 2, 3)
        self.offers = (1, 2)
        self.groups = ()
        self.requested = ()
        self.requirements = ("Гарантия 36 месяцев",)
        self.risks = ("Не указаны условия оплаты",)
        self.analysis = FakeAnalysis()


class FakeAnalysis:
    recommendation = "участвовать"
    summary = "Три предложения, разброс невелик"
    comparability = "сопоставимы"
    best_offer_supplier = "ИП Сыздыкова К"
    best_offer_reason = "дешевле по трём позициям"
    estimated_cost = 2_800_000.0
    recommended_bid = 3_900_000.0
    expected_margin_percent = 28.0
    margin_reasoning = "с учётом логистики"
    blockers: ClassVar[list[str]] = ["Отсутствуют условия оплаты"]
    questions: ClassVar[list[str]] = ["Каков размер аванса?"]


class FakeView:
    def __init__(self) -> None:
        from decimal import Decimal
        from pathlib import Path

        self.case = FakeCase()
        self.vat_rate = Decimal("0.12")
        self.total_min = Decimal("4370536")
        self.total_max = Decimal("5535000")
        self.root = Path("/tmp/case")


@pytest.fixture
def analyzed_case(
    app: FastAPI, db: DbSession, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> Any:
    """Разобранная закупка, не трогающая ни ядро, ни диск."""
    app.state.redis = redis
    from platform_api.modules.tender import comparison, core

    # Обработчик импортирует функцию внутри себя, поэтому подмена в модуле
    # ядра доходит до него — и ни база разбора, ни диск не участвуют.
    monkeypatch.setattr(core, "build_case_view", lambda _row: FakeView())
    # Находки читаются из базы ядра — в этих тестах она не участвует.
    monkeypatch.setattr(comparison, "_market", lambda _view: None)
    return None


def _case(db: DbSession, org: Organization, title: str = "Системный блок") -> TenderCaseRow:
    row = TenderCaseRow(organization_id=org.id, title=title)
    db.add(row)
    db.flush()
    db.commit()
    return row


def test_analyst_sees_the_money(
    app: FastAPI, app_client: TestClient, db: DbSession, analyzed_case: Any
) -> None:
    org = sign_in(db, app_client, Role.ANALYST)
    case = _case(db, org)

    body = app_client.get(f"/api/tender/cases/{case.id}/comparison").json()

    assert body["analyzed"] is True
    assert body["decision"]["recommended_bid"] == 3_900_000.0
    assert body["decision"]["estimated_cost"] == 2_800_000.0
    assert body["decision"]["expected_margin_percent"] == 28.0


def test_buyer_does_not_see_the_money(
    app: FastAPI, app_client: TestClient, db: DbSession, analyzed_case: Any
) -> None:
    """Главное здесь.

    Закупщик работает с позициями и поставщиками. Наша отпускная цена,
    себестоимость и маржа для его работы не нужны, а уходят вместе с ним.
    """
    org = sign_in(db, app_client, Role.BUYER)
    case = _case(db, org)

    body = app_client.get(f"/api/tender/cases/{case.id}/comparison").json()

    assert body["analyzed"] is True
    # Позиции и риски видны — с ними он и работает.
    assert body["risks"] == ["Не указаны условия оплаты"]
    # А решения нет вовсе: не пустое, не обнулённое — отсутствует.
    assert body["decision"] is None


def test_viewer_does_not_see_the_money(
    app: FastAPI, app_client: TestClient, db: DbSession, analyzed_case: Any
) -> None:
    org = sign_in(db, app_client, Role.VIEWER)
    case = _case(db, org)

    response = app_client.get(f"/api/tender/cases/{case.id}/comparison")

    # Наблюдателю сравнение вообще не положено: это рабочий инструмент,
    # а не отчёт.
    assert response.status_code == 403


def test_unanalyzed_case_says_so_plainly(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    """Пустая сводка честнее выдуманной."""
    app.state.redis = redis
    org = sign_in(db, app_client, Role.ANALYST)
    case = _case(db, org, "Рабочее колесо")

    body = app_client.get(f"/api/tender/cases/{case.id}/comparison").json()

    assert body["analyzed"] is False
    assert body["positions"] == []
    assert body["decision"] is None


def test_foreign_case_is_not_found(
    app: FastAPI, app_client: TestClient, db: DbSession, redis: FakeRedis
) -> None:
    app.state.redis = redis
    stranger = Organization(name="Чужие", slug=f"other-{uuid.uuid4().hex[:6]}")
    db.add(stranger)
    db.flush()
    foreign = _case(db, stranger)
    sign_in(db, app_client, Role.ANALYST)

    assert app_client.get(f"/api/tender/cases/{foreign.id}/comparison").status_code == 404


def test_comparison_requires_a_session(app_client: TestClient) -> None:
    assert app_client.get(f"/api/tender/cases/{uuid.uuid4()}/comparison").status_code == 401
