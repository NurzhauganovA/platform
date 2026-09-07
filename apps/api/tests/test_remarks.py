"""Замечания к спецификации: переходы, права и сроки.

Проверяется прежде всего необратимое. Отправка уходит заказчику, и ошибка в
правиле «кто и когда может отправить» стоит письма от имени компании, которое
никто не читал.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from platform_api.db.base import utcnow
from platform_api.db.models import (
    DiscussionOutcome,
    DiscussionStage,
    DiscussionWriting,
    Organization,
    Role,
    User,
)
from platform_api.errors import SpokenError
from platform_api.modules import remarks

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
    """Настоящий человек в базе.

    Выдуманный идентификатор здесь не годится: ответственный и правивший
    хранятся внешними ключами, и на случайном UUID падает не проверяемое
    правило, а вставка.
    """
    found = User(email=f"{uuid.uuid4().hex[:8]}@fintend.kz", password_hash="x")
    db.add(found)
    db.flush()
    return found.id


def _завести(
    db: DbSession, org: Organization, *, deadline_in: timedelta | None = timedelta(days=1)
) -> uuid.UUID:
    row = remarks.open_remark(
        db,
        organization_id=org.id,
        module="goszakup",
        row_id="81468165-ЗЦП1",
        subject=remarks.Subject(
            code="GZ000001",
            title="Компьютер (моноблок)",
            customer="ГУ Управление",
            amount=Decimal("8660625"),
            enstru_code="262013.000.000011",
            deadline=utcnow() + deadline_in if deadline_in is not None else None,
        ),
    )
    return row.id


def test_fail_obsuzhdenie_po_lotu_odno(db: DbSession, org: Organization, кто: uuid.UUID) -> None:
    """Кнопку «Обсудить» нажимают дважды.

    Второе нажатие не должно ни падать ошибкой, ни заводить второе замечание
    по тому же лоту: их потом отправят оба, и заказчик получит два письма.
    """
    первое = _завести(db, org)
    второе = _завести(db, org)
    assert первое == второе


def test_fail_pustoe_zamechanie_ne_ukhodit(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Отправленная пустота выглядит для заказчика ошибкой в системе.

    Отвечать он на неё не станет, а срок будет потрачен.
    """
    remark_id = _завести(db, org)
    with pytest.raises(SpokenError, match="пустое"):
        remarks.move(
            db,
            organization_id=org.id,
            remark_id=remark_id,
            role=Role.ANALYST,
            user_id=кто,
            to=DiscussionStage.MODERATION,
        )


