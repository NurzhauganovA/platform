"""Карточка лота: переходы, подписи и задачи.

Проверяется то, что стоит денег. Лот, объявленный готовым без подписи
снабжения, — это участие в закупке, товара под которую нет; лот, отмеченный
«не участвуем» без причины, через месяц никто не объяснит.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from platform_api.db.base import utcnow
from platform_api.db.models import (
    ApprovalKind,
    ApprovalState,
    Department,
    LotCard,
    LotStatus,
    Organization,
    Participation,
    Role,
    TaskState,
    User,
)
from platform_api.errors import SpokenError
from platform_api.modules import cards
from sqlalchemy import select

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
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


def _завести(db: DbSession, org: Organization, кто: uuid.UUID) -> uuid.UUID:
    card = cards.open_card(
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
    return card.id


def _карточка(db: DbSession, org: Organization) -> LotCard:
    found = cards.by_row(db, organization_id=org.id, module="goszakup", row_id="81468165-ЗЦП1")
    assert found is not None
    return found


def _подписать_всё(db: DbSession, org: Organization, card_id: uuid.UUID, кто: uuid.UUID) -> None:
    роли = {
        ApprovalKind.MANAGER: Role.MANAGER,
        ApprovalKind.SUPPLY: Role.BUYER,
        ApprovalKind.LEGAL: Role.LAWYER,
        ApprovalKind.TECHNOLOGIST: Role.TECHNOLOGIST,
        ApprovalKind.ASSEMBLER: Role.ASSEMBLER,
    }
    for kind, role in роли.items():
        cards.sign(
            db,
            organization_id=org.id,
            card_id=card_id,
            role=role,
            user_id=кто,
            kind=kind,
            state=ApprovalState.APPROVED,
        )


def test_fail_kartochka_na_lot_odna(db: DbSession, org: Organization, кто: uuid.UUID) -> None:
    """Кнопку «Взять в работу» нажимают дважды.

    Вторая карточка по тому же лоту означала бы два ответственных, два набора
    подписей и два разных ответа на вопрос, что с закупкой.
    """
    assert _завести(db, org, кто) == _завести(db, org, кто)


def test_fail_pyat_podpisey_zavodyatsya_srazu(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Пустые подписи видны с самого начала.

    Иначе «согласовано» у лота с одной подписью выглядит так же, как у лота с
    пятью: в обоих случаях ни одного отказа.
    """
    card_id = _завести(db, org, кто)
    карточка = cards.one(
        db, organization_id=org.id, card_id=card_id, role=Role.MANAGER, user_id=кто
    )
    assert len(карточка.approvals) == len(ApprovalKind)
    assert all(item.state == "waiting" for item in карточка.approvals)
    assert not карточка.approved


def test_fail_bez_vsekh_podpisey_ne_gotov(db: DbSession, org: Organization, кто: uuid.UUID) -> None:
    """Лот, объявленный готовым без подписи снабжения, — это участие в
    закупке, товара под которую нет."""
    card_id = _завести(db, org, кто)
    cards.move(
        db,
        organization_id=org.id,
        card_id=card_id,
        role=Role.ANALYST,
        user_id=кто,
        to=LotStatus.ANALYSIS,
    )
    cards.move(
        db,
        organization_id=org.id,
        card_id=card_id,
        role=Role.ANALYST,
        user_id=кто,
        to=LotStatus.APPROVAL,
    )
    with pytest.raises(SpokenError, match="подписи"):
        cards.move(
            db,
            organization_id=org.id,
            card_id=card_id,
            role=Role.MANAGER,
            user_id=кто,
            to=LotStatus.READY,
        )

    _подписать_всё(db, org, card_id, кто)
    cards.move(
        db,
        organization_id=org.id,
        card_id=card_id,
        role=Role.MANAGER,
        user_id=кто,
        to=LotStatus.READY,
    )
    карточка = cards.one(
        db, organization_id=org.id, card_id=card_id, role=Role.MANAGER, user_id=кто
    )
    assert карточка.status == LotStatus.READY.value
    assert карточка.approved


def test_fail_podpis_stavit_svoy_otdel(db: DbSession, org: Organization, кто: uuid.UUID) -> None:
    """Если один человек подписывает за двоих, согласование перестаёт быть
    согласованием."""
    card_id = _завести(db, org, кто)
    with pytest.raises(SpokenError, match="ставите не вы"):
        cards.sign(
            db,
            organization_id=org.id,
            card_id=card_id,
            role=Role.BUYER,
            user_id=кто,
            kind=ApprovalKind.LEGAL,
            state=ApprovalState.APPROVED,
        )


