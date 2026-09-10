"""Права на эндпоинтах.

Граница между ролями здесь не абстрактная: она повторяет ту, что уже
существует в документах проекта. КП для заказчика собирается без
себестоимости, задание закупщику — с ней. В вебе то же самое должно держаться
на правах, а не на том, что человек не открыл соседний адрес.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from platform_api.auth import passwords
from platform_api.auth.dependencies import require_roles, requires_money, requires_sourcing
from platform_api.auth.service import open_session
from platform_api.config import Settings
from platform_api.db.models import Membership, Organization, Role, User
from sqlalchemy.orm import Session as DbSession

PASSWORD = "закупки-2026-каратау"


@pytest.fixture
def guarded_app(app: FastAPI) -> FastAPI:
    """Приложение с эндпоинтами под каждую из готовых проверок."""
    router = APIRouter(prefix="/api/probe")

    @router.get("/money", dependencies=[requires_money])
    def money() -> dict[str, str]:
        return {"маржа": "30.5%"}

    @router.get("/sourcing", dependencies=[requires_sourcing])
    def sourcing() -> dict[str, str]:
        return {"поставщик": "eco-service.kz"}

    @router.get("/admin", dependencies=[Depends(require_roles())])
    def admin() -> dict[str, str]:
        return {"ключ": "настройки"}

    app.include_router(router)
    return app


def _login(db: DbSession, client: TestClient, role: Role) -> User:
    org = Organization(name="Fintend", slug=f"fintend-{uuid.uuid4().hex[:6]}")
    user = User(
        email=f"{role.value}-{uuid.uuid4().hex[:6]}@fintend.kz",
        password_hash=passwords.hash_password(PASSWORD),
    )
    db.add_all([org, user])
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role=role))
    db.flush()

    _, token = open_session(db, user, org, ttl_hours=12)
    db.commit()
    client.cookies.set(Settings().auth.session_cookie, token)
    return user


@pytest.mark.parametrize(
    ("role", "money", "sourcing", "admin"),
    [
        (Role.ADMIN, 200, 200, 200),
        (Role.ANALYST, 200, 200, 403),
        (Role.BUYER, 403, 200, 403),
        (Role.VIEWER, 403, 403, 403),
    ],
)
def test_roles_see_only_their_own(
    guarded_app: FastAPI,
    db: DbSession,
    role: Role,
    money: int,
    sourcing: int,
    admin: int,
) -> None:
    """Закупщик не видит маржу, наблюдатель не видит поставщиков.

    Ключевая строка таблицы — вторая с конца: закупщик работает с целевой
    ценой закупа и поставщиками, но нашей отпускной цены и маржи не видит.
    Для его работы они не нужны, а уходят вместе с ним.
    """
    with TestClient(guarded_app) as client:
        _login(db, client, role)

        assert client.get("/api/probe/money").status_code == money
        assert client.get("/api/probe/sourcing").status_code == sourcing
        assert client.get("/api/probe/admin").status_code == admin


def test_without_session_everything_is_closed(guarded_app: FastAPI) -> None:
    """Незваный получает 401, а не 403: разница видна и в логах, и в интерфейсе."""
    with TestClient(guarded_app) as client:
        for path in ("/api/probe/money", "/api/probe/sourcing", "/api/probe/admin"):
            assert client.get(path).status_code == 401


def test_roles_are_matched_by_set_not_by_seniority(guarded_app: FastAPI, db: DbSession) -> None:
    """Иерархия ролей подтолкнула бы написать «не ниже закупщика».

    Тогда закупщик получил бы доступ к марже, которую ему видеть не
    полагается. Проверка идёт по набору, и этот тест закрепляет именно это.
    """
    with TestClient(guarded_app) as client:
        _login(db, client, Role.BUYER)

        assert client.get("/api/probe/sourcing").status_code == 200
        assert client.get("/api/probe/money").status_code == 403


def test_fail_proverki_prav_podklyucheny_cherez_depends(app: FastAPI) -> None:
    """Проверка прав без `Depends` не выполняется вовсе.

    FastAPI принимает такую за обычный параметр запроса: роль не проверяется, а
    `_guard` вылезает в схеме API отдельным полем. Ошибка тихая — эндпоинт
    отвечает, тесты на нужные роли проходят, — и находится только тогда, когда
    список ролей сузили, а доступ остался у всех.

    Проверяется по схеме, а не по коду: так ловится любой модуль, включая те,
    которых ещё нет.
    """
    schema = app.openapi()
    протекло = [
        f"{method.upper()} {path}"
        for path, methods in schema["paths"].items()
        for method, operation in methods.items()
        if any(item["name"].startswith("_") for item in operation.get("parameters", []))
    ]
    assert not протекло, "Проверка прав подключена без Depends — она не выполняется: " + ", ".join(
        протекло
    )


def test_fail_kazhdaya_rol_vidit_svoyo(db: DbSession, app_client: TestClient) -> None:
    """Матрица доступа целиком, а не по одной роли за тест.

    Ролей десять, и права им раздавались по мере появления: шесть новых
    завели под согласование и не вписали в `requires_read`. Менеджер поставки
    — тот, кто ведёт лот от объявления до оплаты, — не видел ни одного
    рабочего списка. Ошибка тихая: каждый отдельный тест на своей роли
    проходил.

    Здесь перечислено ожидаемое поведение целиком. Меняется набор ролей —
    правится эта таблица, и расхождение видно сразу.
    """
    открыто = 200
    закрыто = 403
    ожидаем: dict[Role, dict[str, int]] = {
        # Ведёт лот и решает об участии: нужны и списки, и цифры.
        Role.MANAGER: {
            "/api/goszakup/worklist": открыто,
            "/api/cards": открыто,
            "/api/jobs": открыто,
        },
        # Считает себестоимость. Работал и раньше.
        Role.ANALYST: {
            "/api/goszakup/worklist": открыто,
            "/api/cards": открыто,
            "/api/remarks": открыто,
        },
        # Ищет товар. Маржи не видит, но список и карточка нужны.
        Role.BUYER: {
            "/api/goszakup/worklist": открыто,
            "/api/cards": открыто,
            "/api/remarks": закрыто,
        },
        # Пишет замечания. За списками цены — туда не пускаем.
        Role.LAWYER: {
            "/api/goszakup/worklist": закрыто,
            "/api/cards": открыто,
            "/api/remarks": открыто,
        },
        # Подтверждают товар и сроки. Работают с карточки, список им не нужен.
        Role.TECHNOLOGIST: {"/api/goszakup/worklist": закрыто, "/api/cards": открыто},
        Role.ASSEMBLER: {"/api/goszakup/worklist": закрыто, "/api/cards": открыто},
        # Решают, когда цифры спорные.
        Role.HEAD: {"/api/goszakup/worklist": открыто, "/api/cards": открыто},
        Role.COMMERCIAL: {"/api/goszakup/worklist": открыто, "/api/cards": открыто},
        # Смотрит отчёты. Карточка — стол с задачами, не отчёт.
        Role.VIEWER: {"/api/goszakup/worklist": открыто, "/api/cards": закрыто},
    }

    разошлось: list[str] = []
    for роль, адреса in ожидаем.items():
        _login(db, app_client, роль)
        for адрес, ждём in адреса.items():
            было = app_client.get(адрес).status_code
            if было != ждём:
                разошлось.append(f"{роль.value} {адрес}: ждали {ждём}, получили {было}")

    assert not разошлось, "Права разошлись с ТЗ: " + "; ".join(разошлось)


def test_fail_obhod_portala_zapuskayut_te_zhe_kto_chitayet(
    db: DbSession, app_client: TestClient
) -> None:
    """Кнопка «Обновить» на лотах портала — всем, кому открыт раздел.

    Обход бесплатен: открытое API портала не требует ни токена, ни ЭЦП, и
    модель в нём не участвует. Ждать тендерщика ради свежего списка незачем —
    объявление вешают посреди дня, а у запроса ценовых предложений на подачу
    двое суток.

    Закрыт он ровно от тех, кому закрыт сам список: кнопка, доступная тому,
    кто не видит результата, — это расход запросов к государственному порталу
    без единого читателя.
    """
    можно = 202
    нельзя = 403
    ожидаем = {
        Role.MANAGER: можно,
        Role.ANALYST: можно,
        Role.BUYER: можно,
        Role.HEAD: можно,
        Role.COMMERCIAL: можно,
        Role.LAWYER: нельзя,
        Role.TECHNOLOGIST: нельзя,
        Role.ASSEMBLER: нельзя,
    }

    разошлось: list[str] = []
    for роль, ждём in ожидаем.items():
        _login(db, app_client, роль)
        было = app_client.post("/api/goszakup/sync").status_code
        if было != ждём:
            разошлось.append(f"{роль.value}: ждали {ждём}, получили {было}")

    assert not разошлось, "Права на обход разошлись: " + "; ".join(разошлось)


def test_fail_udalyat_loty_mozhet_tolko_administrator(
    db: DbSession, app_client: TestClient
) -> None:
    """Очистка раздела — только администратору, и остальным отказ.

    Действие необратимо: вместе с лотами уходят карточки, задачи, обсуждения
    и устойчивые коды. Тендерщик и руководитель видят раздел и правят цифры,
    но стереть работу пяти отделов — не то право, которое даётся заодно с
    доступом к ценам.

    Проверяется и просмотр объёма: он показывает, сколько чего заведено по
    госзакупкам, и это тоже не для всех.
    """
    отказ = 403
    for роль in (Role.MANAGER, Role.ANALYST, Role.BUYER, Role.HEAD, Role.COMMERCIAL):
        _login(db, app_client, роль)
        assert app_client.delete("/api/goszakup/lots").status_code == отказ, роль.value
        assert app_client.get("/api/goszakup/purge").status_code == отказ, роль.value


def test_fail_vklyuchit_kod_mozhet_tolko_administrator(
    db: DbSession, app_client: TestClient
) -> None:
    """Возврат кода в обход — того же права, что и выключение.

    Иначе получилось бы, что выключить код может только администратор, а
    включить обратно — кто угодно: список кодов задаёт, что вообще попадёт в
    отбор, и открытая половина этой пары обходит закрытую.
    """
    _login(db, app_client, Role.MANAGER)
    ответ = app_client.put("/api/goszakup/codes/262011.100.000000/active")
    assert ответ.status_code == 403


def _без_servisa(client: TestClient) -> None:
    """Гасит адрес сервиса у собранного приложения.

    На машине разработчика `.env` обычно заполнен, и проверка «сервис не
    настроен» без этого уходила бы в настоящую сеть за настоящим отказом —
    то есть проверяла бы связь с чужой машиной, а не свою ветку кода.
    """
    client.app.state.settings.notify.url = ""  # type: ignore[attr-defined]


def test_fail_uvedomleniya_tolko_administratoru(db: DbSession, app_client: TestClient) -> None:
    """За экраном уведомлений почты всех сотрудников и то, кто что себе
    отключил. Вопрос «почему Ивану не приходит» задаёт не Иван."""
    from tests.conftest import sign_in

    sign_in(db, app_client, Role.MANAGER)
    db.commit()

    assert app_client.get("/api/notify").status_code == 403
    assert app_client.get("/api/notify/people").status_code == 403
    assert app_client.post("/api/notify/sync").status_code == 403


def test_fail_bez_servisa_ekran_govorit_chto_ne_nastroeno(
    db: DbSession, app_client: TestClient
) -> None:
    """Сервис не настроен — это рабочее состояние, а не поломка.

    У разработчика он обычно не поднят, и экран должен сказать об этом словами,
    а не отдать пятисотую: администратор, увидевший ошибку, идёт чинить то,
    чего не делают намеренно.
    """
    from tests.conftest import sign_in

    sign_in(db, app_client, Role.ADMIN)
    db.commit()
    _без_servisa(app_client)

    ответ = app_client.get("/api/notify")

    assert ответ.status_code == 200, ответ.text
    сводка = ответ.json()
    assert сводка["configured"] is False
    assert сводка["reachable"] is False
    assert "PLATFORM__NOTIFY__URL" in сводка["trouble"]
    # Сколько людей у нас — считается всегда: это половина ответа на вопрос,
    # доехал ли реестр.
    assert сводка["people_here"] >= 1


def test_fail_vygruzka_bez_servisa_otkazyvaet_slovami(
    db: DbSession, app_client: TestClient
) -> None:
    """Кнопка «Выгрузить сотрудников» без настроенного сервиса не делает вид,
    что сработала: молчаливый успех отправил бы администратора искать причину
    в сервисе, которого нет."""
    from tests.conftest import sign_in

    sign_in(db, app_client, Role.ADMIN)
    db.commit()
    _без_servisa(app_client)

    ответ = app_client.post("/api/notify/sync")

    assert ответ.status_code == 409, ответ.text
