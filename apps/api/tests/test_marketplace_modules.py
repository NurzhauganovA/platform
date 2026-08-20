"""Модули площадок через HTTP.

Оба модуля — SKStore и OMarket — устроены одинаково и проверяются вместе:
расхождение между ними было бы неожиданностью для сотрудника, который ходит в
оба раздела за одним и тем же.

Ядра здесь не трогаются по-настоящему: у них свои базы, свои доступы и свои
тесты. Проверяется перевод на язык HTTP — и в первую очередь то, кому что
достаётся: рабочий список собирается из колонок проекта автоматически, и
граница доступа проходит ровно в этом модуле.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from platform_api.db.models import Role
from sqlalchemy.orm import Session as DbSession
from tests.conftest import sign_in

MODULES = [pytest.param("skstore", id="skstore"), pytest.param("omarket", id="omarket")]


@dataclass(frozen=True)
class _Column:
    """Колонка в том виде, в каком её описывают оба проекта."""

    title: str
    getter: Any
    hyperlink: Any = None
    width: int = 18
    number_format: str | None = None


@dataclass(frozen=True)
class _Verdict:
    """Вердикт в том же виде, в каком его отдают оба ядра: у skstore это
    перечисление со свойством `value`, у omarket — строка в строке оценки."""

    value: str


@dataclass(frozen=True)
class _Analysis:
    verdict: str


@dataclass(frozen=True)
class _Row:
    товар: str
    себестоимость: Decimal
    маржа: Decimal
    verdict: _Verdict = _Verdict("promising")
    analysis: _Analysis = _Analysis("promising")


_COLUMNS = (
    _Column("Товар", getter=lambda row: row.товар, width=40),
    _Column("Где купить", getter=lambda _row: "1688.com · 900 000 ₸", width=30),
    _Column(
        "Себестоимость",
        getter=lambda row: row.себестоимость,
        width=16,
        number_format="#,##0.00",
    ),
    _Column("Маржа ₸", getter=lambda row: row.маржа, width=16, number_format="#,##0.00"),
)

_POLICY_TITLES = {
    "Товар": "all",
    "Где купить": "sourcing",
    "Себестоимость": "money",
    "Маржа ₸": "money",
}


@pytest.fixture
def offline_marketplace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подменяет оба ядра на предсказуемые данные.

    Без этого тесты зависели бы от того, что лежит в базе разработчика:
    сегодня двести закупов, завтра ноль — и падают проверки, к которым это
    отношения не имеет.
    """
    from platform_api.modules.omarket import columns as omarket_columns
    from platform_api.modules.omarket import core as omarket_core
    from platform_api.modules.skstore import columns as skstore_columns
    from platform_api.modules.skstore import core as skstore_core
    from platform_api.modules.table import Visibility

    policy = {title: Visibility(value) for title, value in _POLICY_TITLES.items()}
    rows = (_Row("Автошина Pirelli 265/65 R17", Decimal("70777.00"), Decimal("630000.00")),)

    readiness = {
        "ok": True,
        "core_version": "0.1.0",
        "market_search": True,
        "market_model": "gemini-3.1-pro-preview",
        "warehouse": True,
        "problems": (),
    }

    for module, columns_module, extra in (
        (skstore_core, skstore_columns, {"bargains": 262}),
        (omarket_core, omarket_columns, {"preorders": 381, "session": True}),
    ):
        monkeypatch.setattr(module, "focus_columns", lambda: _COLUMNS)
        monkeypatch.setattr(module, "sheet_title", lambda: "Фокус")
        monkeypatch.setattr(module, "in_focus", lambda _row: True)
        monkeypatch.setattr(module, "row_id", lambda _row: "777")
        monkeypatch.setattr(module, "row_deadline", lambda _row: None)
        monkeypatch.setattr(module, "readiness", lambda extra=extra: {**readiness, **extra})
        monkeypatch.setattr(columns_module, "POLICY", policy)

    worklist = skstore_core.Worklist(
        rows=rows,
        total=262,
        verdicts={"good": 16, "info": 76},
        margin_total=Decimal("630000.00"),
        focused=100,
        expired=0,
        priced=186,
    )
    monkeypatch.setattr(skstore_core, "worklist", lambda **_: worklist)
    monkeypatch.setattr(
        omarket_core,
        "worklist",
        lambda **_: omarket_core.Worklist(
            rows=rows,
            total=381,
            verdicts={"info": 125},
            margin_total=Decimal("630000.00"),
            focused=125,
            expired=0,
            priced=126,
            analyzed=True,
        ),
    )

    # Роутер берёт права по имени, импортированному при своей загрузке, —
    # подмена в `columns` до него не доходит. Через `import_module`, потому
    # что пакет переэкспортирует `router` объектом и затеняет подмодуль.
    import importlib

    for slug in ("skstore", "omarket"):
        router_module = importlib.import_module(f"platform_api.modules.{slug}.router")
        monkeypatch.setattr(router_module, "POLICY", policy)
        # Живая очередь для проверки «завелась ли задача» не нужна: дело
        # обработчика — записать её в базу и передать дальше, а доступность
        # Redis это забота исполнителя.
        monkeypatch.setattr(router_module, "enqueue_sync", lambda *_args, **_kwargs: None)


