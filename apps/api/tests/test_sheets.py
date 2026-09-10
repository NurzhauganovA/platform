"""Варианты разбора спецификации.

Один лот собирается по-разному: на своём корпусе и на готовом системном
блоке. Цена, поставщик и срок у этих способов разные, а требования заказчика
одни и те же — на этом и держатся правила ниже.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from platform_api.db.base import utcnow
from platform_api.db.models import LotCard, Organization, User
from platform_api.errors import SpokenError
from platform_api.modules import cards, sheets
from sqlalchemy.orm import Session as DbSession


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
def card(db: DbSession, org: Organization, кто: uuid.UUID) -> LotCard:
    return cards.open_card(
        db,
        organization_id=org.id,
        module="goszakup",
        row_id="81468165-ЗЦП1",
        snapshot=cards.Snapshot(
            code="GZ000001",
            title="Компьютер (моноблок)",
            customer="ГУ Управление",
            amount=Decimal("8660625"),
            enstru_code="262013.000.000011",
            category="Компьютеры",
            deadline=utcnow() + timedelta(days=1),
        ),
        by=кто,
    )


def _разобрать(db: DbSession, card: LotCard) -> None:
    """Кладёт таблицу так, как её оставила бы модель, а следом человек."""
    sheets.save(
        db,
        card,
        columns=list(sheets.default_columns()),
        rows=[
            sheets.Row(
                key="r1",
                cells={
                    "subject": "проц",
                    "demand": "не менее 8 ядер",
                    "brief": "Ядра: 8",
                    "price": "120000",
                    "cost": "90000",
                    "ours": "Core i5-13400",
                },
            ),
        ],
    )


def test_fail_variant_beryot_trebovaniya_no_ne_nashi_tseny(db: DbSession, card: LotCard) -> None:
    """Новый вариант наследует спецификацию и не наследует наш ответ.

    Требования заказчика те же — переписывать их руками значит однажды
    переписать с ошибкой и подать заявку по придуманному. А цена, себес и наш
    товар в новом варианте другие: ради них вариант и заводится, и
    скопированные они выглядели бы уже посчитанными.
    """
    _разобрать(db, card)

    letter = sheets.branch(db, card)

    assert letter == "B"
    второй = sheets.load(db, card, letter)
    assert второй.variant == "B"
    assert [column.key for column in второй.columns] == [
        column.key for column in sheets.default_columns()
    ]
    ячейки = второй.rows[0].cells
    assert ячейки["demand"] == "не менее 8 ядер"
    assert ячейки["brief"] == "Ядра: 8"
    assert ячейки.get("price", "") == ""
    assert ячейки.get("cost", "") == ""
    assert ячейки.get("ours", "") == ""


def test_fail_pravka_varianta_ne_zadevaet_sosednego(db: DbSession, card: LotCard) -> None:
    """Цена, набранная в «B», не появляется в «A».

    Отложенное сохранение уходит через паузу после набора, и адрес варианта
    ошибиться не имеет права: перепутанный, он затирает соседний целиком.
    """
    _разобрать(db, card)
    sheets.branch(db, card)

    sheets.save(
        db,
        card,
        columns=list(sheets.default_columns()),
        rows=[sheets.Row(key="r1", cells={"demand": "не менее 8 ядер", "price": "98000"})],
        variant="B",
    )

    assert sheets.load(db, card, "A").rows[0].cells["price"] == "120000"
    assert sheets.load(db, card, "B").rows[0].cells["price"] == "98000"


def test_fail_spisok_variantov_ne_lomaet_chtenie(db: DbSession, card: LotCard) -> None:
    """Второй вариант не должен ломать открытие вкладки.

    Таблица искалась по паре «модуль и строка», и с появлением второй записи
    этот поиск падал бы `MultipleResultsFound` — вкладка «Разбор» отдавала бы
    пятисотую всем, у кого больше одного варианта.
    """
    _разобрать(db, card)
    sheets.branch(db, card)

    assert sheets.variants(db, card) == ["A", "B"]
    assert sheets.load(db, card).variant == "A"


def test_fail_posledniy_variant_ne_udalyaetsya(db: DbSession, card: LotCard) -> None:
    """Лот без разбора — пустая вкладка, по которой не понять, потеряно или не начато."""
    _разобрать(db, card)

    with pytest.raises(SpokenError):
        sheets.drop(db, card, "A")

    sheets.branch(db, card)
    sheets.drop(db, card, "B")
    assert sheets.variants(db, card) == ["A"]


def test_fail_variantov_ne_bolshe_shesti(db: DbSession, card: LotCard) -> None:
    """Дальше шести сравнение перестаёт помещаться в голову, а выбирают всё равно один."""
    _разобрать(db, card)
    for _ in range(sheets.MAX_VARIANTS - 1):
        sheets.branch(db, card)

    assert len(sheets.variants(db, card)) == sheets.MAX_VARIANTS
    with pytest.raises(SpokenError):
        sheets.branch(db, card)


def test_fail_stolbtsy_zavodyatsya_s_sebesom(db: DbSession, card: LotCard) -> None:
    """Себестоимость стоит вплотную к цене: заработок считается из разницы."""
    ключи = [column.key for column in sheets.default_columns()]

    assert ключи == ["subject", "demand", "brief", "price", "cost", "ours"]
    названия = {column.key: column.title for column in sheets.hand_columns()}
    assert названия["ours"] == "Наш товар"
