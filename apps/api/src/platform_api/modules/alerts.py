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

from sqlalchemy.orm import Session as DbSession

from platform_api.config import Settings
from platform_api.db.models import Department, LotCard, Task
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


__all__ = ["TAKEN_DESKS", "lot_opened", "task_added", "task_closed"]