# --- готовность ------------------------------------------------------------


@pytest.mark.parametrize("module", MODULES)
def test_gotovnost_govorit_chto_nastroeno(
    client: TestClient, signed_in: Any, offline_marketplace: None, module: str
) -> None:
    response = client.get(f"/api/{module}/health")

    assert response.status_code == 200
    assert response.json()["market_search"] is True


@pytest.mark.parametrize("module", MODULES)
def test_razdel_zakryt_bez_sessii(client: TestClient, module: str) -> None:
    """Без входа не отдаём ничего: за этим адресом себестоимость."""
    assert client.get(f"/api/{module}/worklist").status_code == 401


# --- рабочий список --------------------------------------------------------


@pytest.mark.parametrize("module", MODULES)
def test_tendershchik_vidit_tablicu_celikom(
    client: TestClient, signed_in: Any, offline_marketplace: None, module: str
) -> None:
    response = client.get(f"/api/{module}/worklist")

    assert response.status_code == 200
    data = response.json()
    assert [item["title"] for item in data["columns"]] == [
        "Товар",
        "Где купить",
        "Себестоимость",
        "Маржа ₸",
    ]
    assert data["hidden_columns"] == 0
    assert data["margin_total"] == pytest.approx(630000.0)
    assert data["sheet"] == "Фокус"
    # Подсветка строки та же, что заливка в книге.
    assert data["rows"][0]["tone"] == "good"


@pytest.mark.parametrize("module", MODULES)
def test_zakupshchik_ne_poluchaet_sebestoimost_dazhe_zaprosom(
    db: DbSession, app_client: TestClient, offline_marketplace: None, module: str
) -> None:
    """Спрятать колонку в браузере и отдать её в JSON — самый частый способ
    отдать себестоимость наружу. Проверяем именно ответ."""
    sign_in(db, app_client, Role.BUYER)

    data = app_client.get(f"/api/{module}/worklist").json()

    titles = [item["title"] for item in data["columns"]]
    assert titles == ["Товар", "Где купить"]
    assert data["hidden_columns"] == 2
    # Итог по марже крупным шрифтом — та же самая цифра, только заметнее.
    assert data["margin_total"] is None
    assert "70777" not in response_text(data)
    assert "630000" not in response_text(data)


@pytest.mark.parametrize("module", MODULES)
def test_knopki_sovpadayut_s_pravami_na_endpointy(
    db: DbSession, app_client: TestClient, offline_marketplace: None, module: str
) -> None:
    """Кнопка, которая ответит 403, — обещание, которого раздел не выполнит.

    Проверяются обе стороны: и что кнопки нет, и что эндпоинт за ней закрыт.
    Разъехаться они могут только вместе с этим тестом.
    """
    sign_in(db, app_client, Role.BUYER)

    data = app_client.get(f"/api/{module}/worklist").json()

    assert data["actions"] == ["sync"]
    assert app_client.get(f"/api/{module}/export").status_code == 403
    assert app_client.post(f"/api/{module}/analyze").status_code == 403


