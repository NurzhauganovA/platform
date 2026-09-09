"""Кого и о чём оповещает платформа.

Между обработчиками и сервисом уведомлений (`notify.py`). Тот умеет одно —
отнести заявку; здесь решается, что произошло, кого это касается и какая
ссылка ведёт к делу.

Отдельным файлом, а не строками по месту. Оповещение — это выбор получателей,
и выбор этот повторяется: «отделу разбора», «исполнителю, а если его нет — то
отделу». Разложенный по десятку обработчиков, он расходится за месяц: в одном
месте забыли администратора, в другом позвали наблюдателя.

Зовётся из служб, а не из обработчиков HTTP — по той же причине, по которой из
служб пишется лента событий: задача, заведённая прогоном, — тоже работа над
лотом, и человек должен узнать о ней так же, как о заведённой руками.

Ссылка обязательна везде, где есть куда вести. Уведомление без неё заставляет
искать лот руками — а приходит оно в тот момент, когда человек занят другим.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from platform_api.config import Settings
from platform_api.db.models import Department, LotCard, Membership, Task, User
from platform_api.logging import get_logger
from platform_api.modules import notify

logger = get_logger(__name__)

TAKEN_DESKS = (Department.ANALYSIS, Department.DISCUSSION)
"""Кого звать на взятый в работу лот.

