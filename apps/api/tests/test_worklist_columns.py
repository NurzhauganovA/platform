"""Колонки рабочего списка: совпадение с Excel и граница доступа.

Два свойства, за которые здесь отвечают, стоят дороже остальных.

**Экран и файл показывают одно и то же.** Сотрудник открывает таблицу в
браузере и книгу в Excel и сверяет их. Колонка, разошедшаяся на одну, — это
полчаса выяснений, кто из двух прав, и подорванное доверие к обоим.

**Себестоимость не уходит закупщику.** Таблица собирается из колонок проекта
автоматически, поэтому новая колонка попала бы в ответ сама. Проверяется не
только то, что деньги скрыты, но и то, что каждая колонка вообще описана в
правах: неописанная считается денежной, и об этом должен узнать разработчик,
а не заказчик.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest
from platform_api.db.models import Role
from platform_api.modules.omarket.columns import POLICY as OMARKET_POLICY
from platform_api.modules.skstore.columns import POLICY as SKSTORE_POLICY
from platform_api.modules.table import (
    Visibility,
    build_table,
    sees_money,
    visible_columns,
)

MODULES = [
    pytest.param("skstore", SKSTORE_POLICY, id="skstore"),
    pytest.param("omarket", OMARKET_POLICY, id="omarket"),
]


def focus_columns(module: str) -> Any:
    if module == "skstore":
        from platform_api.modules.skstore import core

        return core.focus_columns()
    from platform_api.modules.omarket import core as omarket_core

    return omarket_core.focus_columns()


# --- совпадение с книгой ---------------------------------------------------


@pytest.mark.parametrize(("module", "policy"), MODULES)
def test_kazhdaya_kolonka_knigi_opisana_v_pravah(module: str, policy: dict[str, Any]) -> None:
    """Колонка, добавленная в проекте, не должна показаться сама собой.

    Неописанная считается денежной и молча пропадает у закупщика — а это
    выглядит как потеря данных. Пусть лучше падает тест.
    """
    titles = {column.title for column in focus_columns(module)}
    missing = titles - set(policy)

    assert not missing, f"не описаны в правах: {sorted(missing)}"


@pytest.mark.parametrize(("module", "policy"), MODULES)
def test_v_pravah_net_lishnih_kolonok(module: str, policy: dict[str, Any]) -> None:
    """Обратная сторона: колонку убрали из книги, а из прав забыли.

    Мёртвая запись безобидна ровно до того дня, когда в книге появится другая
    колонка с тем же названием и молча унаследует чужие права.
    """
    titles = {column.title for column in focus_columns(module)}
    stale = set(policy) - titles

    assert not stale, f"колонок нет в книге: {sorted(stale)}"


@pytest.mark.parametrize(("module", "policy"), MODULES)
def test_tendershchik_vidit_knigu_celikom(module: str, policy: dict[str, Any]) -> None:
    """Порядок и состав колонок для тендерщика совпадают с листом книги."""
    columns = focus_columns(module)
    chosen = visible_columns(columns, policy, Role.ANALYST)

    assert [column.title for _index, column, _access in chosen] == [
        column.title for column in columns
    ]


# --- граница доступа -------------------------------------------------------


@pytest.mark.parametrize(("module", "policy"), MODULES)
def test_zakupshchik_ne_vidit_deneg(module: str, policy: dict[str, Any]) -> None:
    """Ни себестоимости, ни маржи — ни в колонке, ни в пояснении к ней."""
    chosen = visible_columns(focus_columns(module), policy, Role.BUYER)
    titles = [column.title for _index, column, _access in chosen]

    assert not any("ебестоимост" in title for title in titles)
    assert not any("аржа" in title for title in titles)
    assert not any("аработок" in title for title in titles)
    # «Почему» читается как безобидное пояснение, но внутри проценты маржи.
    assert "Почему" not in titles


@pytest.mark.parametrize(("module", "policy"), MODULES)
def test_zakupshchik_vidit_gde_kupit(module: str, policy: dict[str, Any]) -> None:
    """Забрать у закупщика «Где купить» значит забрать у него работу."""
    chosen = visible_columns(focus_columns(module), policy, Role.BUYER)

    assert "Где купить" in [column.title for _index, column, _access in chosen]


@pytest.mark.parametrize(("module", "policy"), MODULES)
def test_nablyudatel_vidit_tolko_ploshchadku(module: str, policy: dict[str, Any]) -> None:
    """Наблюдателю — то, что и так открыто любому участнику закупа."""
    chosen = visible_columns(focus_columns(module), policy, Role.VIEWER)

    assert {access for _index, _column, access in chosen} <= {Visibility.ALL}


@pytest.mark.parametrize("role", [Role.ADMIN, Role.ANALYST])
def test_dengi_vidyat_tolko_te_komu_polozheno(role: Role) -> None:
    assert sees_money(role) is True


@pytest.mark.parametrize("role", [Role.BUYER, Role.VIEWER])
def test_ostalnye_deneg_ne_vidyat(role: Role) -> None:
    assert sees_money(role) is False


def test_neizvestnaya_kolonka_schitaetsya_denezhnoy() -> None:
    """Отказ по умолчанию. Показывать, пока не запретили, — верный способ
    однажды отдать себестоимость и узнать об этом от заказчика."""
    columns = [_column("Новая колонка")]

    assert visible_columns(columns, {}, Role.BUYER) == []
    assert len(visible_columns(columns, {}, Role.ANALYST)) == 1


# --- сборка таблицы --------------------------------------------------------


@dataclass(frozen=True)
class _Column:
    title: str
    getter: Any
    hyperlink: Any = None
    width: int = 18
    number_format: str | None = None


def _column(title: str, **kwargs: Any) -> Any:
    return _Column(title=title, getter=lambda _row: "x", **kwargs)


def test_chisla_ostayutsya_chislami() -> None:
    """По марже сортируют и подводят итог. Строка «1 234,56 ₸» этого не даёт."""
    from decimal import Decimal

    columns = [_Column("Маржа ₸", getter=lambda _r: Decimal("1234.56"), number_format="#,##0.00")]
    table = build_table(columns, [object()], policy={"Маржа ₸": Visibility.ALL}, role=Role.ANALYST)

    assert table.rows[0].cells[0].number == pytest.approx(1234.56)
    assert table.rows[0].cells[0].text == ""
    assert table.columns[0].format == "money"
    assert table.columns[0].align == "right"


def test_ssylka_edet_vmeste_so_znacheniem() -> None:
    columns = [
        _Column("Торг", getter=lambda _r: "Открыть", hyperlink=lambda _r: "https://skstore.kz/1")
    ]
    table = build_table(columns, [object()], policy={"Торг": Visibility.ALL}, role=Role.VIEWER)

    assert table.rows[0].cells[0].link == "https://skstore.kz/1"


def test_slomannaya_yacheyka_ne_ronyaet_tablicu() -> None:
    """Строк несколько сотен, и одна сломанная — не повод показать человеку
    пустой экран вместо работы."""

    def explode(_row: Any) -> Any:
        raise ValueError("в ядре что-то поменяли")

    columns = [_Column("Цена", getter=explode)]
    table = build_table(columns, [object()], policy={"Цена": Visibility.ALL}, role=Role.ANALYST)

    assert table.rows[0].cells[0].text == "—"


def test_skrytye_kolonki_schitayutsya() -> None:
    """Молча урезанная таблица выглядит как потерянные данные."""
    columns = [_column("Товар"), _column("Себестоимость")]
    policy = {"Товар": Visibility.ALL, "Себестоимость": Visibility.MONEY}

    table = build_table(columns, [object()], policy=policy, role=Role.BUYER)

    assert len(table.columns) == 1
    assert table.hidden_columns == 1


def test_podsvetka_stroki_doezzhaet_do_brauzera() -> None:
    """В книге строки отбора залиты по вердикту, и на экране должно быть так
    же: глаз ищет зелёное, а не читает двести строк подряд."""
    columns = [_column("Решение")]
    table = build_table(
        columns,
        [object()],
        policy={"Решение": Visibility.ALL},
        role=Role.ANALYST,
        tone=lambda _row: "good",
    )

    assert table.rows[0].tone == "good"


def test_bez_podsvetki_stroka_ostayotsya_pustoy() -> None:
    columns = [_column("Решение")]
    table = build_table(columns, [object()], policy={"Решение": Visibility.ALL}, role=Role.ANALYST)

    assert table.rows[0].tone == ""


def test_klyuchi_kolonok_razlichny_i_chitaemy() -> None:
    """«Маржа %» и «Маржа ₸» — разные колонки, и ключ обязан их различать."""
    columns = [_column("Маржа %"), _column("Маржа ₸")]
    policy = {"Маржа %": Visibility.ALL, "Маржа ₸": Visibility.ALL}

    table = build_table(columns, [object()], policy=policy, role=Role.ANALYST)
    keys = [column.key for column in table.columns]

    assert keys == ["marzha_percent", "marzha_kzt"]


def test_odinakovye_zagolovki_ne_dayut_odinakovyh_klyuchey() -> None:
    """Два одинаковых ключа — и браузер перепутает колонки при перерисовке."""
    columns = [_column("Цена"), _column("Цена")]
    table = build_table(columns, [object()], policy={"Цена": Visibility.ALL}, role=Role.ANALYST)

    assert len({column.key for column in table.columns}) == 2


# --- главные колонки -------------------------------------------------------


@pytest.mark.parametrize(("module", "policy"), MODULES)
def test_glavnye_kolonki_est_v_knige(module: str, policy: dict[str, Any]) -> None:
    """Опечатка в списке главных молча убрала бы колонку с экрана."""
    from platform_api.modules.omarket.columns import ESSENTIAL as OMARKET_KEY
    from platform_api.modules.skstore.columns import ESSENTIAL as SKSTORE_KEY

    essential = SKSTORE_KEY if module == "skstore" else OMARKET_KEY
    titles = {column.title for column in focus_columns(module)}

    assert set(essential) <= titles, f"нет в книге: {sorted(set(essential) - titles)}"


@pytest.mark.parametrize(("module", "policy"), MODULES)
def test_v_glavnom_est_dengi_i_srok(module: str, policy: dict[str, Any]) -> None:
    """То, ради чего человек открывает раздел, должно быть видно без прокрутки
    вбок: себестоимость, маржа и срок."""
    from platform_api.modules.omarket.columns import ESSENTIAL as OMARKET_KEY
    from platform_api.modules.skstore.columns import ESSENTIAL as SKSTORE_KEY

    essential = SKSTORE_KEY if module == "skstore" else OMARKET_KEY

    assert any("ебестоимост" in title for title in essential)
    assert any("аржа" in title for title in essential)
    assert any(title in {"Приём до", "Срок подачи"} for title in essential)


@pytest.mark.parametrize(("module", "policy"), MODULES)
def test_vedikta_v_glavnom_net_ego_pokazyvaet_cvet(module: str, policy: dict[str, Any]) -> None:
    """Колонка на восемнадцать знаков ради слова, которое уже показано цветной
    меткой и легендой, — это место, отнятое у маржи."""
    from platform_api.modules.omarket.columns import ESSENTIAL as OMARKET_KEY
    from platform_api.modules.skstore.columns import ESSENTIAL as SKSTORE_KEY

    essential = SKSTORE_KEY if module == "skstore" else OMARKET_KEY

    assert "Решение" not in essential
    assert "Оценка" not in essential


@pytest.mark.parametrize(("module", "policy"), MODULES)
def test_gde_kupit_pokazyvaetsya_znachkom(module: str, policy: dict[str, Any]) -> None:
    """Сорок четыре знака про поставщика, срок и минимальную партию в строке
    списка вытесняют маржу за край экрана. В списке нужен один ответ — нашли
    или нет, — а подробности открываются разбором."""
    from platform_api.modules.omarket.columns import COMPACT as OMARKET_ICONS
    from platform_api.modules.skstore.columns import COMPACT as SKSTORE_ICONS

    compact = SKSTORE_ICONS if module == "skstore" else OMARKET_ICONS
    titles = {column.title for column in focus_columns(module)}

    assert "Где купить" in compact
    assert compact <= titles, "колонки нет в книге"


def test_znachok_dohodit_do_brauzera() -> None:
    columns = [_column("Где купить"), _column("Товар")]
    policy = {"Где купить": Visibility.ALL, "Товар": Visibility.ALL}

    table = build_table(
        columns,
        [object()],
        policy=policy,
        role=Role.ANALYST,
        compact={"Где купить"},
    )

    by_title = {column.title: column for column in table.columns}
    assert by_title["Где купить"].compact is True
    assert by_title["Товар"].compact is False


# --- часовой пояс ----------------------------------------------------------


def test_vremya_uezzhaet_so_smescheniem() -> None:
    """SQLite не хранит часовой пояс, и время приходит «голым». Уедет таким в
    браузер — там его прочитают как местное: в Алматы это пять часов, и срок,
    до которого ещё полдня, показывается истёкшим."""
    from datetime import UTC, datetime

    from platform_api.modules.table import to_utc

    # Без пояса намеренно: ровно так значение приходит из SQLite, и ровно
    # это здесь и проверяется.
    naive = datetime(2026, 8, 17, 14, 34)  # noqa: DTZ001
    columns = [_Column("Приём до", getter=lambda _r: naive, number_format="DD.MM.YYYY HH:MM")]

    table = build_table(columns, [object()], policy={"Приём до": Visibility.ALL}, role=Role.ANALYST)

    assert table.rows[0].cells[0].text.endswith("+00:00")
    assert to_utc(naive) == naive.replace(tzinfo=UTC)


def test_osvedomlyonnoe_vremya_ne_trogaem() -> None:
    """Значение с поясом уже однозначно — переписывать его нельзя."""
    from datetime import timedelta, timezone

    from platform_api.modules.table import to_utc

    almaty = timezone(timedelta(hours=5))
    aware = datetime(2026, 8, 17, 19, 34, tzinfo=almaty)

    assert to_utc(aware) == aware


def test_pustoy_srok_ne_istyok() -> None:
    """«Не знаем, когда» и «поздно» — разные ответы."""
    from platform_api.modules.table import is_past

    assert is_past(None) is False


# --- роли колонок ----------------------------------------------------------


@pytest.mark.parametrize(
    ("slug", "columns_module", "core_module"),
    [
        ("skstore", "platform_api.modules.skstore.columns", "platform_api.modules.skstore.core"),
        ("omarket", "platform_api.modules.omarket.columns", "platform_api.modules.omarket.core"),
    ],
)
def test_roli_ssylayutsya_na_sushchestvuyushchie_kolonki(
    slug: str, columns_module: str, core_module: str
) -> None:
    """Роль, повешенная на несуществующий заголовок, ничего не ломает — она
    просто молчит, и итог по отобранному показывает ноль.

    Такое расхождение возникает от переименования колонки в ядре: заголовок
    там поправили, а роль осталась на старом. Заметить это на экране нельзя —
    плитка «Заработаем» просто перестаёт считаться.
    """
    import importlib

    roles = importlib.import_module(columns_module).ROLES
    titles = {column.title for column in importlib.import_module(core_module).focus_columns()}

    assert set(roles) <= titles, f"{slug}: роли на колонках, которых нет в книге"


def test_tendernye_roli_ssylayutsya_na_sushchestvuyushchie_kolonki() -> None:
    from platform_api.modules.tender.columns import ROLES
    from tender_analyze.export.ranked import HEADERS

    assert set(ROLES) <= set(HEADERS), "роли на колонках, которых нет в книге отбора"


@pytest.mark.parametrize(
    "columns_module",
    [
        "platform_api.modules.skstore.columns",
        "platform_api.modules.omarket.columns",
        "platform_api.modules.tender.columns",
    ],
)
def test_rol_ne_povtoryaetsya_v_predelah_razdela(columns_module: str) -> None:
    """Две колонки с ролью «заработок» — это удвоенный итог, и заметно это
    только тому, кто сложит числа руками."""
    import importlib

    roles = list(importlib.import_module(columns_module).ROLES.values())

    assert len(roles) == len(set(roles)), f"повторяющиеся роли: {roles}"