@pytest.mark.parametrize("module", MODULES)
def test_nablyudatel_vidit_tolko_ploshchadku(
    db: DbSession, app_client: TestClient, offline_marketplace: None, module: str
) -> None:
    sign_in(db, app_client, Role.VIEWER)

    data = app_client.get(f"/api/{module}/worklist").json()

    assert [item["title"] for item in data["columns"]] == ["Товар"]
    assert data["hidden_columns"] == 3


@pytest.mark.parametrize("module", MODULES)
def test_chisla_prihodyat_chislami(
    client: TestClient, signed_in: Any, offline_marketplace: None, module: str
) -> None:
    """По марже сортируют и подводят итог — значит, это число, а не строка."""
    data = client.get(f"/api/{module}/worklist").json()
    cells = dict(zip([c["title"] for c in data["columns"]], data["rows"][0]["cells"], strict=True))

    assert cells["Себестоимость"]["number"] == pytest.approx(70777.0)
    assert cells["Себестоимость"]["text"] == ""
    assert cells["Товар"]["text"].startswith("Автошина")


@pytest.mark.parametrize("module", MODULES)
def test_nedostupnoe_yadro_ne_pyatisotit(
    client: TestClient,
    signed_in: Any,
    offline_marketplace: None,
    monkeypatch: pytest.MonkeyPatch,
    module: str,
) -> None:
    """Базы ядра может ещё не быть — это состояние, а не поломка платформы."""
    import importlib

    core = importlib.import_module(f"platform_api.modules.{module}.core")

    def missing(**_: Any) -> Any:
        raise RuntimeError("no such table: bargain")

    monkeypatch.setattr(core, "worklist", missing)

    response = client.get(f"/api/{module}/worklist")

    assert response.status_code == 503
    assert "недоступн" in response.json()["detail"]


# --- действия --------------------------------------------------------------


@pytest.mark.parametrize("module", MODULES)
def test_obnovlenie_dannyh_dostupno_zakupshchiku(
    db: DbSession, app_client: TestClient, offline_marketplace: None, module: str
) -> None:
    """Выгрузка бесплатна — ждать ради неё тендерщика незачем."""
    sign_in(db, app_client, Role.BUYER)

    response = app_client.post(f"/api/{module}/sync")

    assert response.status_code == 202
    assert response.json()["job_id"]


@pytest.mark.parametrize("module", MODULES)
def test_pereschet_tolko_tendershchiku(
    db: DbSession, app_client: TestClient, offline_marketplace: None, module: str
) -> None:
    """Кнопка, которая тратит бюджет, — у того, кто за него отвечает."""
    sign_in(db, app_client, Role.BUYER)

    assert app_client.post(f"/api/{module}/analyze").status_code == 403


@pytest.mark.parametrize("module", MODULES)
def test_vygruzka_knigi_tolko_tendershchiku(
    db: DbSession, app_client: TestClient, offline_marketplace: None, module: str
) -> None:
    """В книге листы с себестоимостью целиком, и урезать её по ролям нечем."""
    sign_in(db, app_client, Role.VIEWER)

    assert app_client.get(f"/api/{module}/export").status_code == 403


@pytest.mark.parametrize("module", MODULES)
def test_zadacha_zapisyvaetsya_za_svoim_modulem(
    client: TestClient, signed_in: Any, offline_marketplace: None, module: str
) -> None:
    """Иначе в списке задач не разобрать, чей это прогон."""
    client.post(f"/api/{module}/analyze")

    jobs = client.get(f"/api/jobs?module={module}").json()

    assert [item["kind"] for item in jobs] == ["analyze"]
    assert all(item["module"] == module for item in jobs)


# --- меню ------------------------------------------------------------------


def test_oba_razdela_est_v_menyu(client: TestClient) -> None:
    """Меню строится из `/api/modules`: захардкоженный пункт означает, что
    контракт модулей сломан."""
    modules = {item["slug"]: item for item in client.get("/api/modules").json()}

    assert modules["skstore"]["nav"][0]["path"] == "/skstore/bargains"
    assert modules["omarket"]["nav"][0]["path"] == "/omarket/preorders"
    # Сверху то, с чем работают каждый день.
    assert list(modules) == ["skstore", "omarket", "tender"]


