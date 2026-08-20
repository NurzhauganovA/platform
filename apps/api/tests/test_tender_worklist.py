"""Тендерный отбор через HTTP.

Ядро здесь не трогается по-настоящему: у него своя база, свои доступы и свои
тесты. Проверяется перевод на язык HTTP — и в первую очередь то, кому что
достаётся. Таблица собирается из колонок книги автоматически, и колонка,
добавленная в ядре, попала бы в ответ сама, вместе с себестоимостью.

Отдельно проверяется, что колонки и значения приходят из одного места. Книга
описывает лист «Отбор» заголовками и функцией значений, и разъехаться они
могут незаметно: значение встанет не под своим заголовком, а заметит это тот,
кто в отчёте увидит маржу в графе количества.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from platform_api.db.models import Role
from sqlalchemy.orm import Session as DbSession
from tests.conftest import sign_in


@dataclass
class _Row:
    """Строка книги в том виде, в каком её собирает ядро."""

    title: str = "Насос центробежный ЦНС 60-330"
    customer: str = "АО «Акбастау»"
    ens_code: str = "281312.500.000001"
    average_quote: Decimal | None = Decimal("4761300")
    quantity: Decimal | None = Decimal("56")
    total: Decimal | None = Decimal("266632800")
    cost: Decimal | None = Decimal("123252640")
    subject: str = "Поставка насосов"
    category: str = "Насосное оборудование"
    kind: str = "Товар"
    method: str = "Запрос ценовых предложений"
    margin_percent: Decimal | None = Decimal("53.8")
    review: str = ""
    date: str = "12.03.2026"
    quotes: list[Any] = field(default_factory=list)
    cost_lines: list[Any] = field(default_factory=list)
    findings: list[Any] = field(default_factory=list)
    market: list[Any] = field(default_factory=list)
    folder: str = "тендеры/2 аппак/Каныбек_Насосы 56шт"
    folder_path: str = "/Users/analyst/тендеры/2 аппак/Каныбек_Насосы 56шт"
    by_analog: str = ""
    parts: list[Any] = field(default_factory=list)
    missing: list[Any] = field(default_factory=list)
    cost_low: Decimal | None = None
    cost_high: Decimal | None = None


@dataclass(frozen=True)
class _Verdict:
    label: str = "Брать"
    score: int = 78
    reasons: tuple[str, ...] = ("маржа 53,8% выше порога", "два поставщика на рынке")


@dataclass(frozen=True)
class _Ranked:
    row: _Row
    verdict: _Verdict = _Verdict()


@pytest.fixture
def case_folder(tmp_path: Any) -> Any:
    """Папка закупки с настоящим файлом внутри.

    Настоящим, а не выдуманным: платформа отдаёт содержимое с диска, и
    проверять это подменой файловой системы значит проверять подмену.
    """
    folder = tmp_path / "тендеры" / "аппак" / "Насосы 56шт"
    folder.mkdir(parents=True)
    (folder / "ТЗ насосы.pdf").write_bytes("%PDF-1.7\nтехническое задание\n".encode())
    return folder


@pytest.fixture
def offline_worklist(monkeypatch: pytest.MonkeyPatch) -> _Ranked:
    """Готовый отбор вместо обращения к базе ядра.

    Без подмены тест зависел бы от того, что лежит в базе разработчика:
    сегодня двести шестьдесят закупок, завтра ноль — и падают проверки, к
    которым это отношения не имеет.
    """
    import importlib

    from platform_api.modules.tender import worklist as module

    item = _Ranked(row=_Row())
    monkeypatch.setattr(module, "_ranked", lambda: [item])
    monkeypatch.setattr(module, "case_files", lambda _folder: ())
    router = importlib.import_module("platform_api.modules.tender.router")
    monkeypatch.setattr(router, "worklist", module)
    return item


@pytest.fixture
def with_files(monkeypatch: pytest.MonkeyPatch, offline_worklist: _Ranked, case_folder: Any) -> Any:
    """Тот же отбор, но у закупки есть папка с документами."""
    from platform_api.modules.tender import worklist as module

    offline_worklist.row.folder_path = str(case_folder)
    files = (
        module.CaseFile(
            sha256="a" * 64,
            name="ТЗ насосы.pdf",
            kind="ТЗ",
            size_bytes=42,
            path=case_folder / "ТЗ насосы.pdf",
        ),
        module.CaseFile(
            sha256="b" * 64,
            name="Проект МЗ.docx",
            kind="МЗ",
            size_bytes=1024,
            # Архив не подключён: файл в базе есть, на диске его не видно.
            path=case_folder / "нет-такого.docx",
        ),
    )
    monkeypatch.setattr(module, "case_files", lambda folder: files if folder else ())
    return files


# --- рабочий список --------------------------------------------------------


def test_bez_sessii_ne_otdaem_nichego(client: TestClient) -> None:
    """За этим адресом себестоимость и маржа."""
    assert client.get("/api/tender/worklist").status_code == 401


def test_kolonki_i_znacheniya_prihodyat_iz_knigi(
    client: TestClient, signed_in: Any, offline_worklist: _Ranked
) -> None:
    """Заголовки — те же, что на листе «Отбор», и значения стоят под своими.

    Проверяется не список заголовков, а совпадение с книгой: список пришлось
    бы править вторым движением после каждой правки ядра, и разъехались бы
    они ровно тогда, когда никто не смотрит.
    """
    from tender_analyze.export.ranked import HEADERS, row_values

    data = client.get("/api/tender/worklist").json()

    assert [item["title"] for item in data["columns"]] == list(HEADERS)
    assert data["sheet"] == "Отбор"

    expected = row_values(offline_worklist)  # type: ignore[arg-type]
    cells = data["rows"][0]["cells"]
    assert cells[HEADERS.index("название закупки")]["text"] == str(expected[2])
    assert cells[HEADERS.index("сумма")]["number"] == pytest.approx(266632800.0)
    assert cells[HEADERS.index("себестоимость")]["number"] == pytest.approx(123252640.0)


def test_verdikt_krasit_stroku_i_podpisan_slovami(
    client: TestClient, signed_in: Any, offline_worklist: _Ranked
) -> None:
    """Цвет сам по себе смысла не несёт: при дальтонизме «брать» и «мимо»
    неразличимы, поэтому слово приходит вместе с ним."""
    data = client.get("/api/tender/worklist").json()

    assert data["rows"][0]["tone"] == "good"
    assert ("good", "Брать") in [(item["tone"], item["title"]) for item in data["legend"]]
    # Счётчики ключуются тоном, а не словом: браузер думает тонами, и слово
    # «Брать» в разделе, где вердикты называются иначе, дало бы молчаливый ноль.
    assert data["verdicts"] == {"good": 1}


def test_knopok_obnovit_i_pereschitat_zdes_net(
    client: TestClient, signed_in: Any, offline_worklist: _Ranked
) -> None:
    """Папки разбирают на машине тендерщика. Кнопка, которую нечем обслужить,
    хуже отсутствующей: человек нажимает и получает ошибку."""
    data = client.get("/api/tender/worklist").json()

    assert data["actions"] == ["export"]


def test_zakupshchik_ne_poluchaet_sebestoimost_dazhe_zaprosom(
    db: DbSession, app_client: TestClient, offline_worklist: _Ranked
) -> None:
    """Спрятать колонку в браузере и отдать её в JSON — самый частый способ
    отдать себестоимость наружу. Проверяется именно ответ."""
    import json

    sign_in(db, app_client, Role.BUYER)

    data = app_client.get("/api/tender/worklist").json()

    titles = [item["title"] for item in data["columns"]]
    assert "себестоимость" not in titles
    assert "заработок" not in titles
    assert "моржа %" not in titles
    assert data["hidden_columns"] == 3
    assert data["margin_total"] is None
    # Ни в одной ячейке — ни числом, ни в тексте.
    assert "123252640" not in json.dumps(data, ensure_ascii=False)
    # И книгу с теми же числами закупщику не отдают — ни кнопкой, ни запросом.
    assert data["actions"] == []
    assert app_client.get("/api/tender/worklist/export").status_code == 403


def test_neznakomaya_kolonka_schitaetsya_denezhnoy() -> None:
    """Таблица собирается автоматически, и колонка, добавленная в ядре,
    попала бы в ответ сама. Умолчание должно быть закрытым."""
    from platform_api.modules.table import Visibility, visible_columns
    from platform_api.modules.tender.columns import POLICY

    @dataclass(frozen=True)
    class _Unknown:
        title: str = "закупочная цена поставщика"
        width: int = 20
        number_format: str | None = None
        getter: Any = None
        hyperlink: Any = None

    for role in (Role.BUYER, Role.VIEWER):
        assert visible_columns([_Unknown()], policy=POLICY, role=role) == []
    assert POLICY["себестоимость"] is Visibility.MONEY


# --- разбор одной закупки --------------------------------------------------


def test_razbor_otkryvaetsya_po_ustoychivomu_imeni(
    client: TestClient, signed_in: Any, offline_worklist: _Ranked
) -> None:
    """Имя строки — не её номер: он съезжает от пересортировки, а ссылку на
    разбор пересылают коллеге."""
    from platform_api.modules.tender.worklist import row_id

    data = client.get("/api/tender/worklist").json()
    identifier = data["rows"][0]["id"]
    assert identifier == row_id(offline_worklist)  # type: ignore[arg-type]

    detail = client.get(f"/api/tender/item/{identifier}").json()
    assert detail["verdict"] == "Брать"
    assert detail["tone"] == "good"
    # Ссылки на площадку у тендерной закупки нет: она пришла папкой по почте.
    assert detail["url"] is None
    assert [section["title"] for section in detail["sections"]][:3] == [
        "Закупка",
        "Решение",
        "Деньги",
    ]


def test_neizvestnaya_stroka_eto_404_a_ne_pustoy_razbor(
    client: TestClient, signed_in: Any, offline_worklist: _Ranked
) -> None:
    assert client.get("/api/tender/item/0000000000000000").status_code == 404


def test_zakupshchik_ne_vidit_razdelov_s_dengami(
    db: DbSession, app_client: TestClient, offline_worklist: _Ranked
) -> None:
    """Та же граница, что у колонок, и по той же причине."""
    sign_in(db, app_client, Role.BUYER)

    detail = app_client.get(f"/api/tender/item/{_identifier(offline_worklist)}").json()

    titles = [section["title"] for section in detail["sections"]]
    assert "Деньги" not in titles
    assert "Как считали себестоимость" not in titles
    # Молча урезанный разбор выглядит недоделанным — про скрытое сказано.
    assert detail["hidden_sections"] > 0


def _identifier(item: _Ranked) -> str:
    from platform_api.modules.tender.worklist import row_id

    return row_id(item)  # type: ignore[arg-type]


# --- документы закупки -----------------------------------------------------


def test_gde_kupit_bez_lishnih_kolonok(
    client: TestClient, signed_in: Any, offline_worklist: _Ranked
) -> None:
    """Доставка, срок и минимальная партия убраны: они съедали треть ширины
    ради «1 шт» и «20 дн.», одинаковых почти во всех строках."""
    offline_worklist.row.market = [_Finding()]

    data = client.get(f"/api/tender/item/{_identifier(offline_worklist)}").json()

    section = next(s for s in data["sections"] if s["title"] == "Где купить")
    assert section["table"]["columns"] == [
        "Позиция",
        "Страна",
        "Площадка",
        "Поставщик",
        "Цена, ₸",
        "Тот ли товар",
    ]


def test_dokumenty_zakupki_vidny_spiskom(
    client: TestClient, signed_in: Any, with_files: Any, offline_worklist: _Ranked
) -> None:
    """Последний вопрос перед подачей — «покажи само ТЗ»."""
    item_id = _identifier(offline_worklist)

    data = client.get(f"/api/tender/item/{item_id}").json()

    section = next(s for s in data["sections"] if s["title"] == "Документы закупки")
    # Свёрнут: файлов в папке бывает три десятка.
    assert section["collapsed"] is True
    assert [(f["label"], f["text"]) for f in section["fields"]] == [
        ("ТЗ", "ТЗ насосы.pdf"),
        ("МЗ", "Проект МЗ.docx"),
    ]
    # Что есть на диске — ссылкой, чего нет — словами. Молчание про
    # неподключённый архив читается как «платформа сломалась».
    assert section["fields"][0]["link"] == f"/api/tender/item/{item_id}/file/{'a' * 64}"
    assert section["fields"][1]["link"] is None
    assert section["fields"][1]["note"] == "нет на диске"
    assert "подключается к платформе томом" in section["note"]


def test_dokument_otdaetsya_s_diska(
    client: TestClient, signed_in: Any, with_files: Any, offline_worklist: _Ranked
) -> None:
    response = client.get(f"/api/tender/item/{_identifier(offline_worklist)}/file/{'a' * 64}")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    # Открыть, а не скачать: за ТЗ идут посмотреть.
    assert "inline" in response.headers["content-disposition"]


def test_dokument_iz_chuzhoy_zakupki_ne_otdaetsya(
    client: TestClient, signed_in: Any, with_files: Any, offline_worklist: _Ranked
) -> None:
    """Взять файл по одному хэшу значило бы прочитать чужую папку, подставив
    хэш оттуда, — а в чужой папке лежат КП с ценами, которых нам не показывали."""
    assert client.get(f"/api/tender/item/0000000000000000/file/{'a' * 64}").status_code == 404


def test_nesuschestvuyuschiy_fayl_govorit_pochemu(
    client: TestClient, signed_in: Any, with_files: Any, offline_worklist: _Ranked
) -> None:
    """Файл в базе есть, а на диске его нет: это не поломка платформы, а
    неподключённый архив, и сказать это словами полезнее пустого ответа."""
    response = client.get(f"/api/tender/item/{_identifier(offline_worklist)}/file/{'b' * 64}")

    assert response.status_code == 404
    assert "TENDER_ARCHIVE" in response.json()["detail"]


def test_dokumenty_zakryty_bez_sessii(client: TestClient, offline_worklist: _Ranked) -> None:
    assert client.get(f"/api/tender/item/x/file/{'a' * 64}").status_code == 401


@dataclass(frozen=True)
class _Finding:
    """Находка на рынке в том виде, в каком её отдаёт ядро."""

    position: str = "Насос ЦНС 60-330"
    country: str = "Казахстан"
    marketplace: str = "satu.kz"
    supplier: str = "ТОО «KARLSKRONA»"
    price: Decimal = Decimal("3650000")
    landed: Decimal = Decimal("3857500")
    delivery_days: int = 15
    min_order: str = "1 шт"
    matches_spec: bool = True
    note: str = ""
    url: str = "https://satu.kz/p/nasos-tsns"
    """Ссылка на карточку. У настоящей находки она есть, и подделка без неё
    прятала бы поломку: разбор обращается к ней при каждом открытии."""


# --- выбор поставщика ------------------------------------------------------


@dataclass(frozen=True)
class _Country:
    value: str = "Казахстан"


@dataclass(frozen=True)
class _Market:
    """Находка так, как её хранит ядро.

    Отдельно от `_Finding`: та описывает строку книги, а эта — доменный
    объект, и поля у них разные. Одна подделка на две роли скрыла бы, что
    разбор читает то одну, то другую.
    """

    marketplace: str = "dn.ru"
    supplier: str = "ДН.РУ"
    price_kzt: Decimal = Decimal("2000")
    matches_spec: bool = True
    country: _Country = _Country()
    url: str = "https://dn.ru/nasos"


@dataclass(frozen=True)
class _Chosen:
    """Находка вместе с посчитанной по ней себестоимостью — как у ядра."""

    position: str
    landed_cost: Decimal
    quantity: Decimal | None
    finding: _Market


@pytest.fixture
def with_sourcing(monkeypatch: pytest.MonkeyPatch, offline_worklist: _Ranked) -> Any:
    """Две находки по одной позиции: дешёвая непроходная и дорогая подходящая.

    Ровно тот случай, ради которого выбор и сделан: считать по дешёвой нельзя,
    её нельзя поставить, но и разница в деньгах должна быть видна.
    """
    from platform_api.modules.tender import worklist as module

    cheap = _Chosen(
        position="Насос",
        landed_cost=Decimal("1000"),
        quantity=None,
        finding=_Market(
            marketplace="1688.com",
            supplier="CNP",
            price_kzt=Decimal("1000"),
            matches_spec=False,
        ),
    )
    proper = _Chosen(
        position="Насос", landed_cost=Decimal("2000"), quantity=None, finding=_Market()
    )

    @dataclass(frozen=True)
    class _Sourcing:
        opportunities: tuple[_Chosen, ...]

    monkeypatch.setattr(module, "case_sourcing", lambda _folder: (_Sourcing((cheap, proper)), 1))
    # Сумма закупки поменьше: при 266 миллионах обе себестоимости дают маржу
    # 100,0 % после округления, и проверка «маржа пересчиталась» не поймала бы
    # ничего.
    offline_worklist.row.total = Decimal("200000")

    # Строки книги идут в том же порядке и с теми же площадками: по ним разбор
    # и сопоставляет находки со своими ключами.
    offline_worklist.row.market = [
        _Finding(
            position="Насос",
            marketplace="1688.com",
            supplier="CNP",
            matches_spec=False,
            price=Decimal("1000"),
        ),
        _Finding(position="Насос", marketplace="dn.ru", supplier="ДН.РУ", price=Decimal("2000")),
    ]
    return module, cheap, proper


def test_po_umolchaniyu_beretsya_podhodyashchaya_a_ne_deshevaya(
    client: TestClient, signed_in: Any, with_sourcing: Any, offline_worklist: _Ranked
) -> None:
    """Товар, который не проходит по требованиям, поставить нельзя — какой бы
    ни была его цена. Дешёвая находка с пометкой «нет» в расчёт не идёт."""
    module, cheap, proper = with_sourcing

    data = client.get(f"/api/tender/item/{_identifier(offline_worklist)}").json()

    table = next(s for s in data["sections"] if s["title"] == "Где купить")["table"]
    assert table["chosen"] == [module.finding_key(proper)]
    assert module.finding_key(cheap) not in table["chosen"]


def test_vybor_postavshchika_pereschityvaet_dengi(
    client: TestClient, signed_in: Any, with_sourcing: Any, offline_worklist: _Ranked
) -> None:
    """«Подходит» — суждение модели, и тендерщик вправе с ним не согласиться.
    Выбрал другую находку — деньги должны стать её."""
    module, cheap, _proper = with_sourcing
    item_id = _identifier(offline_worklist)

    before = _money(client.get(f"/api/tender/item/{item_id}").json())
    after = _money(
        client.get(f"/api/tender/item/{item_id}?pick={module.finding_key(cheap)}").json()
    )

    # 56 штук по 2000 против 56 по 1000 — себестоимость ровно вдвое меньше.
    assert before["Себестоимость"] == pytest.approx(112000.0)
    assert after["Себестоимость"] == pytest.approx(56000.0)
    # И заработок с маржой пересчитаны под неё, а не остались от умолчания.
    assert (before["Заработок"], before["Маржа"]) == (pytest.approx(88000.0), "44.0 %")
    assert (after["Заработок"], after["Маржа"]) == (pytest.approx(144000.0), "72.0 %")


def test_vybor_otmechen_v_spiske_nahodok(
    client: TestClient, signed_in: Any, with_sourcing: Any, offline_worklist: _Ranked
) -> None:
    """Без отметки непонятно, откуда взялась цифра, и человек считает её
    заново на глаз."""
    module, cheap, _proper = with_sourcing

    data = client.get(
        f"/api/tender/item/{_identifier(offline_worklist)}?pick={module.finding_key(cheap)}"
    ).json()

    table = next(s for s in data["sections"] if s["title"] == "Где купить")["table"]
    assert table["chosen"] == [module.finding_key(cheap)]


def test_nesushchestvuyushchiy_vybor_ne_lomaet_razbor(
    client: TestClient, signed_in: Any, with_sourcing: Any, offline_worklist: _Ranked
) -> None:
    """Ссылку с выбором пересылают, а отбор к тому времени пересобран: находки
    той уже нет. Разбор должен показать умолчание, а не отказать."""
    response = client.get(f"/api/tender/item/{_identifier(offline_worklist)}?pick=неттакой")

    assert response.status_code == 200
    assert _money(response.json())["Себестоимость"] == pytest.approx(112000.0)


def test_nahodki_otdayutsya_so_ssylkami(
    client: TestClient, signed_in: Any, with_sourcing: Any, offline_worklist: _Ranked
) -> None:
    """Находка без ссылки — обещание, а не поставщик: менеджер идёт искать её
    заново поиском и половину не находит."""
    data = client.get(f"/api/tender/item/{_identifier(offline_worklist)}").json()

    table = next(s for s in data["sections"] if s["title"] == "Где купить")["table"]
    assert all(link for link in table["links"])
    # Ссылка на площадке, а не на названии: название в строках одно и то же.
    assert table["columns"][table["link_column"]] == "Площадка"


def _money(detail: dict[str, Any]) -> dict[str, Any]:
    fields = next(s for s in detail["sections"] if s["title"] == "Деньги")["fields"]
    return {
        item["label"]: (item["number"] if item["number"] is not None else item["text"])
        for item in fields
    }
