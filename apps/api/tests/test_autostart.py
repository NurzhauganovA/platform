"""Взятие лота в работу запускает обсуждение и разбор само.

Проверяется то, что стоит денег: оба прогона идут к модели, и лишний — это
оплаченный дважды разбор одной спецификации. Поэтому здесь про повторы, а не
про то, что задача вообще ставится: второе нажатие кнопки, вторая вкладка,
второй человек на том же лоте — три обычных случая, и каждый не должен стоить
ничего.

Сам поход к модели не делается: проверяются задачи в очереди, а не их работа.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest
from platform_api.config import Settings
from platform_api.db.base import utcnow
from platform_api.db.models import (
    Discussion,
    DiscussionStage,
    DiscussionWriting,
    Job,
    JobStatus,
    Organization,
    SpecSheet,
    User,
)
from platform_api.modules import cards
from platform_api.modules.goszakup import start
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DbSession

ЛОТ = "87767340-ЗЦП1"


def _модуль_задач() -> Any:
    """Сам модуль задач, а не одноимённый набор из пакета.

    В `goszakup/__init__.py` имя `jobs` занято набором объявлений, и обычный
    импорт приносит его, а не модуль: подменять в нём нечего.
    """
    from importlib import import_module

    return import_module("platform_api.modules.goszakup.jobs")


@pytest.fixture
def org(db: DbSession) -> Organization:
    found = Organization(name="Fintend", slug=f"fintend-{uuid.uuid4().hex[:6]}")
    db.add(found)
    db.flush()
    return found


@pytest.fixture
def кто(db: DbSession) -> uuid.UUID:
    found = User(email=f"{uuid.uuid4().hex[:8]}@fintend.kz", password_hash="x")
    db.add(found)
    db.flush()
    return found.id


@pytest.fixture
def лот(db: DbSession, org: Organization, кто: uuid.UUID) -> Any:
    """Карточка лота портала — то, что заводит кнопка «Взять в работу»."""
    return cards.open_card(
        db,
        organization_id=org.id,
        module="goszakup",
        row_id=ЛОТ,
        snapshot=cards.Snapshot(code="GZ000042", title="Сервер", deadline=utcnow()),
        by=кто,
    )


@pytest.fixture
def спецификация(monkeypatch: pytest.MonkeyPatch) -> None:
    """У лота есть текст спецификации.

    Подменяется поход в базу портала: она живёт у подключённого ядра, а
    проверяем мы здесь платформу.
    """
    monkeypatch.setattr(
        _модуль_задач(), "spec_of", lambda _lot: ("Процессор: не менее 8 ядер", "spec.pdf")
    )


@pytest.fixture
def обсуждение(db: DbSession, org: Organization) -> Discussion:
    """Обсуждение уже заведено: заведение идёт через ядро портала, а нам нужно
    только то, что делает с ним автозапуск."""
    found = Discussion(
        organization_id=org.id,
        module="goszakup",
        row_id=ЛОТ,
        code="GZ000042",
        title="Сервер",
        stage=DiscussionStage.DRAFTING,
        writing=DiscussionWriting.READY,
        text="",
    )
    db.add(found)
    db.flush()
    return found


def _задачи(db: DbSession, org: Organization, kind: str) -> list[Job]:
    return list(
        db.execute(select(Job).where(Job.organization_id == org.id, Job.kind == kind)).scalars()
    )


def test_разбор_ставится_один_раз(
    db: DbSession,
    org: Organization,
    кто: uuid.UUID,
    лот: Any,
    обсуждение: Discussion,
    спецификация: None,
) -> None:
    """Второе нажатие «Взять в работу» не стоит второго разбора.

    Кнопку нажимают дважды — из списка и из карточки, — а карточку открывают с
    двух машин. Каждый лишний прогон это деньги и минута работы модели, которую
    ждёт кто-то другой.
    """
    settings = Settings(environment="dev")

    первый = start.on_take(db, card=лот, user_id=кто, settings=settings, redis=None)
    второй = start.on_take(db, card=лот, user_id=кто, settings=settings, redis=None)

    assert len(_задачи(db, org, "sheet")) == 1
    assert первый != ()
    assert второй == () or all(job not in первый for job in второй)


def test_разбор_не_ставится_без_спецификации(
    db: DbSession,
    org: Organization,
    кто: uuid.UUID,
    лот: Any,
    обсуждение: Discussion,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """У большинства лотов портала спецификации нет вовсе.

    Задача на пустом тексте честно напишет «раскладывать нечего» — но напишет
    это в списке прогонов, рядом с настоящей работой, и через неделю по нему не
    отличить сделанное от пустого.
    """
    monkeypatch.setattr(_модуль_задач(), "spec_of", lambda _lot: ("", ""))

    start.on_take(db, card=лот, user_id=кто, settings=Settings(environment="dev"), redis=None)

    assert _задачи(db, org, "sheet") == []


def test_разбор_не_ставится_поверх_собранного(
    db: DbSession,
    org: Organization,
    кто: uuid.UUID,
    лот: Any,
    обсуждение: Discussion,
    спецификация: None,
) -> None:
    """Таблица уже собрана — пересборка затёрла бы её вместе с правками людей.

    Пересобрать можно кнопкой «Разобрать заново»: там это осознанное действие,
    а здесь — побочное следствие второго нажатия «Взять в работу».
    """
    db.add(
        SpecSheet(
            organization_id=org.id,
            module="goszakup",
            row_id=ЛОТ,
            columns=[],
            rows=[{"key": "r1", "cells": {"demand": "Ядер не менее 8"}}],
        )
    )
    db.flush()

    start.on_take(db, card=лот, user_id=кто, settings=Settings(environment="dev"), redis=None)

    assert _задачи(db, org, "sheet") == []


def test_идущий_разбор_виден_снаружи(
    db: DbSession,
    org: Organization,
    кто: uuid.UUID,
    лот: Any,
    обсуждение: Discussion,
    спецификация: None,
) -> None:
    """Прогон, начатый автозапуском, должен быть виден тому, кто его не начинал.

    Человек взял два лота разом и открыл второй: разбор первого идёт, но его
    нажатие помнит только чужая вкладка. Без этого он видит пустую таблицу и
    жмёт «Разобрать» ещё раз — второй прогон поверх идущего.
    """
    from platform_api.modules.goszakup.start import _running_sheet

    start.on_take(db, card=лот, user_id=кто, settings=Settings(environment="dev"), redis=None)

    running = _running_sheet(db, лот)
    assert running is not None
    assert running.status is JobStatus.QUEUED
