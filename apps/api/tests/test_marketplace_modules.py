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
    goods: str
    cost_value: Decimal
    margin: Decimal
    verdict: _Verdict = _Verdict("promising")
    analysis: _Analysis = _Analysis("promising")


_COLUMNS = (
    _Column("Товар", getter=lambda row: row.goods, width=40),
    _Column("Где купить", getter=lambda _row: "1688.com · 900 000 ₸", width=30),
    _Column(
        "Себестоимость",
        getter=lambda row: row.cost_value,
        width=16,
        number_format="#,##0.00",
    ),
    _Column("Маржа ₸", getter=lambda row: row.margin, width=16, number_format="#,##0.00"),
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
    assert "не отвечает" in response.json()["detail"]


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


def test_oba_razdela_est_v_menyu(client: TestClient, db: DbSession) -> None:
    """Меню строится из `/api/modules`: захардкоженный пункт означает, что
    контракт модулей сломан."""
    sign_in(db, client, Role.ANALYST)
    modules = {item["slug"]: item for item in client.get("/api/modules").json()}

    assert modules["skstore"]["nav"][0]["path"] == "/skstore/bargains"
    assert modules["omarket"]["nav"][0]["path"] == "/omarket/preorders"
    assert modules["goszakup"]["nav"][0]["path"] == "/goszakup/lots"
    # По наличию, а не по месту в списке: порядок пунктов внутри модуля —
    # это порядок дня, и он меняется. Проверять индекс значит ронять тест на
    # каждой перестановке меню, ничего не проверив по существу.
    работа = {item["path"] for item in modules["work"]["nav"]}
    assert "/work/lots" in работа
    # Раздел задаёт сам пункт: меню группируется по делу, а не по модулю.
    assert {item["group"] for item in modules["work"]["nav"]} == {
        "Мой стол",
        "Работа",
    }
    # Порядок разделов — порядок дня. Сверху взятые в работу лоты: с них
    # начинают, потому что там то, чего от нас ждут к сроку. Площадки ниже —
    # они показывают, что появилось, а тендерная папка приходит по почте.
    assert list(modules) == ["work", "skstore", "omarket", "tender", "goszakup"]


def test_v_menyu_net_punktov_kotorye_nikuda_ne_vedut(client: TestClient, db: DbSession) -> None:
    """Пункт, молча уводящий на чужой раздел, хуже отсутствующего: человек
    решает, что сломался вход, и перестаёт верить остальным пунктам тоже.

    Маршруты читаются из самого `App.tsx`, а не переписываются сюда списком.
    Список пришлось бы править вторым движением после каждой правки меню, и
    забыли бы про него ровно тогда, когда он нужен: пункт добавили, страницу
    не завели, тест продолжает зеленеть.
    """
    sign_in(db, client, Role.ANALYST)
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


def test_fail_itog_nazyvaet_pomehi_a_ne_tolko_verdikt() -> None:
    """Разбор отвечает на шесть вопросов, а открывают его ради седьмого.

    «Участвовать или нет» человек до сих пор складывал в голове из шести
    разделов — и складывал по-разному в понедельник и в пятницу. Итог
    собирает то же самое, ничего не решая заново: вердикт и причину посчитало
    ядро, пороги взяты из его настроек.
    """
    from types import SimpleNamespace

    from platform_api.modules.skstore.core import _blockers

    # Находка не отвечает требованию, связка со складом слабая, предложений по
    # ТРУ мало — три помехи разом, и это обычный случай, а не выдуманный.
    item = SimpleNamespace(
        bargain=SimpleNamespace(deadline_at=None),
        finding=SimpleNamespace(matches_spec=False, match_note="другая модель"),
        match=SimpleNamespace(score=Decimal("0.4")),
        market=SimpleNamespace(offers=2),
        cost=SimpleNamespace(unit_cost=Decimal(1)),
        llm=SimpleNamespace(summary="ок"),
    )

    found = {label: text for label, text, _tone in _blockers(item)}

    assert "другая модель" in found["Товар не тот"]
    assert "40%" in found["Связка со складом слабая"]
    # Порог надёжности — из настроек ядра, а не из числа, написанного здесь.
    assert "их 2" in found["Мало предложений"]
    assert "Себестоимости нет" not in found


def test_fail_ischerpannyy_srok_ne_prosit_podat() -> None:
    """За три часа до конца приёма закуп горит, после — уже нет смысла."""
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from platform_api.modules.skstore.core import _blockers

    def item(hours: float) -> Any:
        return SimpleNamespace(
            bargain=SimpleNamespace(deadline_at=datetime.now(UTC) + timedelta(hours=hours)),
            finding=None,
            match=None,
            market=None,
            cost=SimpleNamespace(unit_cost=Decimal(1)),
            llm=SimpleNamespace(summary="ок"),
        )

    def left(hours: float) -> str:
        return {label: text for label, text, _tone in _blockers(item(hours))}.get("Срок", "")

    assert left(5) == ""
    assert "меньше чем через три часа" in left(2)
    assert "приём закрыт" in left(-1)


def test_fail_snabzhenie_ne_vidit_chuzhih_razdelov(client: TestClient, db: DbSession) -> None:
    """Отбор и аналитика — работа отдела разбора.

    Снабжению там нечего делать: суммы и маржа ему не показываются, а без них
    отбор пуст. Пункт, ведущий в бесполезный раздел, человек нажимает ровно
    один раз, а потом перестаёт верить всему меню.
    """
    sign_in(db, client, Role.BUYER)
    tender = next(item for item in client.get("/api/modules").json() if item["slug"] == "tender")

    # Остался общий стол двух отделов — и только он.
    assert [item["path"] for item in tender["nav"]] == ["/tender/works"]


# --- госзакупки ------------------------------------------------------------


def test_fail_spisok_kodov_pravit_tolko_administrator(
    app_client: TestClient, db: DbSession
) -> None:
    """Список кодов ЕНС ТРУ меняет только администратор.

    Список задаёт, что вообще попадёт в отбор: код, добавленный по ошибке, —
    это сотни чужих лотов и запросы к государственному порталу за ними.
    Решение о номенклатуре принимает тот, кто за неё отвечает.
    """
    sign_in(db, app_client, Role.ANALYST)

    добавить = app_client.post("/api/goszakup/codes", json={"code": "262013.000.000099"})
    assert добавить.status_code == 403
    assert app_client.delete("/api/goszakup/codes/262013.000.000011").status_code == 403


def test_fail_kod_s_opechatkoy_otklonyayetsya(app_client: TestClient, db: DbSession) -> None:
    """Код с опечаткой отклоняется при вводе, а не сутки спустя.

    На портале он не найдёт ничего, и выяснилось бы это пустой выгрузкой на
    следующий день — когда уже неясно, кода нет или закупок по нему.
    """
    sign_in(db, app_client, Role.ADMIN)

    ответ = app_client.post("/api/goszakup/codes", json={"code": "26201.100.00000"})
    assert ответ.status_code == 400
    assert "ЕНС ТРУ" in ответ.json()["detail"]


def test_fail_v_razbore_vidny_sosednie_loty_obyavleniya() -> None:
    """В разборе видно всё объявление, а не только нашу позицию.

    Под наши коды ЕНС ТРУ из объявления подходит одна позиция из четырёх, а
    торги идут по объявлению целиком: соседние лоты — это и конкуренты за
    внимание заказчика, и повод взять закупку целиком, если остальное мы тоже
    возим. Показав только своё, мы прячем половину предмета решения.
    """
    from types import SimpleNamespace
    from unittest.mock import patch

    from platform_api.modules.goszakup import detail

    наш = SimpleNamespace(
        announce_id=17547275,
        purchase_number="17547275-1",
        lot_number="87470604-ОИ2",
        name="Компрессор",
        customer="Филиал Жетісу",
        method="Из одного источника",
        status="Опубликован",
        end_date=None,
        published_at=None,
        applications=None,
        enstru_code="262013.000.000011",
        enstru_name="Компрессор",
        brief="кондиционера",
        extra="Компрессор кондиционера Mitsubishi",
        count=Decimal(1),
        unit="Штука",
        unit_price=Decimal(85000),
        amount=Decimal(85000),
        prepayment_percent=None,
        kato="",
        delivery_term="",
        incoterms="",
        spec_name="",
        spec_url="",
        spec_text="",
        url="",
    )

    def сосед(number: str, name: str) -> Any:
        return detail._Neighbour(
            number=number,
            name=name,
            extra="",
            unit="Штука",
            count=Decimal(1),
            amount=Decimal(1000),
            status="Опубликован",
            ours=True,
        )

    соседи = (сосед("87470604-ОИ2", "Компрессор"), сосед("87468559-ОИ2", "Фильтр"))
    with patch.object(detail, "_announce_neighbours", return_value=(соседи, "")):
        раздел = detail.neighbours(наш)

    assert раздел.table is not None
    assert [row[1] for row in раздел.table.rows] == ["87470604-ОИ2", "87468559-ОИ2"]
    # Наш отмечен: иначе в таблице из четырёх строк его не найти.
    assert [row[0] for row in раздел.table.rows] == ["▸", ""]


def test_fail_razbor_ne_zhdyot_portal() -> None:
    """Открытие панели не должно ходить на портал.

    Замер до правки: 49 секунд на разбор лота против 0,1 у того же разбора без
    портала — всё, что панель показывает, лежит в нашей базе. Ждал человек, а
    отвечал чужой сервер, и в день, когда портал отдаёт 504, панель не
    открывалась вовсе.

    Чужие лоты объявления приходят отдельным запросом; здесь проверяется, что
    разбор к порталу не обращается совсем.
    """
    from types import SimpleNamespace
    from unittest.mock import patch

    from platform_api.modules.goszakup import detail

    лот = SimpleNamespace(
        announce_id=17547275,
        purchase_number="17547275-1",
        lot_number="87470604-ОИ2",
        name="Компрессор",
        customer="Филиал Жетісу",
        method="Из одного источника",
        status="Опубликован",
        end_date=None,
        published_at=None,
        applications=None,
        enstru_code="262013.000.000011",
        enstru_name="Компрессор",
        brief="",
        extra="",
        count=Decimal(1),
        unit="Штука",
        unit_price=Decimal(85000),
        amount=Decimal(85000),
        prepayment_percent=None,
        kato="",
        delivery_term="",
        incoterms="",
        spec_name="",
        spec_url="",
        spec_text="",
        url="",
    )
    свои = (
        detail._Neighbour(
            number="87470604-ОИ2",
            name="Компрессор",
            extra="",
            unit="Штука",
            count=Decimal(1),
            amount=Decimal(85000),
            status="Опубликован",
            ours=True,
        ),
    )

    def не_звать(_announce_id: int) -> tuple[tuple[Any, ...], str]:
        raise AssertionError("Разбор пошёл на портал — панель снова будет ждать минуту")

    with (
        patch.object(detail, "_from_base", return_value=свои),
        patch.object(detail, "_from_portal", side_effect=не_звать),
    ):
        разбор = detail.build(лот, code="GZ000001")

    раздел = next(s for s in разбор.sections if s.key == "announce_lots")
    assert раздел.table is not None
    assert [row[1] for row in раздел.table.rows] == ["87470604-ОИ2"]


def test_fail_nedostupnyy_portal_ne_lomayet_razbor() -> None:
    """Портал не отвечает — раздел говорит об этом словами, а не пустотой.

    Панель при этом уже открыта: она собирается из нашей базы и портала не
    ждёт. «Не дозвонились» человек понимает и идёт по ссылке на портал сам;
    пустой раздел он прочитал бы как «в объявлении один лот».
    """
    from types import SimpleNamespace
    from unittest.mock import patch

    from platform_api.modules.goszakup import detail

    пустой = SimpleNamespace(
        announce_id=1,
        purchase_number="1-1",
        lot_number="",
        name="Ноутбук",
        customer="",
        method="",
        status="",
        end_date=None,
        published_at=None,
        applications=None,
        enstru_code="",
        enstru_name="",
        brief="",
        extra="",
        count=None,
        unit="",
        unit_price=None,
        amount=None,
        prepayment_percent=None,
        kato="",
        delivery_term="",
        incoterms="",
        spec_name="",
        spec_url="",
        spec_text="",
        url="",
    )
    with patch.object(
        detail, "_announce_neighbours", return_value=((), "Портал сейчас не отвечает")
    ):
        раздел = detail.neighbours(пустой)

    assert "не отвечает" in раздел.empty and раздел.table is None


# --- обсуждение ------------------------------------------------------------


def test_fail_chuzhuyu_repliku_ne_popravit(app_client: TestClient, db: DbSession) -> None:
    """Чужую реплику не правит никто, включая администратора.

    Убрать чужое администратор может, переписать — нет: убранное видно по
    отсутствию, переписанное не видно никак, а спор о том, кто что сказал,
    обсуждение и должно разрешать.
    """
    from platform_api.modules import discussion

    org = sign_in(db, app_client, Role.ANALYST)
    чужая = discussion.add(
        db, org.id, None, module="goszakup", row_id="17547275-1", body="Брать не стоит"
    )
    db.commit()

    ответ = app_client.patch(
        f"/api/discussion/messages/{чужая.id}", json={"body": "Наоборот, берём"}
    )
    assert ответ.status_code == 403
    assert "свои" in ответ.json()["detail"]


def test_fail_svoyu_repliku_pravit_i_vidno_chto_pravili(
    app_client: TestClient, db: DbSession
) -> None:
    """Свою реплику править можно, и это видно.

    Молча изменённый текст в общей ветке — тот же спор о сказанном, ради
    которого ветку и заводили.
    """
    sign_in(db, app_client, Role.ANALYST)
    написано = app_client.post("/api/discussion/goszakup/17547275-1", json={"body": "Берём"}).json()

    поправлено = app_client.patch(
        f"/api/discussion/messages/{написано['id']}", json={"body": "Берём, но по цене ниже"}
    )
    assert поправлено.status_code == 200
    assert поправлено.json()["body"] == "Берём, но по цене ниже"
    assert поправлено.json()["edited_at"]


def test_fail_schyotchik_obsuzhdeniya_odnim_zaprosom(app_client: TestClient, db: DbSession) -> None:
    """Счётчики по всем строкам разом, а не по строке.

    Строк сотни, а веток десятки: обращение на каждую строку было бы сотнями
    запросов ради нескольких десятков записей.
    """
    from platform_api.modules import discussion

    org = sign_in(db, app_client, Role.ANALYST)
    discussion.add(db, org.id, None, module="goszakup", row_id="A-1", body="первое")
    discussion.add(db, org.id, None, module="goszakup", row_id="A-1", body="второе")
    discussion.add(db, org.id, None, module="goszakup", row_id="B-1", body="одно")

    итоги = discussion.summaries(db, org.id, "goszakup", ["A-1", "B-1", "C-1"])

    assert итоги["A-1"].count == 2 and итоги["B-1"].count == 1
    assert "C-1" not in итоги
    # В подсказку идёт последняя реплика, а не первая.
    assert итоги["A-1"].last == "второе"


def test_skachivanie_knigi_nichego_ne_sobiraet(
    db: DbSession, app_client: TestClient, offline_marketplace: None, monkeypatch: Any
) -> None:
    """Скачивание читает готовый файл, а не собирает его на месте.

    Сборка книги skstore занимает процессор целиком, а процесс API один: под
    нагрузкой замер дал 156 секунд, за которые переставала отвечать даже
    проверка готовности. Браузер к тому моменту запрос бросал, а сервер его всё
    равно досчитывал.
    """
    from platform_api.modules.skstore import core as skstore_core

    def refuse() -> Any:
        raise AssertionError("Скачивание не должно собирать книгу")

    monkeypatch.setattr(skstore_core, "export_workbook", refuse)
    monkeypatch.setattr(skstore_core, "latest_workbook", lambda: None)
    sign_in(db, app_client, Role.ANALYST)

    answer = app_client.get("/api/skstore/export")

    assert answer.status_code == 404
    assert "Собрать книгу" in answer.json()["detail"]


def test_kniga_sobiraetsya_zadachey(
    db: DbSession, app_client: TestClient, offline_marketplace: None
) -> None:
    """Кнопка ставит сборку в очередь, а не ждёт её в запросе."""
    sign_in(db, app_client, Role.ANALYST)

    started = app_client.post("/api/skstore/export")

    assert started.status_code == 202
    assert started.json()["job_id"]

    listed = app_client.get("/api/skstore/worklist").json()
    assert "build" in listed["actions"]
    assert "export" not in listed["actions"]


@pytest.mark.parametrize("module", MODULES)
def test_spisok_ne_shlet_istekshie_bez_prosby(
    db: DbSession, app_client: TestClient, offline_marketplace: None, module: str
) -> None:
    """По умолчанию уезжает только отобранное, а не весь список.

    У skstore это 1,9 МБ, из которых в отборе примерно шестая часть; остальное
    — строки с истёкшим приёмом. Браузер их всё равно выбрасывал, но мегабайт
    шёл по сети на каждое открытие раздела и на каждый переход в аналитику.
    """
    sign_in(db, app_client, Role.ANALYST)

    narrow = app_client.get(f"/api/{module}/worklist").json()
    wide = app_client.get(f"/api/{module}/worklist?scope=all").json()

    assert all(row["focus"] for row in narrow["rows"]), "Приехало то, чего не просили"
    assert len(narrow["rows"]) <= len(wide["rows"])
    # Число до отбора приходит отдельно: по длине `rows` его больше не узнать,
    # а плитка «Показано 28 из 184» считает именно по нему.
    assert narrow["rows_total"] == len(wide["rows"])
    assert wide["rows_total"] == len(wide["rows"])


@pytest.mark.parametrize("module", MODULES)
def test_gotovnost_otvechaet_bystro(
    db: DbSession, app_client: TestClient, offline_marketplace: None, module: str
) -> None:
    """Сводка готовности укладывается в срок проверки контейнера.

    Считалась она перебором: ради одного числа база отдавала тысячу с лишним
    строк объектами, и ответ шёл девять секунд при таймауте проверки в пять.
    Контейнер помечался больным, хотя работал, — а по здоровью выстроен
    `depends_on`, и зависимые службы такой API не дождались бы.

    Порог здесь с большим запасом: тест меряет не быстродействие машины, а то,
    что подсчёт остался запросом, а не вернулся в перебор.
    """
    import time

    start = time.monotonic()
    answer = app_client.get(f"/api/{module}/health")
    spent = time.monotonic() - start

    assert answer.status_code == 200
    assert spent < 2.0, f"Готовность {module} собиралась {spent:.1f} с"
