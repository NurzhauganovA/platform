"""Общие приспособления тестов.

Тендерное ядро в тестах не трогается по-настоящему: у него своя база, свои
реквизиты компаний и свой ключ к модели. Тесты платформы проверяют перевод на
язык HTTP, а не разбор документов — за это отвечают тесты самого ядра.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from platform_api.app import create_app
from platform_api.config import Settings
from platform_api.db.base import Base
from platform_api.db.models import Membership, Organization, Role, User
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

TEST_DB_NAME = "fintend_test"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Отдельная база под тесты.

    Отдельная, а не рабочая: тесты заводят и удаляют учётные записи, а рабочая
    база к этому моменту содержит настоящие закупки. Схема разворачивается по
    моделям — расхождение моделей с миграциями ловит `alembic check` в общем
    прогоне, здесь это лишний десяток секунд на каждый запуск.
    """
    base = Settings().db.url
    admin_url = base.rsplit("/", 1)[0] + "/postgres"
    test_url = base.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"

    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            exists = connection.execute(
                text("select 1 from pg_database where datname = :name"),
                {"name": TEST_DB_NAME},
            ).scalar()
            if not exists:
                connection.execute(text(f'create database "{TEST_DB_NAME}"'))
    except OperationalError as exc:  # pragma: no cover — база не поднята
        pytest.skip(f"PostgreSQL недоступен: {exc}")
    finally:
        admin.dispose()

    test_engine = create_engine(test_url)
    Base.metadata.create_all(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    """Соединение с внешней транзакцией, которая откатывается после теста.

    Так тесты не видят следов друг друга, а база остаётся чистой — при этом
    внутри теста можно вызывать `commit()`, как это делает обработчик запроса.
    """
    conn = engine.connect()
    transaction = conn.begin()
    try:
        yield conn
    finally:
        transaction.rollback()
        conn.close()


@pytest.fixture
def db(connection: Connection) -> Iterator[DbSession]:
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="dev")


@pytest.fixture
def app(settings: Settings, connection: Connection) -> FastAPI:
    """Приложение, работающее в транзакции теста.

    Фабрика сессий подменяется на привязанную к тому же соединению: иначе
    запрос ходил бы в свою транзакцию и не видел данных, заведённых тестом.
    """
    application = create_app(settings)
    application.state.session_factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    return application


@pytest.fixture
def app_client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client(app_client: TestClient) -> TestClient:
    return app_client


def sign_in(db: DbSession, client: TestClient, role: Role = Role.ANALYST) -> Organization:
    """Заводит человека с ролью и кладёт его сессию в куки клиента."""
    from platform_api.auth import passwords
    from platform_api.auth.service import open_session

    org = Organization(name="Fintend", slug=f"fintend-{uuid.uuid4().hex[:6]}")
    user = User(
        email=f"{uuid.uuid4().hex[:8]}@fintend.kz",
        password_hash=passwords.hash_password("закупки-2026-каратау"),
    )
    db.add_all([org, user])
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role=role))
    db.flush()

    _, token = open_session(db, user, org, ttl_hours=12)
    db.commit()
    client.cookies.set(Settings().auth.session_cookie, token)
    return org


@pytest.fixture
def signed_in(db: DbSession, app_client: TestClient) -> Organization:
    """Клиент с сессией тендерщика — самая частая роль в тестах."""
    return sign_in(db, app_client)


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
