"""Переписка по строке: кого зовёт упоминание.

Проверяется то, ради чего упоминание и заводили: позванный узнаёт о реплике.
Ошибка здесь тихая — сообщение отправлено, выглядит доставленным, и человек
неделю ждёт ответа от того, кому ничего не пришло.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest
from platform_api.db.models import Membership, Organization, Role, User
from platform_api.modules import discussion, notify

if TYPE_CHECKING:
    from platform_api.config import Settings
    from sqlalchemy.orm import Session as DbSession


@pytest.fixture
def позвали(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Перехватывает заявки в сервис уведомлений.

    Перехват на `notify.about`, а не на HTTP: проверяется решение «кого
    позвать», а не то, как заявка уходит по сети, — за второе отвечает сам
    `notify` и его собственная проверка.
    """
    заявки: list[dict[str, Any]] = []

    def запомнить(_settings: Settings, **kwargs: Any) -> bool:
        заявки.append(kwargs)
        return True

    monkeypatch.setattr(notify, "about", запомнить)
    return заявки


def _человек(db: DbSession, org: Organization, *, active: bool = True) -> User:
    user = User(
        email=f"{uuid.uuid4().hex[:8]}@fintend.kz",
        password_hash="x",
        full_name="Айша Тлеубаева",
        is_active=active,
    )
    db.add(user)
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role=Role.LAWYER))
    db.flush()
    return user


@pytest.fixture
def org(db: DbSession) -> Organization:
    found = Organization(name="Fintend", slug=f"fintend-{uuid.uuid4().hex[:6]}")
    db.add(found)
    db.flush()
    return found


def test_упомянутого_зовут(
    db: DbSession, settings: Settings, org: Organization, позвали: list[dict[str, Any]]
) -> None:
    автор = _человек(db, org)
    коллега = _человек(db, org)

    сообщение = discussion.add(
        db,
        org.id,
        автор.id,
        module="goszakup",
        row_id="81468165-ЗЦП1",
        body="@Айша Тлеубаева, посмотрите пункт 4.2",
        mentions=[str(коллега.id)],
        settings=settings,
    )

    assert сообщение.mentions == [str(коллега.id)]
    assert len(позвали) == 1
    assert позвали[0]["users"] == [коллега.id]
    # Текст уходит вместе с заявкой: половина реплик отвечается одной строкой,
    # и открывать ради неё платформу человек не должен.
    assert "пункт 4.2" in позвали[0]["body_text"]


def test_себя_не_зовут(
    db: DbSession, settings: Settings, org: Organization, позвали: list[dict[str, Any]]
) -> None:
    автор = _человек(db, org)

    сообщение = discussion.add(
        db,
        org.id,
        автор.id,
        module="goszakup",
        row_id="81468165-ЗЦП1",
        body="@Айша Тлеубаева сам себе",
        mentions=[str(автор.id)],
        settings=settings,
    )

    assert сообщение.mentions == []
    assert позвали == []


def test_чужого_из_другой_организации_не_зовут(
    db: DbSession, settings: Settings, org: Organization, позвали: list[dict[str, Any]]
) -> None:
    """Идентификатор из браузера не даёт права звать кого угодно.

    Подставленный чужой идентификатор означал бы уведомление о нашей закупке
    человеку из другой компании — и по тексту реплики он узнал бы о ней больше,
    чем из любого экрана.
    """
    другая = Organization(name="Чужая", slug=f"other-{uuid.uuid4().hex[:6]}")
    db.add(другая)
    db.flush()
    автор = _человек(db, org)
    чужой = _человек(db, другая)

    сообщение = discussion.add(
        db,
        org.id,
        автор.id,
        module="goszakup",
        row_id="81468165-ЗЦП1",
        body="@Кто-то",
        mentions=[str(чужой.id)],
        settings=settings,
    )

    assert сообщение.mentions == []
    assert позвали == []


def test_всех_зовут_кроме_автора_и_выключенных(
    db: DbSession, settings: Settings, org: Organization, позвали: list[dict[str, Any]]
) -> None:
    автор = _человек(db, org)
    коллега = _человек(db, org)
    уволенный = _человек(db, org, active=False)

    сообщение = discussion.add(
        db,
        org.id,
        автор.id,
        module="goszakup",
        row_id="81468165-ЗЦП1",
        body="@all смотрим все",
        mentions=[discussion.EVERYONE],
        settings=settings,
    )

    # В самой реплике остаётся слово, а не список людей: позвали всех, а не тех
    # двоих, кто работал в организации в этот вторник.
    assert сообщение.mentions == [discussion.EVERYONE]
    кому = set(позвали[0]["users"])
    assert коллега.id in кому
    assert автор.id not in кому
    assert уволенный.id not in кому


def test_правка_зовёт_только_дописанного(
    db: DbSession, settings: Settings, org: Organization, позвали: list[dict[str, Any]]
) -> None:
    """Повторное уведомление по той же реплике читается как второе сообщение.

    Правка через минуту после отправки — обычный ход: имя забывают поставить
    так же часто, как ошибаются в тексте.
    """
    автор = _человек(db, org)
    первый = _человек(db, org)
    второй = _человек(db, org)

    сообщение = discussion.add(
        db,
        org.id,
        автор.id,
        module="goszakup",
        row_id="81468165-ЗЦП1",
        body="@Айша Тлеубаева посмотрите",
        mentions=[str(первый.id)],
        settings=settings,
    )
    позвали.clear()

    discussion.edit(
        db,
        org.id,
        автор.id,
        uuid.UUID(сообщение.id),
        "@Айша Тлеубаева @Айша Тлеубаева посмотрите оба",
        mentions=[str(первый.id), str(второй.id)],
        settings=settings,
    )

    assert len(позвали) == 1
    assert позвали[0]["users"] == [второй.id]