def test_fail_otkaz_v_podpisi_trebuet_prichiny(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Подпись «нет» без слова о том, что не так, останавливает работу и не
    говорит, что чинить."""
    card_id = _завести(db, org, кто)
    with pytest.raises(SpokenError, match="мешает"):
        cards.sign(
            db,
            organization_id=org.id,
            card_id=card_id,
            role=Role.BUYER,
            user_id=кто,
            kind=ApprovalKind.SUPPLY,
            state=ApprovalState.REJECTED,
        )


def test_fail_perevesti_mozhno_kuda_ugodno(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Порядок шагов — подсказка, а не забор.

    Раньше переходы описывала таблица: из «Нового» только в «Обсуждение» или
    «На разбор», из «Завершён» никуда. Она описывала процесс таким, каким его
    задумали, — а компания молодая, и процесс ещё меняется. Каждое расхождение
    с жизнью упиралось в отказ, объяснить который человеку нечем.

    Проверяется крайний случай: из последнего состояния обратно в первое.
    """
    card_id = _завести(db, org, кто)
    for to in (LotStatus.DONE, LotStatus.NEW, LotStatus.AWAITING_PAYMENT):
        card = cards.move(
            db,
            organization_id=org.id,
            card_id=card_id,
            role=Role.ADMIN,
            user_id=кто,
            to=to,
        )
        assert card.status is to


def test_fail_gotov_k_uchastiyu_vsyo_ravno_trebuet_podpisey(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Свободные переходы не отменили того, что стоит денег.

    Лот, объявленный готовым без подписи снабжения, — это участие в закупке,
    товара под которую нет. Это запрет не про порядок шагов, и он остался.
    """
    card_id = _завести(db, org, кто)

    with pytest.raises(SpokenError, match="подписи"):
        cards.move(
            db,
            organization_id=org.id,
            card_id=card_id,
            role=Role.ADMIN,
            user_id=кто,
            to=LotStatus.READY,
        )


def test_fail_ne_uchastvuem_trebuet_prichiny(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Через месяц по тем же заказчикам решают заново, и «почему тогда прошли
    мимо» — рабочий вопрос."""
    card_id = _завести(db, org, кто)
    with pytest.raises(SpokenError, match="почему"):
        cards.move(
            db,
            organization_id=org.id,
            card_id=card_id,
            role=Role.HEAD,
            user_id=кто,
            to=LotStatus.SKIPPED,
        )

    cards.move(
        db,
        organization_id=org.id,
        card_id=card_id,
        role=Role.HEAD,
        user_id=кто,
        to=LotStatus.SKIPPED,
        reason="Товара нет и не будет к сроку",
    )
    карточка = cards.one(db, organization_id=org.id, card_id=card_id, role=Role.HEAD, user_id=кто)
    assert карточка.participation == Participation.NO.value
    assert "Товара нет" in карточка.skip_reason


def test_fail_gotov_ne_predlagaetsya_bez_podpisey(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Кнопка, которая всегда отвечает отказом, читается как поломка."""
    card_id = _завести(db, org, кто)
    cards.move(
        db,
        organization_id=org.id,
        card_id=card_id,
        role=Role.ANALYST,
        user_id=кто,
        to=LotStatus.ANALYSIS,
    )
    cards.move(
        db,
        organization_id=org.id,
        card_id=card_id,
        role=Role.ANALYST,
        user_id=кто,
        to=LotStatus.APPROVAL,
    )
    без = cards.one(db, organization_id=org.id, card_id=card_id, role=Role.MANAGER, user_id=кто)
    assert LotStatus.READY.value not in без.can

    _подписать_всё(db, org, card_id, кто)
    с = cards.one(db, organization_id=org.id, card_id=card_id, role=Role.MANAGER, user_id=кто)
    assert LotStatus.READY.value in с.can


def test_fail_zadacha_popadaet_v_ochered_otdela(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Отдел не указан — берётся тот, у кого лот сейчас.

    Задачу чаще всего заводят себе же, и переспрашивать об этом каждый раз
    значит добавить нажатие к самому частому действию.
    """
    card_id = _завести(db, org, кто)
    cards.move(
        db,
        organization_id=org.id,
        card_id=card_id,
        role=Role.LAWYER,
        user_id=кто,
        to=LotStatus.DISCUSSION,
    )
    задача = cards.add_task(
        db,
        organization_id=org.id,
        card_id=card_id,
        created_by=кто,
        title="  Написать   замечание  ",
    )
    assert задача.department is Department.DISCUSSION
    # Название сжимается: «Написать   замечание» с тремя пробелами в списке
    # выглядит опечаткой, а в поиске не находится.
    assert задача.title == "Написать замечание"

    очередь = cards.tasks(db, organization_id=org.id, department=Department.DISCUSSION)
    assert [item.id for item in очередь] == [str(задача.id)]
    assert очередь[0].card_code == "GZ000001"


def test_fail_zakrytye_zadachi_ne_v_ocheredi(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Очередь работы — это то, что не сделано."""
    card_id = _завести(db, org, кто)
    задача = cards.add_task(
        db, organization_id=org.id, card_id=card_id, created_by=кто, title="Проверить"
    )
    cards.close_task(
        db, organization_id=org.id, task_id=задача.id, state=TaskState.DONE, result="Сделано"
    )

    assert cards.tasks(db, organization_id=org.id) == []
    закрытые = cards.tasks(db, organization_id=org.id, state=TaskState.DONE)
    assert len(закрытые) == 1 and закрытые[0].result == "Сделано"


def test_fail_soshedshie_s_distantsii_vnizu(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Отменённый лот с горящим сроком не должен занимать верх списка."""
    живой = cards.open_card(
        db,
        organization_id=org.id,
        module="goszakup",
        row_id="живой",
        snapshot=cards.Snapshot(
            code="GZ000002", title="Ноутбук", deadline=utcnow() + timedelta(days=3)
        ),
        by=кто,
    )
    отменённый = cards.open_card(
        db,
        organization_id=org.id,
        module="goszakup",
        row_id="отменённый",
        snapshot=cards.Snapshot(
            code="GZ000003", title="Сервер", deadline=utcnow() + timedelta(hours=1)
        ),
        by=кто,
    )
    cards.move(
        db,
        organization_id=org.id,
        card_id=отменённый.id,
        role=Role.MANAGER,
        user_id=кто,
        to=LotStatus.CANCELLED,
    )

    список = cards.listing(db, organization_id=org.id, role=Role.MANAGER, user_id=кто)
    assert [item.code for item in список] == ["GZ000002", "GZ000003"]
    assert список[0].id == str(живой.id)
    # У сошедшего с дистанции срок не показывается: «осталось 40 минут»
    # означало бы, что по нему ещё что-то нужно сделать.
    assert список[1].left == ""


def test_fail_shag_puti_viden_chislom(db: DbSession, org: Organization, кто: uuid.UUID) -> None:
    """Одно слово статуса не говорит, сколько ещё идти."""
    card_id = _завести(db, org, кто)
    начало = cards.one(db, organization_id=org.id, card_id=card_id, role=Role.MANAGER, user_id=кто)
    assert начало.step == 1

    cards.move(
        db,
        organization_id=org.id,
        card_id=card_id,
        role=Role.ANALYST,
        user_id=кто,
        to=LotStatus.ANALYSIS,
    )
    дальше = cards.one(db, organization_id=org.id, card_id=card_id, role=Role.MANAGER, user_id=кто)
    assert дальше.step == cards.FLOW.index(LotStatus.ANALYSIS) + 1

    cards.move(
        db,
        organization_id=org.id,
        card_id=card_id,
        role=Role.HEAD,
        user_id=кто,
        to=LotStatus.SKIPPED,
        reason="дорого",
    )
    сошёл = cards.one(db, organization_id=org.id, card_id=card_id, role=Role.MANAGER, user_id=кто)
    assert сошёл.step == 0


def test_fail_kod_kartochki_ustoychivyy_a_ne_nomer_zakupki(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """У объявления с четырьмя лотами номер закупки один на всех.

    Карточки на этом номере в списке работ неразличимы: четыре разных товара
    под одной подписью. Код должен быть свой у каждого лота.
    """
    первый = cards.open_card(
        db,
        organization_id=org.id,
        module="goszakup",
        row_id="87790027-ЗЦП1",
        snapshot=cards.Snapshot(code="GZ000171", title="Ноутбук"),
        by=кто,
    )
    второй = cards.open_card(
        db,
        organization_id=org.id,
        module="goszakup",
        row_id="87790028-ЗЦП2",
        snapshot=cards.Snapshot(code="GZ000172", title="Компрессор"),
        by=кто,
    )
    assert первый.id != второй.id
    список = cards.listing(db, organization_id=org.id, role=Role.MANAGER, user_id=кто)
    коды = {item.code for item in список}
    assert коды == {"GZ000171", "GZ000172"}


def test_fail_srok_soglasovaniya_ranshe_sroka_priyoma(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Подписи собираются за два часа до окончания приёма.

    Это запас не на подпись, а на подачу: заявку подают руками, и десять
    минут до срока означают спешку, в которой прикладывают не тот файл.
    Показать здесь общий срок значит дать человеку два часа, которых у него
    нет.
    """
    card_id = _завести(db, org, кто)
    карточка = cards.one(
        db, organization_id=org.id, card_id=card_id, role=Role.MANAGER, user_id=кто
    )
    приём = datetime.fromisoformat(карточка.deadline)
    подписать = datetime.fromisoformat(карточка.approve_by)
    assert приём - подписать == cards.APPROVE_BEFORE
    # Остаток до подписей меньше остатка до приёма — иначе на экране
    # согласования человек видит чужой, более щедрый срок.
    assert карточка.approve_left != карточка.left


def test_fail_itogi_tolko_u_podannogo(db: DbSession, org: Organization, кто: uuid.UUID) -> None:
    """«Выиграли за» у неподанного лота означало бы итоги закупки, в которой
    мы не участвовали."""
    card_id = _завести(db, org, кто)
    with pytest.raises(SpokenError, match="поданного"):
        cards.result(
            db,
            organization_id=org.id,
            card_id=card_id,
            role=Role.MANAGER,
            won_amount=Decimal("100"),
        )


def test_fail_svoya_i_chuzhaya_tsena_ne_meshayut_drug_drugu(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Своя цена нужна, чтобы через год понять, с какой маржой брали; чужая —
    чтобы понять, с кем соревнуемся и по какой цене они берут."""
    card_id = _завести(db, org, кто)
    _довести_до_podachi(db, org, card_id, кто)

    cards.result(
        db,
        organization_id=org.id,
        card_id=card_id,
        role=Role.MANAGER,
        won_amount=Decimal("8100000"),
        winner='ТОО "Другой поставщик"',
    )
    карточка = cards.one(
        db, organization_id=org.id, card_id=card_id, role=Role.MANAGER, user_id=кто
    )
    assert карточка.won_amount == Decimal("8100000")
    assert "Другой поставщик" in карточка.winner


def test_fail_odna_zadacha_chitaetsya_odnoy(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Чтение одной задачи не должно обходить все задачи организации.

    На двух десятках разницы нет, на нескольких тысячах это полный обход
    таблицы на каждое нажатие «закрыть».
    """
    card_id = _завести(db, org, кто)
    задача = cards.add_task(
        db, organization_id=org.id, card_id=card_id, created_by=кто, title="Проверить"
    )
    одна = cards.task(db, organization_id=org.id, task_id=задача.id)
    assert одна.id == str(задача.id)
    assert одна.card_code == "GZ000001"

    with pytest.raises(SpokenError, match="не найдена"):
        cards.task(db, organization_id=org.id, task_id=uuid.uuid4())


def test_fail_fayl_k_lotu_ne_dvoitsya(db: DbSession, org: Organization, кто: uuid.UUID) -> None:
    """Хранилище складывает по хэшу содержимого: повторная загрузка того же
    счёта даёт ту же запись, а в списке она выглядела бы двумя разными."""
    from platform_api.db.models import StoredFile

    card_id = _завести(db, org, кто)
    файл = StoredFile(
        organization_id=org.id,
        original_name="счёт.pdf",
        sha256="a" * 64,
        size_bytes=1024,
    )
    db.add(файл)
    db.flush()

    первый = cards.attach(
        db, organization_id=org.id, card_id=card_id, file_id=файл.id, added_by=кто
    )
    второй = cards.attach(
        db, organization_id=org.id, card_id=card_id, file_id=файл.id, added_by=кто
    )
    assert первый.link.id == второй.link.id
    # Первая привязка новая, вторая — узнанная по содержимому, и об этом есть
    # что сказать человеку: иначе повторная загрузка выглядит пропажей.
    assert первый.known is False
    assert второй.known is True
    assert второй.stored_name == "счёт.pdf"

    приложено = cards.files(db, organization_id=org.id, card_id=card_id)
    assert [item.name for item in приложено] == ["счёт.pdf"]

    cards.detach(db, organization_id=org.id, link_id=первый.link.id)
    assert cards.files(db, organization_id=org.id, card_id=card_id) == []
    # Из хранилища файл не удаляется: тот же файл может висеть на соседнем лоте.
    assert db.get(StoredFile, файл.id) is not None


def test_fail_nomer_zakupki_i_nomer_lota_eto_raznoe(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Ключ у карточки — номер лота, а вслух говорят номер закупки.

    По номеру закупки открывают разбор: рабочий список опознаёт строку именно
    им. На номере лота ссылка молча открывала пустую панель.
    """
    card = cards.open_card(
        db,
        organization_id=org.id,
        module="goszakup",
        row_id="87790027-ЗЦП1",
        snapshot=cards.Snapshot(code="GZ000171", title="Ноутбук", source_number="17547275-1"),
        by=кто,
    )
    карточка = cards.one(
        db, organization_id=org.id, card_id=card.id, role=Role.MANAGER, user_id=кто
    )
    assert карточка.row_id == "87790027-ЗЦП1"
    assert карточка.source_number == "17547275-1"


def _довести_до_podachi(
    db: DbSession, org: Organization, card_id: uuid.UUID, кто: uuid.UUID
) -> None:
    for role, to in ((Role.ANALYST, LotStatus.ANALYSIS), (Role.ANALYST, LotStatus.APPROVAL)):
        cards.move(db, organization_id=org.id, card_id=card_id, role=role, user_id=кто, to=to)
    _подписать_всё(db, org, card_id, кто)
    for to in (LotStatus.READY, LotStatus.AWAITING):
        cards.move(
            db, organization_id=org.id, card_id=card_id, role=Role.MANAGER, user_id=кто, to=to
        )


def test_fail_zagruzka_fayla_rabotaet(db: DbSession, app_client: TestClient) -> None:
    """Сквозная загрузка: файл ложится в хранилище и виден у лота.

    Проверяется целиком, а не по частям. Первая попытка падала на поле,
    которого у таблицы файлов нет: типы этого не ловят — SQLAlchemy принимает
    любые имена в конструкторе, — и выяснилось бы это на первом человеке,
    который что-то приложил.
    """
    from tests.conftest import sign_in

    org = sign_in(db, app_client, Role.MANAGER)
    card = cards.open_card(
        db,
        organization_id=org.id,
        module="goszakup",
        row_id="лот-с-файлом",
        snapshot=cards.Snapshot(code="GZ000900", title="Сервер"),
    )
    db.commit()

    ответ = app_client.post(
        f"/api/cards/{card.id}/files",
        files={"file": ("счёт.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert ответ.status_code == 201, ответ.text
    приложен = ответ.json()
    assert приложен["name"] == "счёт.pdf"
    assert приложен["size_bytes"] == len(b"%PDF-1.4 fake")

    список = app_client.get(f"/api/cards/{card.id}/files").json()
    assert [item["name"] for item in список] == ["счёт.pdf"]

    # Скачивание идёт по хэшу и только у своего лота: хэш попадает в ссылки и
    # в журнал, а по чужому лоту файлов видеть не полагается.
    скачано = app_client.get(f"/api/cards/{card.id}/files/{приложен['sha256']}")
    assert скачано.status_code == 200
    assert скачано.content == b"%PDF-1.4 fake"

    убрано = app_client.delete(f"/api/cards/files/{приложен['id']}")
    assert убрано.status_code == 204
    assert app_client.get(f"/api/cards/{card.id}/files").json() == []


def test_fail_perevod_v_obsuzhdenie_zavodit_ego_sam(
    db: DbSession, app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Перевод в «Обсуждение» заводит обсуждение сам.

    Раньше он менял только состояние карточки. Человек переводил лот, шёл в
    раздел обсуждений и своего лота там не находил: обсуждение заводила
    отдельная кнопка в разборе строки портала, и её надо было отыскать и
    нажать ещё раз. Два способа сделать одно и то же, из которых работал один.
    """
    from platform_api.modules import cards_router
    from tests.conftest import sign_in

    org = sign_in(db, app_client, Role.MANAGER)
    who = db.execute(select(User.id)).scalars().first()
    assert who is not None
    card_id = _завести(db, org, who)
    db.commit()

    called: list[str] = []

    def запомнить(_db: object, **kwargs: object) -> object:
        called.append(str(kwargs["lot_number"]))
        return SimpleNamespace(remark=SimpleNamespace(id=uuid.uuid4()), job_id=None)

    monkeypatch.setattr(cards_router.start, "ensure", запомнить)

    answer = app_client.post(f"/api/cards/{card_id}/move", json={"to": "discussion", "reason": ""})

    assert answer.status_code == 200
    assert called == ["81468165-ЗЦП1"], "Обсуждение по лоту не завелось"


def test_fail_perevod_ne_lomaetsya_ot_nedostupnogo_portala(
    db: DbSession, app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """База портала недоступна — лот всё равно переходит.

    Откатывать переход из-за этого значит врать о состоянии: решение обсуждать
    принято, а обсуждение потом заводится кнопкой, как и раньше.
    """
    from platform_api.modules import cards_router
    from tests.conftest import sign_in

    org = sign_in(db, app_client, Role.MANAGER)
    who = db.execute(select(User.id)).scalars().first()
    assert who is not None
    card_id = _завести(db, org, who)
    db.commit()

    def упасть(_db: object, **_kwargs: object) -> object:
        raise RuntimeError("база портала недоступна")

    monkeypatch.setattr(cards_router.start, "ensure", упасть)

    answer = app_client.post(f"/api/cards/{card_id}/move", json={"to": "discussion", "reason": ""})

    assert answer.status_code == 200
    assert answer.json()["status"] == "discussion"


def test_fail_istoriya_otdayotsya_s_sobytiyami(db: DbSession, app_client: TestClient) -> None:
    """Лента отдаётся целиком, с настоящими событиями.

    Проверяется на непустой истории, и это существенно: поля перехода были
    добавлены в таблицу и в схему ответа, но не в слой между ними. На пустой
    ленте всё сходилось — сравнивать было нечего, — а первый же заведённый лот
    отдавал пятисотую.
    """
    from tests.conftest import sign_in

    org = sign_in(db, app_client, Role.MANAGER)
    who = db.execute(select(User.id)).scalars().first()
    assert who is not None
    card_id = _завести(db, org, who)
    cards.move(
        db,
        organization_id=org.id,
        card_id=card_id,
        role=Role.MANAGER,
        user_id=who,
        to=LotStatus.ANALYSIS,
    )
    db.commit()

    answer = app_client.get(f"/api/cards/{card_id}/history")

    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert len(body["events"]) >= 2, "Взятие в работу и перевод обязаны быть в ленте"

    moved = next(item for item in body["events"] if item["kind"] == "moved")
    assert moved["to_status"] == "analysis"
    assert moved["from_status"] == "new"
    assert moved["by_machine"] is False

    # Сводка по людям: по ней делят премию, и считает её сервер.
    assert body["workers"], "Человек, работавший над лотом, обязан быть в сводке"
    assert body["workers"][0]["actions"] >= 2

    # Этапы: сколько лот простоял на каждом. Без них не видно, где застряло.
    assert [stage["status"] for stage in body["stages"]] == ["new", "analysis"]
    assert body["stages"][-1]["running"] is True


def test_fail_zadacha_ne_zakryvayetsya_bez_otchyota(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Закрыть задачу без отчёта нельзя.

    Поле было в базе с самого начала, но его никто не спрашивал, и в истории
    оставалось только «закрыл»: ни премию посчитать, ни спросить, что именно
    нашли. Дверей у закрытия две — окно в карточке и «Мои задачи», — поэтому
    проверка стоит в службе: на экране её обошла бы вторая дверь.
    """
    card_id = _завести(db, org, кто)
    task = cards.add_task(
        db,
        organization_id=org.id,
        card_id=card_id,
        title="Найти поставщика",
        department=Department.SUPPLY,
        created_by=кто,
    )

    for пусто in ("", "   "):
        with pytest.raises(SpokenError, match="Напишите, что сделано"):
            cards.close_task(
                db,
                organization_id=org.id,
                task_id=task.id,
                state=TaskState.DONE,
                result=пусто,
                user_id=кто,
            )

    закрыта = cards.close_task(
        db,
        organization_id=org.id,
        task_id=task.id,
        state=TaskState.DONE,
        result="Нашли поставщика, цена подтверждена",
        user_id=кто,
    )
    assert закрыта.state is TaskState.DONE
    assert закрыта.result == "Нашли поставщика, цена подтверждена"


def test_fail_vernut_v_rabotu_mozhno_bez_otchyota(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Возврат в работу отчёта не требует.

    Объяснять там нечего: задача не сделана, и это видно по её состоянию.
    Требовать отчёт и здесь значило бы заставлять писать «передумал» ради
    того, чтобы система пропустила нажатие.
    """
    card_id = _завести(db, org, кто)
    task = cards.add_task(
        db,
        organization_id=org.id,
        card_id=card_id,
        title="Проверить",
        department=Department.SUPPLY,
        created_by=кто,
    )
    cards.close_task(
        db,
        organization_id=org.id,
        task_id=task.id,
        state=TaskState.DONE,
        result="проверено",
        user_id=кто,
    )

    снова = cards.close_task(
        db, organization_id=org.id, task_id=task.id, state=TaskState.OPEN, user_id=кто
    )

    assert снова.state is TaskState.OPEN


def test_fail_ubrannaya_papka_ne_unosit_fayly(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Папку убирают, файлы остаются.

    Снабжение складывает в папку переписку с китайским поставщиком: снимки
    экрана из WeChat, договор, счёт. Папка — способ разложить, а не второе
    хранилище, и её удаление вместе с содержимым однажды унесло бы
    единственный экземпляр договора. Файлы возвращаются в корень, и сколько
    их вернулось — говорится числом.
    """
    from platform_api.db.models import StoredFile

    card_id = _завести(db, org, кто)
    папка = cards.make_folder(
        db, organization_id=org.id, card_id=card_id, name="Поставщик Шэньчжэнь", by=кто
    )
    файл = StoredFile(
        organization_id=org.id,
        original_name="договор.pdf",
        sha256="b" * 64,
        size_bytes=2048,
    )
    db.add(файл)
    db.flush()
    cards.attach(
        db,
        organization_id=org.id,
        card_id=card_id,
        file_id=файл.id,
        added_by=кто,
        folder_id=папка.id,
    )

    assert [
        (item.name, item.files)
        for item in cards.folders(db, organization_id=org.id, card_id=card_id)
    ] == [("Поставщик Шэньчжэнь", 1)]

    вернулось = cards.drop_folder(db, organization_id=org.id, folder_id=папка.id)

    assert вернулось == 1
    assert cards.folders(db, organization_id=org.id, card_id=card_id) == []
    остались = cards.files(db, organization_id=org.id, card_id=card_id)
    assert [item.name for item in остались] == ["договор.pdf"]
    assert остались[0].folder_id == ""


def test_fail_papka_s_tem_zhe_imenem_ne_zavoditsya(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Две «Переписки» в одном лоте — это две папки, в которые кладут наугад."""
    card_id = _завести(db, org, кто)
    cards.make_folder(db, organization_id=org.id, card_id=card_id, name="Переписка", by=кто)

    with pytest.raises(SpokenError):
        cards.make_folder(db, organization_id=org.id, card_id=card_id, name=" Переписка ", by=кто)


def test_fail_progon_dvigaet_lot_tolko_vperyod(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Досчитавшийся разбор не откатывает лот назад.

    Разбор спецификации идёт минутами, и за это время менеджер успевает
    отправить лот на согласование. Прогон, выставляющий «На разборе» по факту
    своего завершения, стёр бы этот перевод — человек увидел бы лот там, откуда
    он его уже убрал, и подписи собирал бы заново.
    """
    _завести(db, org, кто)
    card = _карточка(db, org)

    assert cards.advance(db, card=card, to=LotStatus.ANALYSIS, why="разбор собран") is True
    assert card.status is LotStatus.ANALYSIS

    card.status = LotStatus.APPROVAL
    assert cards.advance(db, card=card, to=LotStatus.ANALYSIS, why="разбор собран") is False
    assert card.status is LotStatus.APPROVAL


def test_fail_soshedshiy_s_distantsii_progonom_ne_dvigaetsya(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """«Не участвуем» — решение человека, и фоновая задача его не пересматривает."""
    _завести(db, org, кто)
    card = _карточка(db, org)
    card.status = LotStatus.SKIPPED

    assert cards.advance(db, card=card, to=LotStatus.DISCUSSION, why="замечание готово") is False
    assert card.status is LotStatus.SKIPPED


def test_fail_tot_zhe_fayl_v_druguyu_papku_pereezzhaet_i_govorit_ob_etom(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Повторная загрузка того же содержимого в другую папку переносит файл.

    Переносит, а не заводит вторую запись: в папке «Скрины» и в папке «ТС»
    лежал бы один и тот же документ двумя строками, и человек, убравший одну,
    считал бы убранными обе.

    Но молчать о переносе нельзя. Файл исчезает оттуда, где лежал, и на экране
    это выглядит пропажей — тем более что сравнивается содержимое, а не имя:
    два разных документа, названных одинаково, остались бы двумя.
    """
    from platform_api.db.models import StoredFile

    card_id = _завести(db, org, кто)
    скрины = cards.make_folder(db, organization_id=org.id, card_id=card_id, name="Скрины", by=кто)
    тс = cards.make_folder(db, organization_id=org.id, card_id=card_id, name="ТС", by=кто)
    файл = StoredFile(
        organization_id=org.id,
        original_name="Resume.pdf",
        sha256="c" * 64,
        size_bytes=160_000,
    )
    db.add(файл)
    db.flush()

    cards.attach(
        db,
        organization_id=org.id,
        card_id=card_id,
        file_id=файл.id,
        added_by=кто,
        folder_id=скрины.id,
    )
    снова = cards.attach(
        db,
        organization_id=org.id,
        card_id=card_id,
        file_id=файл.id,
        added_by=кто,
        folder_id=тс.id,
    )

    assert снова.known is True
    assert снова.moved is True
    assert снова.moved_from == "Скрины"
    приложено = cards.files(db, organization_id=org.id, card_id=card_id)
    assert len(приложено) == 1
    assert приложено[0].folder_id == str(тс.id)


def test_fail_odinakovye_imena_s_raznym_soderzhimym_ostayutsya_dvumya(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """«Тот же файл» — это то же содержимое, а не то же имя.

    Счёт от двух поставщиков оба зовутся `invoice.pdf`, и схлопнуть их по имени
    значит потерять один: в заявку уйдёт цена не того. Байты разные — записи
    разные, даже если в списке они выглядят близнецами.
    """
    from platform_api.db.models import StoredFile

    card_id = _завести(db, org, кто)
    первый = StoredFile(
        organization_id=org.id, original_name="invoice.pdf", sha256="d" * 64, size_bytes=1000
    )
    второй = StoredFile(
        organization_id=org.id, original_name="invoice.pdf", sha256="e" * 64, size_bytes=2000
    )
    db.add_all([первый, второй])
    db.flush()

    cards.attach(db, organization_id=org.id, card_id=card_id, file_id=первый.id, added_by=кто)
    ещё = cards.attach(db, organization_id=org.id, card_id=card_id, file_id=второй.id, added_by=кто)

    assert ещё.known is False
    приложено = cards.files(db, organization_id=org.id, card_id=card_id)
    assert [item.name for item in приложено] == ["invoice.pdf", "invoice.pdf"]
    assert len({item.sha256 for item in приложено}) == 2


def test_fail_zagruzka_govorit_pro_perenos(db: DbSession, app_client: TestClient) -> None:
    """Ответ на загрузку рассказывает, что файл уже был и переехал.

    Через HTTP, а не только в службе: молчащий ответ и есть та поломка, из-за
    которой человек считает файл пропавшим — он клал его в «ТС», а исчез он из
    «Скринов». Сравнение идёт по содержимому, и сказать об этом должен сервер:
    браузер байтов чужой загрузки не видел.
    """
    from tests.conftest import sign_in

    org = sign_in(db, app_client, Role.MANAGER)
    card = cards.open_card(
        db,
        organization_id=org.id,
        module="goszakup",
        row_id="лот-с-папками",
        snapshot=cards.Snapshot(code="GZ000777", title="Компьютеры"),
    )
    db.commit()

    скрины = app_client.post(f"/api/cards/{card.id}/folders", json={"name": "Скрины"})
    assert скрины.status_code == 201, скрины.text
    тс = app_client.post(f"/api/cards/{card.id}/folders", json={"name": "ТС"})
    assert тс.status_code == 201, тс.text

    содержимое = ("%PDF-1.4 то же самое содержимое " * 20).encode()
    первый = app_client.post(
        f"/api/cards/{card.id}/files",
        files={"file": ("Resume.pdf", содержимое, "application/pdf")},
        data={"folder_id": скрины.json()["id"]},
    )
    assert первый.status_code == 201, первый.text
    # Обычная загрузка проходит молча: файл виден в списке, и подпись под ним
    # ничего не добавляет.
    assert первый.json()["notice"] == ""

    второй = app_client.post(
        f"/api/cards/{card.id}/files",
        files={"file": ("Resume_копия.pdf", содержимое, "application/pdf")},
        data={"folder_id": тс.json()["id"]},
    )
    assert второй.status_code == 201, второй.text
    сказано = второй.json()["notice"]
    assert "Resume.pdf" in сказано
    assert "Скрины" in сказано
    assert "побайтно" in сказано

    файлы = app_client.get(f"/api/cards/{card.id}/files").json()
    assert len(файлы) == 1
    assert файлы[0]["folder_id"] == тс.json()["id"]
    # В списке рассказывать не о чем — поля там нет вовсе.
    assert "notice" not in файлы[0]


def test_fail_knopka_prilozhit_ne_vynimaet_fayl_iz_papki(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Загрузка без выбранной папки не трогает того, кто уже лежит в папке.

    «Приложить» в шапке вкладки говорит «к лоту», а не «в общий список».
    Вынимать ею файлы из папок значило бы разбирать раскладку случайным
    нажатием: человек грузит счёт второй раз, не помня, что он уже в папке
    поставщика, — и находит его вывалившимся в общий список.

    Промолчать при этом тоже нельзя: в том месте, куда человек смотрит, файл
    не появится, и это выглядит как несработавшая загрузка. Где он лежит,
    сказано в ответе.
    """
    from platform_api.db.models import StoredFile

    card_id = _завести(db, org, кто)
    папка = cards.make_folder(db, organization_id=org.id, card_id=card_id, name="Счета", by=кто)
    файл = StoredFile(
        organization_id=org.id, original_name="счёт.pdf", sha256="f" * 64, size_bytes=100
    )
    db.add(файл)
    db.flush()
    cards.attach(
        db,
        organization_id=org.id,
        card_id=card_id,
        file_id=файл.id,
        added_by=кто,
        folder_id=папка.id,
    )

    снова = cards.attach(
        db, organization_id=org.id, card_id=card_id, file_id=файл.id, added_by=кто, folder_id=None
    )

    assert снова.moved is False
    assert снова.folder == "Счета"
    приложено = cards.files(db, organization_id=org.id, card_id=card_id)
    assert [item.folder_id for item in приложено] == [str(папка.id)]