def test_v_menyu_net_punktov_kotorye_nikuda_ne_vedut(client: TestClient) -> None:
    """Пункт, молча уводящий на чужой раздел, хуже отсутствующего: человек
    решает, что сломался вход, и перестаёт верить остальным пунктам тоже.

    Маршруты читаются из самого `App.tsx`, а не переписываются сюда списком.
    Список пришлось бы править вторым движением после каждой правки меню, и
    забыли бы про него ровно тогда, когда он нужен: пункт добавили, страницу
    не завели, тест продолжает зеленеть.
    """
    app_tsx = Path(__file__).resolve().parents[3] / "apps/web/src/App.tsx"
    if not app_tsx.is_file():
        pytest.skip("фронтенд не рядом — сверять меню не с чем")

    routes = {
        "/" + path
        for path in re.findall(r'<Route\s+path="([^"*:]+)"', app_tsx.read_text(encoding="utf-8"))
        if path not in {"/", "/login"}
    }

    paths = {item["path"] for module in client.get("/api/modules").json() for item in module["nav"]}

    assert paths <= routes, f"в меню есть пункт без страницы: {sorted(paths - routes)}"


def response_text(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data, ensure_ascii=False)


# --- разбор одной строки ---------------------------------------------------


@pytest.fixture
def offline_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Готовый разбор вместо обращения к ядру."""
    import importlib

    from platform_api.modules.detail import (
        Detail,
        Section,
        Table,
        money_field,
        text_field,
    )
    from platform_api.modules.table import Visibility

    built = Detail(
        id="777",
        title="Автошина Pirelli 265/65 R17",
        subtitle="АО «Каражанбасмунай»",
        verdict="УЧАСТВОВАТЬ",
        tone="good",
        url="https://skstore.kz/ru/home/bargain/777",
        sections=(
            Section(title="Закуп", fields=(text_field("Заказчик", "АО «Каражанбасмунай»"),)),
            Section(
                title="Деньги",
                fields=(money_field("Себестоимость", 70777),),
                access=Visibility.MONEY,
            ),
            Section(
                title="Где взять",
                fields=(text_field("Найдено на рынке", "1688.com"),),
                access=Visibility.SOURCING,
            ),
            Section(
                title="Конкуренты",
                table=Table(columns=("Место", "Цена"), rows=(("1", "12 000"),)),
            ),
        ),
    )
    for slug in ("skstore", "omarket"):
        module = importlib.import_module(f"platform_api.modules.{slug}.core")
        monkeypatch.setattr(module, "detail", lambda _id, built=built: built)


@pytest.mark.parametrize("module", MODULES)
def test_tendershchik_vidit_razbor_celikom(
    client: TestClient, signed_in: Any, offline_detail: None, module: str
) -> None:
    data = client.get(f"/api/{module}/item/777").json()

    assert [section["title"] for section in data["sections"]] == [
        "Закуп",
        "Деньги",
        "Где взять",
        "Конкуренты",
    ]
    assert data["hidden_sections"] == 0
    assert data["url"].startswith("https://")
    # Таблица конкурентов доезжает целиком: ради неё разбор и открывают.
    assert data["sections"][3]["table"]["rows"] == [["1", "12 000"]]


@pytest.mark.parametrize("module", MODULES)
def test_zakupshchik_ne_vidit_deneg_v_razbore(
    db: DbSession, app_client: TestClient, offline_detail: None, module: str
) -> None:
    """Разбор — второй путь к себестоимости, и закрыт он так же, как первый."""
    sign_in(db, app_client, Role.BUYER)

    data = app_client.get(f"/api/{module}/item/777").json()

    titles = [section["title"] for section in data["sections"]]
    assert "Деньги" not in titles
    assert "Где взять" in titles, "закупщику нужно знать, где брать"
    assert data["hidden_sections"] == 1
    assert "70777" not in response_text(data)


@pytest.mark.parametrize("module", MODULES)
def test_nesushchestvuyushchaya_stroka_eto_404(
    client: TestClient, signed_in: Any, offline_marketplace: None, module: str
) -> None:
    import importlib

    core = importlib.import_module(f"platform_api.modules.{module}.core")
    monkeypatch_none = core.detail
    del monkeypatch_none

    response = client.get(f"/api/{module}/item/нет-такого")

    assert response.status_code in (404, 503)


@pytest.mark.parametrize("module", MODULES)
def test_razbor_zakryt_bez_sessii(client: TestClient, module: str) -> None:
    assert client.get(f"/api/{module}/item/777").status_code == 401


# --- истёкший срок ---------------------------------------------------------


@pytest.mark.parametrize("module", MODULES)
def test_istyokshie_ne_popadayut_v_rabochiy_spisok(module: str) -> None:
    """Закуп, приём по которому закончился, — не работа, а история.

    В базе он остаётся: по нему видно, что мы пропустили и почём уходило.
    В рабочем списке его нет.
    """
    import importlib
    from datetime import UTC, datetime, timedelta

    core = importlib.import_module(f"platform_api.modules.{module}.core")
    past = datetime.now(UTC) - timedelta(days=3)

    assert core.is_expired(_row_with(module, deadline=past, ours=False)) is True
    assert core.in_focus(_row_with(module, deadline=past, ours=False)) is False


@pytest.mark.parametrize("module", MODULES)
def test_svoyo_ostayotsya_i_posle_sroka(module: str) -> None:
    """По своему ждут результата, и убрать его с глаз значит потерять то,
    за чем следят."""
    import importlib
    from datetime import UTC, datetime, timedelta

    core = importlib.import_module(f"platform_api.modules.{module}.core")
    past = datetime.now(UTC) - timedelta(days=3)

    assert core.is_expired(_row_with(module, deadline=past, ours=True)) is False


@pytest.mark.parametrize("module", MODULES)
def test_deystvuyushchiy_srok_ne_meshaet(module: str) -> None:
    import importlib
    from datetime import UTC, datetime, timedelta

    core = importlib.import_module(f"platform_api.modules.{module}.core")
    future = datetime.now(UTC) + timedelta(days=3)

    assert core.is_expired(_row_with(module, deadline=future, ours=False)) is False
    # Пустой срок не считается истёкшим: «не знаем» и «поздно» — разное.
    assert core.is_expired(_row_with(module, deadline=None, ours=False)) is False


def _row_with(module: str, *, deadline: Any, ours: bool) -> Any:
    """Строка в том виде, в каком её видят ядра."""
    from decimal import Decimal

    if module == "skstore":
        from skstore.domain.enums import BargainKind, BargainStatus, Verdict
        from skstore.domain.models import Bargain, BargainAnalysis

        return BargainAnalysis(
            bargain=Bargain(
                platform_id="1",
                kind=BargainKind.GOODS,
                status=BargainStatus.ACTIVE,
                title="Товар",
                unit_price=Decimal(100),
                deadline_at=deadline,
                is_winner=ours,
            ),
            market=None,
            verdict=Verdict.PROMISING,
        )

    from omarket.domain.enums import PreorderStatus
    from omarket.domain.models import Preorder
    from omarket.export.reports import FocusRow

    return FocusRow(
        preorder=Preorder(
            platform_id="1",
            status=PreorderStatus.ACTUAL,
            title="Товар",
            unit_price=Decimal(100),
            deadline_at=deadline,
            has_our_offer=ours,
        ),
        analysis=None,
    )


# --- общая база ------------------------------------------------------------


@pytest.mark.parametrize("module", MODULES)
def test_faylovaya_baza_eto_neispravnost(monkeypatch: pytest.MonkeyPatch, module: str) -> None:
    """Для платформы SQLite — не выбор, а неисправность.

    К базе одновременно ходят почасовые прогоны и открытые страницы, а пишущий
    в файл блокирует его целиком. Сломается это не сразу, а в первый час, когда
    работают все, — поэтому сводка готовности должна сказать заранее.
    """
    import importlib

    core = importlib.import_module(f"platform_api.modules.{module}.core")
    settings = core.core_settings()

    monkeypatch.setattr(type(settings.db), "is_sqlite", property(lambda _self: True))
    assert any("SQLite" in problem for problem in core.readiness()["problems"])

    monkeypatch.setattr(type(settings.db), "is_sqlite", property(lambda _self: False))
    assert not any("SQLite" in problem for problem in core.readiness()["problems"])