def test_fail_otpravlennoe_ne_pravitsya_i_ne_vozvrashchaetsya(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Отправка необратима: замечание уже у заказчика.

    «Вернуть на правку» в платформе создало бы у менеджера ложное чувство, что
    оно ещё наше, и он правил бы текст, который заказчик читает в другой
    редакции.
    """
    remark_id = _завести(db, org)
    _написать(db, org, remark_id)
    remarks.move(
        db,
        organization_id=org.id,
        remark_id=remark_id,
        role=Role.ANALYST,
        user_id=кто,
        to=DiscussionStage.MODERATION,
    )
    remarks.move(
        db,
        organization_id=org.id,
        remark_id=remark_id,
        role=Role.LAWYER,
        user_id=кто,
        to=DiscussionStage.SENT,
    )

    with pytest.raises(SpokenError, match="отправлено"):
        remarks.save_text(
            db,
            organization_id=org.id,
            remark_id=remark_id,
            role=Role.ADMIN,
            user_id=кто,
            text="передумали",
        )
    with pytest.raises(SpokenError, match="нельзя перейти"):
        remarks.move(
            db,
            organization_id=org.id,
            remark_id=remark_id,
            role=Role.ADMIN,
            user_id=кто,
            to=DiscussionStage.DRAFTING,
        )


def test_fail_otpravlyaet_ne_kazhdyy(db: DbSession, org: Organization, кто: uuid.UUID) -> None:
    """Подпись под обращением к государственному заказчику — не то право,
    которое даётся заодно с доступом к ценам.

    Отправляют юристы и администратор.
    """
    remark_id = _завести(db, org)
    _написать(db, org, remark_id)
    remarks.move(
        db,
        organization_id=org.id,
        remark_id=remark_id,
        role=Role.ANALYST,
        user_id=кто,
        to=DiscussionStage.MODERATION,
    )
    with pytest.raises(SpokenError, match="вам нельзя"):
        remarks.move(
            db,
            organization_id=org.id,
            remark_id=remark_id,
            role=Role.ANALYST,
            user_id=кто,
            to=DiscussionStage.SENT,
        )


def test_fail_itog_tolko_u_otpravlennogo(db: DbSession, org: Organization, кто: uuid.UUID) -> None:
    """Итог у неотправленного означал бы ответ на письмо, которого заказчик
    не получал."""
    remark_id = _завести(db, org)
    with pytest.raises(SpokenError, match="отправленного"):
        remarks.resolve(
            db,
            organization_id=org.id,
            remark_id=remark_id,
            role=Role.ANALYST,
            outcome=DiscussionOutcome.ACCEPTED,
        )


def test_fail_pravka_ne_zatiraet_napisannoe_modelyu(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Сравнить отправленное с исходным нужно ровно тогда, когда пришёл отказ.

    Именно в этот момент и выясняется, что подлинник затёрли.
    """
    remark_id = _завести(db, org)
    remarks.written(
        db, remark_id=remark_id, text="как написала модель", model="gemini-3.1-pro-preview"
    )
    remarks.save_text(
        db,
        organization_id=org.id,
        remark_id=remark_id,
        role=Role.ANALYST,
        user_id=кто,
        text="как поправил менеджер",
    )
    карточка = remarks.one(
        db,
        organization_id=org.id,
        remark_id=remark_id,
        role=Role.ANALYST,
        user_id=кто,
    )
    assert карточка.ai_text == "как написала модель"
    assert карточка.text == "как поправил менеджер"


def test_fail_povtornyy_progon_ne_steret_pravku(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Задачу перезапускают, когда первая попытка вышла неудачной.

    Вторая не должна стереть то, что менеджер уже успел поправить руками.
    """
    remark_id = _завести(db, org)
    remarks.written(db, remark_id=remark_id, text="первая попытка", model="gemini-3.1-pro-preview")
    remarks.save_text(
        db,
        organization_id=org.id,
        remark_id=remark_id,
        role=Role.ANALYST,
        user_id=кто,
        text="правка менеджера",
    )
    remarks.written(db, remark_id=remark_id, text="вторая попытка", model="gemini-3.1-pro-preview")

    карточка = remarks.one(
        db,
        organization_id=org.id,
        remark_id=remark_id,
        role=Role.ANALYST,
        user_id=кто,
    )
    assert карточка.text == "правка менеджера"
    assert карточка.ai_text == "вторая попытка"


def test_fail_otkaz_modeli_vidno_slovami(db: DbSession, org: Organization, кто: uuid.UUID) -> None:
    """Пустое поле без причины выглядит поломкой платформы, а не решением."""
    remark_id = _завести(db, org)
    remarks.written(
        db,
        remark_id=remark_id,
        text="",
        model="gemini-3.1-pro-preview",
        trouble="Модель занята, попробуйте позже",
    )
    карточка = remarks.one(
        db,
        organization_id=org.id,
        remark_id=remark_id,
        role=Role.ANALYST,
        user_id=кто,
    )
    assert карточка.writing == DiscussionWriting.FAILED.value
    assert "занята" in карточка.trouble


def test_fail_ochered_sortiruetsya_po_sroku(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Наверху те, у кого часы идут; без срока — в конец.

    Не потому что оно неважное, а потому что торопиться по нему некуда, а
    место наверху нужно горящим.
    """
    for номер, срок in (
        ("A", timedelta(days=3)),
        ("B", timedelta(hours=2)),
        ("C", None),
    ):
        remarks.open_remark(
            db,
            organization_id=org.id,
            module="goszakup",
            row_id=f"лот-{номер}",
            subject=remarks.Subject(
                code=f"GZ00000{номер}",
                title="Компьютер",
                deadline=utcnow() + срок if срок is not None else None,
            ),
        )

    очередь = remarks.listing(db, organization_id=org.id, role=Role.ANALYST, user_id=кто)
    assert [item.row_id for item in очередь][:3] == ["лот-B", "лот-A", "лот-C"]
    горит = next(item for item in очередь if item.row_id == "лот-B")
    assert горит.burning and not горит.overdue


def test_fail_proshedshiy_srok_vidno_otdelno(
    db: DbSession, org: Organization, кто: uuid.UUID
) -> None:
    """Просроченное и горящее — разные вещи.

    По первому писать уже поздно, и держать его в общей куче срочных значит
    каждый день пересматривать то, что закрыто.
    """
    remark_id = _завести(db, org, deadline_in=-timedelta(hours=1))
    карточка = remarks.one(
        db,
        organization_id=org.id,
        remark_id=remark_id,
        role=Role.ANALYST,
        user_id=кто,
    )
    assert карточка.overdue and not карточка.burning
    assert карточка.left == "срок прошёл"


def test_fail_knopki_sovpadayut_s_pravami(db: DbSession, org: Organization, кто: uuid.UUID) -> None:
    """Список доступного считает сервер, а не браузер.

    Иначе кнопка есть, а эндпоинт отвечает отказом — самый обидный вид
    поломки: человек уверен, что сделал.
    """
    remark_id = _завести(db, org)
    _написать(db, org, remark_id)
    remarks.move(
        db,
        organization_id=org.id,
        remark_id=remark_id,
        role=Role.ANALYST,
        user_id=кто,
        to=DiscussionStage.MODERATION,
    )

    тендерщик = remarks.one(
        db,
        organization_id=org.id,
        remark_id=remark_id,
        role=Role.ANALYST,
        user_id=кто,
    )
    юрист = remarks.one(
        db, organization_id=org.id, remark_id=remark_id, role=Role.LAWYER, user_id=кто
    )
    закупщик = remarks.one(
        db, organization_id=org.id, remark_id=remark_id, role=Role.BUYER, user_id=кто
    )

    assert DiscussionStage.SENT.value not in тендерщик.can
    assert DiscussionStage.SENT.value in юрист.can
    assert закупщик.can == ()


def _написать(db: DbSession, org: Organization, remark_id: uuid.UUID) -> None:
    remarks.written(
        db,
        remark_id=remark_id,
        text="Заказчик указал конкретный бренд в нарушение пункта 412 Правил.",
        model="gemini-3.1-pro-preview",
    )


def test_fail_ochered_vidna_tomu_komu_polozheno(db: DbSession, app_client: TestClient) -> None:
    """Замечание к документации — не работа закупщика, и адрес ему закрыт.

    Проверяется на эндпоинте, а не спрятанной кнопкой: спрятать и оставить
    открытым адрес — самый ходовой способ отдать наружу то, что не
    полагается.

    Юрист наоборот: очередь ему открыта, хотя рабочие списки с ценами закрыты.
    За обращением к заказчику стоят требования спецификации, а не наша
    себестоимость.
    """
    from tests.conftest import sign_in

    org = sign_in(db, app_client, Role.BUYER)
    _завести_для(db, org)
    assert app_client.get("/api/remarks").status_code == 403

    sign_in(db, app_client, Role.LAWYER)
    открыто = app_client.get("/api/remarks")
    assert открыто.status_code == 200


def test_fail_otpravka_cherez_api_tolko_yuristu(db: DbSession, app_client: TestClient) -> None:
    """Тендерщику эндпоинт отправки отвечает отказом, а не молча пропускает."""
    from tests.conftest import sign_in

    org = sign_in(db, app_client, Role.ANALYST)
    remark_id = _завести_для(db, org)
    remarks.written(
        db,
        remark_id=remark_id,
        text="Заказчик указал конкретный бренд в нарушение пункта 412 Правил.",
        model="gemini-3.1-pro-preview",
    )
    db.commit()

    отказ = app_client.post(f"/api/remarks/{remark_id}/move", json={"to": "sent"})
    assert отказ.status_code == 403
    assert "нельзя" in отказ.json()["detail"]


def test_fail_chuzhaya_organizatsiya_ne_vidna(db: DbSession, app_client: TestClient) -> None:
    """Обсуждение соседней организации не открывается по прямой ссылке."""
    from tests.conftest import sign_in

    чужая = Organization(name="Другая", slug=f"other-{uuid.uuid4().hex[:6]}")
    db.add(чужая)
    db.flush()
    remark_id = _завести_для(db, чужая)

    sign_in(db, app_client, Role.ANALYST)
    ответ = app_client.get(f"/api/remarks/{remark_id}")
    assert ответ.status_code == 404


def _завести_для(db: DbSession, org: Organization) -> uuid.UUID:
    row = remarks.open_remark(
        db,
        organization_id=org.id,
        module="goszakup",
        row_id=f"лот-{uuid.uuid4().hex[:6]}",
        subject=remarks.Subject(
            code="GZ000001",
            title="Компьютер",
            deadline=utcnow() + timedelta(days=1),
        ),
    )
    db.commit()
    return row.id


def test_fail_model_ne_zovut_dvazhdy_za_odno_obsuzhdenie(db: DbSession, org: Organization) -> None:
    """Повторный заход в «Обсуждение» не заказывает написание второй раз.

    На доску приходят перетаскиванием, и лот легко поводить туда-обратно между
    колонками. Каждый заход — это платный вызов модели и затёртый текст,
    который до этого правили руками.
    """
    from platform_api.db.models import Job, JobStatus
    from platform_api.modules.goszakup.start import _needs_writing
    from platform_api.modules.remarks import Subject, open_remark

    remark = open_remark(
        db,
        organization_id=org.id,
        module="goszakup",
        row_id="99999999-ЗЦП1",
        subject=Subject(
            code="GZ000999",
            title="Моноблок",
            customer="ГУ Управление",
            amount=None,
            enstru_code="262013.000.000011",
            category="Компьютеры",
            deadline=None,
        ),
    )
    db.flush()

    assert _needs_writing(db, org.id, remark) is True, "Первый заход обязан позвать модель"

    db.add(
        Job(
            organization_id=org.id,
            module="goszakup",
            kind="remark",
            params={"remark_id": str(remark.id)},
            status=JobStatus.RUNNING,
        )
    )
    db.flush()
    assert _needs_writing(db, org.id, remark) is False, "Написание уже идёт"

    # Написанное руками тоже не переписываем: текст важнее свежести.
    remark.text = "Требование сужает круг участников до одного поставщика."
    db.flush()
    assert _needs_writing(db, org.id, remark) is False


def test_fail_srok_obsuzhdeniya_schitaetsya_ot_publikacii() -> None:
    """Два рабочих дня со дня публикации, выходные не в счёт.

    Портал в открытой части оба своих поля обсуждения отдаёт пустыми — и у
    запроса ценовых предложений, и у конкурса, проверено на живых
    объявлениях. Раньше вместо них подставлялось окончание приёма заявок, и
    «осталось» показывало неделю там, где на замечание оставался день.
    """
    from datetime import UTC, datetime

    from platform_api.modules.goszakup.start import discussion_deadline

    class Лот:
        discussion_end = None
        end_date = datetime(2026, 9, 30, tzinfo=UTC)
        published_at = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)  # понедельник

    assert discussion_deadline(Лот()).day == 9  # среда

    # Пятница: два рабочих дня — это вторник, а не воскресенье.
    Лот.published_at = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)
    assert discussion_deadline(Лот()).day == 8


def test_fail_zapolnennyy_srok_portala_glavnee_rascheta() -> None:
    """Свой расчёт — замена, а не правило: заполнит портал, поверим порталу."""
    from datetime import UTC, datetime

    from platform_api.modules.goszakup.start import discussion_deadline

    class Лот:
        discussion_end = datetime(2026, 9, 15, tzinfo=UTC)
        end_date = datetime(2026, 9, 30, tzinfo=UTC)
        published_at = datetime(2026, 9, 7, tzinfo=UTC)

    assert discussion_deadline(Лот()).day == 15


def test_fail_slova_etapov_v_kartochke_te_zhe() -> None:
    """Карточка повторяет пять слов `remarks`, и они должны совпадать.

    Разошедшись, они дадут «На проверке» в разделе обсуждений и другое слово
    в правом столбце карточки по тому же лоту — и человек решит, что это
    разные обсуждения.
    """
    from platform_api.modules import cards, remarks

    assert cards.DISCUSSION_STAGE_NAMES == remarks.STAGE_NAMES