Разбор считает себестоимость и решает, участвовать ли; обсуждение пишет
замечание к спецификации — и у него срок в два рабочих дня со дня публикации,
то есть короче всех остальных. Оба начинают с одного лота, и узнать о нём
должны в один и тот же момент.
"""


def lot_opened(db: DbSession, settings: Settings, card: LotCard) -> None:
    """Лот взяли в работу — зовём разбор и обсуждение.

    Одной заявкой на всех: пять запросов вместо одного — это пять поводов для
    сервиса ответить отказом на середине.

    Ключ повтора собран из лота, а не из времени: карточка заводится и руками,
    и выборкой по номеру, и оба пути идут через одну службу. Второй заход по
    тому же лоту не должен звать людей дважды.
    """
    from platform_api.modules.cards import people_of

    people: set[uuid.UUID] = set()
    for desk in TAKEN_DESKS:
        people.update(people_of(db, card.organization_id, desk))
    # Тому, кто лот и взял, сообщать нечего: он смотрит на него прямо сейчас.
    if card.owner_id:
        people.discard(card.owner_id)
    if not people:
        return

    notify.about(
        settings,
        event="lot.assigned",
        title="Новый лот в работе",
        body_text=_lot_lines(card),
        payload={
            "lot": card.title,
            "number": card.source_number or card.row_id,
            "customer": card.customer,
            "amount": _money(card.amount),
        },
        users=sorted(people),
        url=f"/work/lots/{card.id}",
        deadline=card.deadline.isoformat() if card.deadline else "",
        group=f"lot:{card.id}",
        idempotency_key=f"lot-opened-{card.id}",
    )


def task_added(db: DbSession, settings: Settings, task: Task, card: LotCard) -> None:
    """Задачу завели — зовём исполнителя, а нет его, так весь отдел.

    Отдел, а не тишина: задача без исполнителя лежит в общей очереди, и если о
    ней никому не сказать, её возьмут в тот день, когда о ней спросят.

    Срок уходит вместе с заявкой: сервис сам напомнит за шесть часов до него и
    сам пропустит напоминание сквозь тихие часы. Считать это у себя значило бы
    завести второе место, где написано, что такое «горит».
    """
    from platform_api.modules.cards import DEPARTMENT_NAMES, people_of

    people = (
        [task.assignee_id]
        if task.assignee_id
        else people_of(db, task.organization_id, task.department)
    )
    people = [one for one in people if one is not None]
    if not people:
        return

    notify.about(
        settings,
        event="task.assigned",
        payload={
            "title": task.title,
            "lot": f"{card.code} · {card.title}",
            "department": DEPARTMENT_NAMES.get(task.department, task.department.value),
        },
        users=sorted(set(people)),
        url=f"/work/lots/{card.id}",
        deadline=task.due_at.isoformat() if task.due_at else "",
        group=f"task:{task.id}",
        remind_before_minutes=[360] if task.due_at else None,
        idempotency_key=f"task-added-{task.id}",
    )


def task_taken(db: DbSession, settings: Settings, task: Task) -> None:
    """Задачу взяли — говорим отделу, кто и к какому сроку.

    Отделу, а не только взявшему. Остальные перестают на неё смотреть, и это
    ровно то, ради чего очередь и заводили: без этого двое берутся за одно и
    узнают об этом на планёрке.

    Новый срок уходит вместе с сообщением, и сервис сам напомнит за час до
    него. Час, а не шесть: срок здесь три часа от силы, и напоминание за шесть
    пришло бы раньше самой задачи.
    """
    from platform_api.modules.cards import DEPARTMENT_NAMES, people_of

    card = db.get(LotCard, task.card_id)
    if card is None:
        return

    people = set(people_of(db, task.organization_id, task.department))
    if task.assignee_id:
        people.discard(task.assignee_id)
    if not people:
        return

    who = db.get(User, task.assignee_id) if task.assignee_id else None
    notify.about(
        settings,
        event="task.assigned",
        title="Задачу взяли",
        body_text=(
            f"{task.title}\n"
            f"{card.code} · {card.title}\n"
            f"Взял: {who.full_name or who.email if who else 'сотрудник'}"
        ),
        payload={
            "title": task.title,
            "lot": f"{card.code} · {card.title}",
            "department": DEPARTMENT_NAMES.get(task.department, task.department.value),
        },
        users=sorted(people),
        url=f"/work/lots/{card.id}",
        deadline=task.due_at.isoformat() if task.due_at else "",
        group=f"task:{task.id}",
        remind_before_minutes=[60] if task.due_at else None,
        idempotency_key=f"task-taken-{task.id}",
    )


def mentioned(
    db: DbSession,
    settings: Settings,
    *,
    organization_id: uuid.UUID,
    module: str,
    row_id: str,
    author: User | None,
    text: str,
    mentions: list[str],
    message_id: uuid.UUID,
) -> None:
    """В переписке позвали по имени — говорим тому, кого позвали.

    Ради этого упоминание и заводили: «@Айша, посмотри пункт 4.2» без
    уведомления — надежда на то, что Айша зайдёт в ветку сама, а заходят в неё
    тогда, когда о ней напомнили.

    Текст уходит целиком, а не одним «вас упомянули». Половина реплик отвечается
    одной строкой, и человек, прочитавший вопрос в уведомлении, отвечает на
    него сразу; уведомление без текста заставляет открыть платформу, чтобы
    узнать, стоило ли её открывать.

    Ссылка ведёт на карточку лота, если он заведён. Не заведён — ссылки нет: та,
    что ведёт в пустоту, хуже отсутствующей.
    """
    from platform_api.modules.discussion import EVERYONE

    people = _mentioned_people(db, organization_id, mentions, author)
    if not people:
        return

    card = _card_of(db, organization_id, module, row_id)
    who = author.full_name or author.email if author else "Коллега"
    where = f"{card.code} · {card.title}" if card else row_id
    everyone = EVERYONE in mentions

    notify.about(
        settings,
        event="discussion.mention",
        title="Вас позвали в переписке" if not everyone else "Позвали всех в переписке",
        body_text=f"{who} · {where}\n\n{_short(text)}",
        payload={"author": who, "lot": where, "text": _short(text)},
        users=sorted(people),
        url=f"/work/lots/{card.id}" if card else "",
        group=f"chat:{module}:{row_id}",
        # Ключ по реплике: одно сообщение зовёт человека один раз, сколько бы
        # раз обработчик ни повторился.
        idempotency_key=f"chat-mention-{message_id}",
    )


def _mentioned_people(
    db: DbSession,
    organization_id: uuid.UUID,
    mentions: list[str],
    author: User | None,
) -> set[uuid.UUID]:
    """Кому уходит уведомление. `all` — всем действующим, кроме автора."""
    from platform_api.modules.discussion import EVERYONE

    people: set[uuid.UUID] = set()
    for one in mentions:
        if one == EVERYONE:
            continue
        try:
            people.add(uuid.UUID(one))
        except ValueError:
            continue

    if EVERYONE in mentions:
        # Действующие: уволившийся продолжал бы получать разговоры о наших
        # закупках, и заметили бы это не скоро.
        people.update(
            db.scalars(
                select(User.id)
                .join(Membership, Membership.user_id == User.id)
                .where(
                    Membership.organization_id == organization_id,
                    User.is_active.is_(True),
                )
            )
        )

    if author is not None:
        people.discard(author.id)
    return people


def _card_of(db: DbSession, organization_id: uuid.UUID, module: str, row_id: str) -> LotCard | None:
    """Карточка лота по строке. Нет — переписка идёт по строке списка."""
    return db.scalars(
        select(LotCard)
        .where(
            LotCard.organization_id == organization_id,
            LotCard.module == module,
            LotCard.row_id == row_id,
        )
        .limit(1)
    ).first()


def _short(text: str) -> str:
    """Реплика в уведомлении. Длинную обрезаем: в списке чатов её всё равно
    видно на три строки, а дочитывают её на самой странице."""
    clean = " ".join(text.split())
    return clean if len(clean) <= 300 else f"{clean[:299]}…"


def task_closed(settings: Settings, task: Task) -> None:
    """Задача закрыта — гасим напоминания о её сроке.

    Напоминание о закрытой вчера задаче обесценивает всю рассылку: на второй
    раз человек перестаёт открывать сообщения бота.
    """
    notify.drop(settings, group=f"task:{task.id}")


def _lot_lines(card: LotCard) -> str:
    """Тело сообщения о лоте: то, по чему решают, браться ли сейчас."""
    rows = [
        f"{card.code} · {card.title}",
        f"Заказчик: {card.customer}" if card.customer else "",
        f"Сумма: {_money(card.amount)} ₸" if card.amount is not None else "",
    ]
    return "\n".join(row for row in rows if row)


def _money(value: Decimal | None) -> str:
    """Сумма разрядами. Восемь цифр подряд человек читает дважды."""
    if value is None:
        return ""
    return f"{int(value):,}".replace(",", " ")


__all__ = [
    "TAKEN_DESKS",
    "lot_opened",
    "mentioned",
    "task_added",
    "task_closed",
    "task_taken",
]
