"""Права на эндпоинтах.

Граница между ролями здесь не абстрактная: она повторяет ту, что уже
существует в документах проекта. КП для заказчика собирается без
себестоимости, задание закупщику — с ней. В вебе то же самое должно держаться
на правах, а не на том, что человек не открыл соседний адрес.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from platform_api.auth import passwords
from platform_api.auth.dependencies import requires_admin, requires_money, requires_sourcing
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

    @router.get("/admin", dependencies=[requires_admin])
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


def test_fail_prava_vstroennyh_roley_sovpadayut_s_prezhnimi_naborami() -> None:
    """Перевод ролей на права ничего не раздал и ничего не отобрал.

    Раньше каждая проверка перечисляла роли. Теперь роль — это набор прав, а
    проверка спрашивает право; словарь `BUILT_IN` — перевод прежних наборов на
    новый язык, и любое расхождение здесь означает, что кто-то молча получил
    доступ к себестоимости или его потерял.

    Проверяется в обе стороны: и что право есть у тех, у кого было, и что его
    нет у остальных. Односторонняя проверка пропустила бы самое дорогое —
    лишнее право у лишней роли.
    """
    from platform_api.auth.dependencies import CRM, MONEY, READS, REMARKS, SOURCING
    from platform_api.auth.permissions import BUILT_IN, Permission

    было: dict[Permission, tuple[Role, ...]] = {
        Permission.MONEY: MONEY,
        Permission.READ: READS,
        Permission.SOURCING: SOURCING,
        Permission.REMARKS: REMARKS,
        Permission.CRM: CRM,
    }
    for право, набор in было.items():
        стало = {role for role in Role if право in BUILT_IN[role]}
        assert стало == set(набор), f"{право} разошлось: было {set(набор)}, стало {стало}"

    # Решение об участии: менеджер, руководитель, коммерческий и администратор.
    решают = {role for role in Role if Permission.DECIDE in BUILT_IN[role]}
    assert решают == {Role.ADMIN, Role.MANAGER, Role.HEAD, Role.COMMERCIAL}

    # Подписи: одна роль — одна подпись, плюс администратор.
    from platform_api.db.models import ApprovalKind
    from platform_api.modules.cards import SIGNS

    пары = {
        ApprovalKind.MANAGER: Permission.SIGN_MANAGER,
        ApprovalKind.SUPPLY: Permission.SIGN_SUPPLY,
        ApprovalKind.LEGAL: Permission.SIGN_LEGAL,
        ApprovalKind.TECHNOLOGIST: Permission.SIGN_TECHNOLOGIST,
        ApprovalKind.ASSEMBLER: Permission.SIGN_ASSEMBLER,
    }
    for kind, право in пары.items():
        стало = {role for role in Role if право in BUILT_IN[role]}
        assert стало == set(SIGNS[kind]), f"{kind} разошлась: {стало} против {set(SIGNS[kind])}"


def test_fail_u_kazhdogo_prava_est_imya_i_poyasnenie() -> None:
    """Право без имени показалось бы человеку как «sign.technologist».

    Список прав человек видит на экране роли и по нему решает, что выдать.
    Строка вида `money` там означает, что выдавать будут наугад.
    """
    from platform_api.auth.permissions import PERMISSION_ABOUT, PERMISSION_NAMES, Permission

    assert all(право in PERMISSION_NAMES for право in Permission)
    assert all(право in PERMISSION_ABOUT for право in Permission)
    assert all(PERMISSION_NAMES[право].strip() for право in Permission)


def test_fail_lyudi_i_roli_tolko_administratoru(db: DbSession, app_client: TestClient) -> None:
    """За экраном людей почты сотрудников и право выдать себе любое из прав.

    Вопрос «кто может видеть себестоимость» задаёт не тот, кому её не
    показывают.
    """
    from tests.conftest import sign_in

    sign_in(db, app_client, Role.MANAGER)
    db.commit()

    assert app_client.get("/api/people").status_code == 403
    assert app_client.get("/api/people/roles").status_code == 403
    assert app_client.post("/api/people/roles", json={"key": "x", "title": "X"}).status_code == 403


def test_fail_svoya_rol_daet_prava_i_zabiraet_lishnie(
    db: DbSession, app_client: TestClient
) -> None:
    """Своя роль отвечает за доступ целиком, а не добавляет к встроенной.

    Иначе «роль без цен» оставляла бы цены от прежней роли — то есть не
    делала бы ровно того, ради чего её заводят.
    """
    from tests.conftest import sign_in

    org = sign_in(db, app_client, Role.ADMIN)
    db.commit()

    заведена = app_client.post(
        "/api/people/roles",
        json={
            "key": "supply_no_money",
            "title": "Снабженец без цен",
            "description": "Ищет товар, цен не видит",
            "permissions": ["crm", "sourcing", "нет-такого-права"],
        },
    )
    assert заведена.status_code == 201, заведена.text
    # Неизвестное право молча отброшено: список закрыт кодом, и выдать
    # несуществующее нельзя.
    assert заведена.json()["permissions"] == ["crm", "sourcing"]

    человек = app_client.post(
        "/api/people",
        json={
            "email": "supply@fintend.kz",
            "full_name": "Снабженец",
            "role": "supply_no_money",
            "password": "закупки-2026-каратау",
        },
    )
    assert человек.status_code == 201, человек.text
    assert человек.json()["role_title"] == "Снабженец без цен"

    # Входим им самим и проверяем, что права именно те.
    app_client.post("/api/auth/logout")
    вход = app_client.post(
        "/api/auth/login",
        json={"email": "supply@fintend.kz", "password": "закупки-2026-каратау"},
    )
    assert вход.status_code == 200, вход.text

    assert app_client.get("/api/cards").status_code == 200
    # Себестоимости у роли нет — и раздел с ней закрыт.
    assert app_client.get("/api/skstore/export").status_code == 403
    # Людьми управлять тоже нельзя: право администратора не выдавали.
    assert app_client.get("/api/people").status_code == 403
    del org


def test_fail_zanyatuyu_rol_ne_ubirayut(db: DbSession, app_client: TestClient) -> None:
    """Удалённая роль молча оставила бы человека с правами наблюдателя.

    Он приходит утром, не находит своих разделов и идёт выяснять, что
    сломалось. Сначала переводят людей, потом убирают роль.
    """
    from tests.conftest import sign_in

    sign_in(db, app_client, Role.ADMIN)
    db.commit()

    app_client.post(
        "/api/people/roles",
        json={"key": "trainee", "title": "Стажёр", "permissions": ["read"]},
    )
    app_client.post(
        "/api/people",
        json={
            "email": "trainee@fintend.kz",
            "role": "trainee",
            "password": "закупки-2026-каратау",
        },
    )

    отказ = app_client.delete("/api/people/roles/trainee")

    assert отказ.status_code == 409
    assert "Переведите" in отказ.json()["detail"]


def test_fail_u_vstroennoy_roli_pravyatsya_tolko_prava(
    db: DbSession, app_client: TestClient
) -> None:
    """Название встроенной роли не меняется.

    По нему роль узнают в переписке и в журнале действий: «Тендерщик» под
    другим именем — это уже другая роль, и заводят её рядом.
    """
    from tests.conftest import sign_in

    sign_in(db, app_client, Role.ADMIN)
    db.commit()

    отказ = app_client.patch("/api/people/roles/analyst", json={"title": "Аналитик"})

    assert отказ.status_code == 409
    assert "только права" in отказ.json()["detail"]


def test_fail_sebya_ne_vyklyuchayut(db: DbSession, app_client: TestClient) -> None:
    """Администратор, оставшийся без прав, их себе не вернёт — а другого в
    маленькой компании может не быть вовсе."""
    from tests.conftest import sign_in

    org = sign_in(db, app_client, Role.ADMIN)
    я = app_client.get("/api/auth/me").json()
    db.commit()

    отказ = app_client.delete(f"/api/people/{я['id']}")
    смена = app_client.patch(f"/api/people/{я['id']}", json={"role": "viewer"})

    assert отказ.status_code == 409
    assert смена.status_code == 409
    del org


def test_fail_udalennyy_chelovek_ne_unosit_istoriyu(db: DbSession, app_client: TestClient) -> None:
    """Запись удалили — подпись и лента остались, и с именем.

    «Кто это одобрил» спрашивают через полгода, когда закупка вышла в убыток, и
    человек к тому времени мог уйти. Имя лежит копией рядом со ссылкой: ссылка
    при удалении обнуляется, а имя нет.
    """
    from decimal import Decimal

    from platform_api.db.models import ApprovalKind, ApprovalState
    from platform_api.modules import cards
    from tests.conftest import sign_in

    org = sign_in(db, app_client, Role.ADMIN)
    db.commit()

    завели = app_client.post(
        "/api/people",
        json={
            "email": "uhodit@fintend.kz",
            "full_name": "Ушёл Уволившийся",
            "role": "manager",
            "password": "закупки-2026-каратау",
        },
    )
    assert завели.status_code == 201, завели.text
    кто = uuid.UUID(завели.json()["id"])

    card = cards.open_card(
        db,
        organization_id=org.id,
        module="goszakup",
        row_id="лот-с-подписью",
        snapshot=cards.Snapshot(code="GZ777", title="Компьютеры", amount=Decimal("1000")),
        by=кто,
    )
    cards.sign(
        db,
        organization_id=org.id,
        card_id=card.id,
        role=Role.MANAGER,
        user_id=кто,
        kind=ApprovalKind.MANAGER,
        state=ApprovalState.APPROVED,
    )
    db.commit()

    убрали = app_client.delete(f"/api/people/{кто}?purge=true")
    assert убрали.status_code == 204, убрали.text
    assert app_client.get("/api/people").json() != []

    показ = app_client.get(f"/api/cards/{card.id}").json()
    подпись = next(one for one in показ["approvals"] if one["kind"] == "manager")
    assert подпись["state"] == "approved"
    assert подпись["by"] == "Ушёл Уволившийся"

    лента = app_client.get(f"/api/cards/{card.id}/history").json()
    assert any(item["actor"] == "Ушёл Уволившийся" for item in лента["events"])
    # Лот остался, но стал ничьим: вести его больше некому, и это правда.
    assert показ["owner"] == ""


def test_fail_poslednego_administratora_ne_udalyayut(db: DbSession, app_client: TestClient) -> None:
    """Платформа без администратора остаётся без управления доступами, и
    вернуть их можно только руками в базе."""
    from tests.conftest import sign_in

    sign_in(db, app_client, Role.ADMIN)
    я = app_client.get("/api/auth/me").json()
    другой = app_client.post(
        "/api/people",
        json={
            "email": "vtoroy@fintend.kz",
            "role": "admin",
            "password": "закупки-2026-каратау",
        },
    )
    assert другой.status_code == 201, другой.text
    db.commit()

    # Второго администратора удалить можно: первый остаётся.
    assert app_client.delete(f"/api/people/{другой.json()['id']}?purge=true").status_code == 204
    # А себя — нет, и не потому что «себя», а потому что последнего.
    отказ = app_client.delete(f"/api/people/{я['id']}?purge=true")
    assert отказ.status_code == 409


def test_fail_zanyatuyu_rol_ubirayut_tolko_naprosheno(
    db: DbSession, app_client: TestClient
) -> None:
    """Роль носят люди — по умолчанию отказываем и называем число.

    Люди на ней остаются в платформе и получают права наблюдателя: человек
    приходит утром, не находит своих разделов и идёт выяснять, что сломалось.
    Решает администратор: перевести их самому или снять роль вместе со всеми.
    """
    from tests.conftest import sign_in

    sign_in(db, app_client, Role.ADMIN)
    db.commit()

    app_client.post(
        "/api/people/roles",
        json={"key": "podryad", "title": "Подрядчик", "permissions": ["crm"]},
    )
    человек = app_client.post(
        "/api/people",
        json={
            "email": "podryad@fintend.kz",
            "role": "podryad",
            "password": "закупки-2026-каратау",
        },
    )
    assert человек.status_code == 201, человек.text

    отказ = app_client.delete("/api/people/roles/podryad")
    assert отказ.status_code == 409
    assert "1 чел" in отказ.json()["detail"]

    убрали = app_client.delete("/api/people/roles/podryad?force=true")
    assert убрали.status_code == 204

    # Человек остался в платформе и стал наблюдателем.
    остался = next(
        one for one in app_client.get("/api/people").json() if one["email"] == "podryad@fintend.kz"
    )
    assert остался["role"] == "viewer"
    assert остался["is_active"] is True


def test_fail_prava_vstroennoy_roli_pravyatsya_i_vozvrashchayutsya(
    db: DbSession, app_client: TestClient
) -> None:
    """«Тендерщик без аналитики» — настройка, а не новая роль.

    Заводить рядом копию из десяти галочек ради снятия одной значит держать два
    списка и однажды поправить только один. Заводские права при этом остаются в
    коде: правка лежит накладкой, и «вернуть как было» — это её удаление.
    """
    from tests.conftest import sign_in

    sign_in(db, app_client, Role.ADMIN)
    db.commit()

    было = next(
        one for one in app_client.get("/api/people/roles").json() if one["key"] == "analyst"
    )
    assert "page.tender_analytics" in было["permissions"]
    assert было["changed"] is False

    без_аналитики = [право for право in было["permissions"] if право != "page.tender_analytics"]
    правка = app_client.patch("/api/people/roles/analyst", json={"permissions": без_аналитики})
    assert правка.status_code == 200, правка.text
    assert "page.tender_analytics" not in правка.json()["permissions"]
    assert правка.json()["changed"] is True

    назад = app_client.post("/api/people/roles/analyst/reset")
    assert назад.status_code == 200, назад.text
    assert "page.tender_analytics" in назад.json()["permissions"]
    assert назад.json()["changed"] is False


def test_fail_sebya_ne_zapirayut_pravkoy_roli(db: DbSession, app_client: TestClient) -> None:
    """Администратор без управления платформой не вернёт его себе.

    И последней роли с этим правом его тоже не снять: платформа осталась бы без
    управления доступами вовсе.
    """
    from tests.conftest import sign_in

    sign_in(db, app_client, Role.ADMIN)
    db.commit()

    своя = app_client.patch("/api/people/roles/admin", json={"permissions": ["page.lots"]})
    assert своя.status_code == 409
    assert "своей роли" in своя.json()["detail"]


def test_fail_menyu_sobiraetsya_po_pravam(db: DbSession, app_client: TestClient) -> None:
    """Пункт без права не показывается, и правка роли это сразу меняет.

    Пункт меню — удобство, а не защита: эндпоинт за ним под своей проверкой.
    Но пункт, ведущий в отказ, человек нажимает один раз и перестаёт верить
    всему меню.
    """
    from tests.conftest import sign_in

    sign_in(db, app_client, Role.ADMIN)
    db.commit()

    пути = {
        пункт["path"] for модуль in app_client.get("/api/modules").json() for пункт in модуль["nav"]
    }
    assert "/work/people" in пути
    assert "/skstore/analytics" in пути

    # Права приходят браузеру, чтобы он не рисовал кнопок, отвечающих отказом.
    я = app_client.get("/api/auth/me").json()
    assert "admin" in я["permissions"]
    assert я["role_title"] == "Администратор"
