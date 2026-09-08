"""Замечания к технической спецификации: ход работы и правила переходов.

Замечание — официальное обращение к заказчику до участия в закупке. Мы
указываем на требования, которые сужают круг участников до одного поставщика,
и просим их снять. В интерфейсе раздел называется «Обсуждения» — по названию
окна на портале, куда замечание уходит, и по нему же названа таблица в базе.
Сосед `discussion.py` — про другое: это внутренняя переписка коллег по строке
списка, без заказчика и без сроков.

Обсуждение заводится **только по площадкам закупок**. Тендерный отбор идёт как
шёл, с детальным разбором: закупки туда приходят папкой по почте, обсуждать их
не с кем.

Переходы описаны таблицей, а не проверками по месту. Проверка «если не
отправлено, то можно править» разъезжается по обработчикам, и через полгода
одно место разрешает то, что другое запрещает; хуже всего, что расходятся они
обычно вокруг отправки — то есть вокруг единственного необратимого шага.

Срок жёсткий: на предварительное обсуждение даётся два рабочих дня со дня
размещения объявления. Пропущенный срок закрывает вопрос совсем, поэтому
очередь сортируется по нему, а не по времени заведения.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select

from platform_api.config import Settings
from platform_api.db.base import utcnow
from platform_api.db.models import (
    Department,
    Discussion,
    DiscussionOutcome,
    DiscussionStage,
    DiscussionWriting,
    Role,
    User,
)
from platform_api.errors import SpokenError
from platform_api.logging import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session as DbSession

BURNING = timedelta(hours=6)
"""За сколько до конца обсуждение считается горящим.

Шесть часов, а не сутки: окно обсуждения и так длиной в два рабочих дня, и
метка, загорающаяся сразу, не отличает срочное от обычного. Шесть часов — это
ещё успеть написать, прочитать и отправить.
"""

MAX_TEXT = 40_000
"""Предел длины замечания. Про базу и про здравый смысл разом: текст длиннее
не дочитывает и заказчик, и модель его не писала — значит, вставили файл."""


# Куда можно уйти с каждого этапа. Пустой набор означает конец пути.
#
# Возврат из модерации в написание есть, а из отправленного назад — нет.
# Отправка необратима: замечание уже у заказчика, и «вернуть на правку» в
# платформе создало бы у менеджера ложное чувство, что оно ещё наше.
TRANSITIONS: dict[DiscussionStage, frozenset[DiscussionStage]] = {
    DiscussionStage.DRAFTING: frozenset({DiscussionStage.MODERATION, DiscussionStage.NOT_NEEDED}),
    DiscussionStage.MODERATION: frozenset(
        {
            DiscussionStage.DRAFTING,
            DiscussionStage.WITH_LAWYERS,
            DiscussionStage.SENT,
            DiscussionStage.NOT_NEEDED,
        }
    ),
    DiscussionStage.WITH_LAWYERS: frozenset(
        {DiscussionStage.MODERATION, DiscussionStage.SENT, DiscussionStage.NOT_NEEDED}
    ),
    DiscussionStage.SENT: frozenset(),
    DiscussionStage.NOT_NEEDED: frozenset({DiscussionStage.DRAFTING}),
}

# Кто вправе сделать переход. Роли перечислены набором, а не «не ниже»:
# старшинство подталкивает написать «не ниже закупщика», и закупщик получает
# право отправить заказчику письмо от имени компании.
ALLOWED: dict[DiscussionStage, frozenset[Role]] = {
    DiscussionStage.DRAFTING: frozenset({Role.ADMIN, Role.ANALYST, Role.LAWYER}),
    DiscussionStage.MODERATION: frozenset({Role.ADMIN, Role.ANALYST, Role.LAWYER}),
    DiscussionStage.WITH_LAWYERS: frozenset({Role.ADMIN, Role.ANALYST}),
    DiscussionStage.SENT: frozenset({Role.ADMIN, Role.LAWYER}),
    DiscussionStage.NOT_NEEDED: frozenset({Role.ADMIN, Role.ANALYST, Role.LAWYER}),
}
"""Кто вправе перевести замечание **в** это состояние.

Отправляют юристы и администратор. Тендерщик пишет и проверяет, но наружу от
имени компании не отправляет: подпись под обращением к государственному
заказчику — не то право, которое даётся заодно с доступом к ценам.
"""

STAGE_NAMES: dict[DiscussionStage, str] = {
    DiscussionStage.DRAFTING: "Пишется",
    DiscussionStage.MODERATION: "На проверке",
    DiscussionStage.WITH_LAWYERS: "У юристов",
    DiscussionStage.SENT: "Отправлено",
    DiscussionStage.NOT_NEEDED: "Не требуется",
}

OUTCOME_NAMES: dict[DiscussionOutcome, str] = {
    DiscussionOutcome.WAITING: "Ждём ответа",
    DiscussionOutcome.ACCEPTED: "Приняли",
    DiscussionOutcome.REJECTED: "Отклонили",
    DiscussionOutcome.CLOSED: "Закрыто",
    DiscussionOutcome.COMPLAINT: "Жалоба",
}


@dataclass(frozen=True, slots=True)
class Subject:
    """Снимок закупки на момент заведения.

    Копией, а не ссылкой в базу площадки: список пересобирается при каждой
    выгрузке, а обсуждение должно остаться тем же, по которому его завели.
    """

    code: str
    title: str
    customer: str = ""
    amount: Decimal | None = None
    enstru_code: str = ""
    category: str = ""
    deadline: datetime | None = None


@dataclass(frozen=True, slots=True)
class Remark:
    """Замечание в том виде, в каком его показывают."""

    id: str
    module: str
    row_id: str
    code: str
    title: str
    customer: str
    amount: Decimal | None
    enstru_code: str
    category: str

    stage: str
    stage_name: str
    outcome: str
    outcome_name: str
    writing: str
    trouble: str

    deadline: str
    left: str
    burning: bool
    overdue: bool

    assignee: str
    assignee_id: str
    text: str
    ai_text: str
    ai_model: str
    answer: str
    sent_at: str
    answered_at: str
    can: tuple[str, ...]
    """Что можно сделать дальше именно этому человеку.

    Считается на сервере и приходит в ответе. Иначе список кнопок живёт в
    браузере вторым набором правил, и однажды кнопка есть, а эндпоинт
    отвечает отказом — самый обидный вид поломки: человек уверен, что сделал.
    """


def open_remark(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    module: str,
    row_id: str,
    subject: Subject,
) -> Discussion:
    """Заводит обсуждение по строке. Уже заведённое возвращает как есть.

    Идемпотентно намеренно: кнопку «Обсудить» нажимают дважды, и второе
    нажатие не должно ни падать ошибкой, ни заводить второе замечание по тому
    же лоту.

    Срок при этом обновляется. Это факт о закупке, а не наша пометка: заказчик
    продлевает приём заявок, объявление переопубликовывают, и обсуждение,
    оставшееся со старым сроком, показывает «просрочено» там, где ещё можно
    писать. Остальной снимок не трогаем — он про то, по чему обсуждение
    заводили.
    """
    found = _find(db, organization_id, module, row_id)
    if found is not None:
        if subject.deadline is not None and found.deadline != subject.deadline:
            found.deadline = subject.deadline
            db.flush()
        return found

    found = Discussion(
        organization_id=organization_id,
        module=module,
        row_id=row_id,
        code=subject.code,
        title=subject.title[:2000],
        customer=subject.customer,
        amount=subject.amount,
        enstru_code=subject.enstru_code,
        category=subject.category,
        deadline=subject.deadline,
        stage=DiscussionStage.DRAFTING,
        outcome=DiscussionOutcome.WAITING,
        writing=DiscussionWriting.QUEUED,
    )
    db.add(found)
    db.flush()
    return found


SOON = timedelta(days=3)
"""Что считать «скоро» для отбора по сроку.

Три дня — не круглое число, а граница между «успеваем спокойно» и «надо
садиться сегодня»: окно обсуждения длиной в два рабочих дня, и всё, что
кончается позже, в сегодняшнюю работу не входит.
"""


def _within(when: datetime | None, bucket: str, now: datetime) -> bool:
    """Попадает ли срок в корзину отбора: сегодня, завтра, позже.

    Корзинами, а не выбором даты. Календарь на этом месте требует двух
    нажатий и знания, какое сегодня число; вопрос при этом всегда один — что
    горит сегодня.
    """
    if when is None:
        return bucket == "none"
    days = (when.date() - now.date()).days
    if bucket == "today":
        return days <= 0
    if bucket == "tomorrow":
        return days == 1
    if bucket == "later":
        return days > 1
    return True


def listing(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    role: Role,
    user_id: uuid.UUID,
    module: str | None = None,
    stage: DiscussionStage | None = None,
    outcome: DiscussionOutcome | None = None,
    mine: bool = False,
    burning: bool = False,
    assignee_id: uuid.UUID | None = None,
    unowned: bool = False,
    category: str | None = None,
    enstru_code: str | None = None,
    amount_from: Decimal | None = None,
    amount_to: Decimal | None = None,
    ends: str | None = None,
    now: datetime | None = None,
) -> list[Remark]:
    """Очередь замечаний.

    `ends` — корзина срока окончания: `today`, `tomorrow`, `later`, `none`.
    Корзинами, а не выбором даты: календарь требует двух нажатий и знания,
    какое сегодня число, а вопрос всегда один — что горит сегодня.

    Порядок: сначала те, у кого срок ближе. Замечание без срока идёт в конец —
    не потому что оно неважное, а потому что торопиться по нему некуда, а
    место наверху нужно тем, у кого часы идут.
    """
    moment = now or utcnow()
    query = select(Discussion).where(Discussion.organization_id == organization_id)
    if module:
        query = query.where(Discussion.module == module)
    if stage is not None:
        query = query.where(Discussion.stage == stage)
    if outcome is not None:
        query = query.where(Discussion.outcome == outcome)
    if mine:
        query = query.where(Discussion.assignee_id == user_id)
    if assignee_id is not None:
        query = query.where(Discussion.assignee_id == assignee_id)
    if unowned:
        query = query.where(Discussion.assignee_id.is_(None))
    if category:
        query = query.where(Discussion.category == category)
    if enstru_code:
        query = query.where(Discussion.enstru_code == enstru_code)
    if amount_from is not None:
        query = query.where(Discussion.amount >= amount_from)
    if amount_to is not None:
        query = query.where(Discussion.amount <= amount_to)

    rows = list(db.execute(query).scalars())
    if ends:
        rows = [row for row in rows if _within(row.deadline, ends, moment)]
    # Сортировка в памяти, а не в запросе: строк здесь десятки, а «без срока в
    # конец» на стороне базы пишется по-разному в SQLite и PostgreSQL и
    # однажды разъезжается между проверочной средой и рабочей.
    #
    # По самой дате, а не по её записи строкой. Строки вида
    # «2026-09-01T12:00:00+06:00» и «2026-09-01T07:00:00+00:00» описывают один
    # момент, но по алфавиту вторая раньше первой — и горящее ушло бы вниз.
    rows.sort(key=lambda row: (row.deadline is None, row.deadline or moment))
    people = _people(db, rows)
    found = [_shown(row, people, role=role, user_id=user_id, now=moment) for row in rows]
    if burning:
        found = [item for item in found if item.burning and not item.overdue]
    return found


def one(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    remark_id: uuid.UUID,
    role: Role,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> Remark:
    row = _required(db, organization_id, remark_id)
    return _shown(row, _people(db, [row]), role=role, user_id=user_id, now=now or utcnow())


def save_text(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    remark_id: uuid.UUID,
    role: Role,
    user_id: uuid.UUID,
    text: str,
) -> Discussion:
    """Правка текста замечания.

    Написанное моделью не переписывается: `ai_text` остаётся тем, чем было.
    Сравнить отправленное с исходным нужно ровно тогда, когда пришёл отказ, —
    и именно в этот момент выясняется, что подлинник затёрли.
    """
    row = _required(db, organization_id, remark_id)
    if row.stage is DiscussionStage.SENT:
        raise SpokenError("Замечание уже отправлено, править его нельзя")
    if role not in ALLOWED[row.stage]:
        raise SpokenError("Править замечание на этом этапе вам нельзя")

    clean = text.strip()
    if len(clean) > MAX_TEXT:
        raise SpokenError("Замечание слишком длинное")
    row.text = clean
    row.edited_by_id = user_id
    row.edited_at = utcnow()
    db.flush()
    return row


def move(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    remark_id: uuid.UUID,
    role: Role,
    user_id: uuid.UUID,
    to: DiscussionStage,
    settings: Settings | None = None,
) -> Discussion:
    """Переводит замечание на следующий этап.

    Пустое замечание не уходит наружу: отправить нечего, а отправленная
    пустота выглядит для заказчика как ошибка в системе — и отвечать он на неё
    не станет.

    Передача юристам заводит им задачу. Раньше это был перевод и тишина:
    замечание ложилось в состояние «у юристов», а юрист узнавал о нём, когда
    сам заходил в раздел. Отправляют официально они, срок у обсуждения — два
    рабочих дня, и «узнал, когда зашёл» здесь означает не отправленное вовсе.
    """
    row = _required(db, organization_id, remark_id)
    if to is row.stage:
        return row
    if to not in TRANSITIONS[row.stage]:
        raise SpokenError(
            f"Из состояния «{STAGE_NAMES[row.stage]}» нельзя перейти в «{STAGE_NAMES[to]}»"
        )
    if role not in ALLOWED[to]:
        raise SpokenError(f"Перевести замечание в «{STAGE_NAMES[to]}» вам нельзя")
    # Пустое замечание не уходит дальше проверки. Исключение — «не требуется»
    # и возврат на доработку: у них текста и не должно быть.
    без_текста = {DiscussionStage.NOT_NEEDED, DiscussionStage.DRAFTING}
    if to not in без_текста and not row.text.strip():
        raise SpokenError("Замечание пустое: сначала напишите текст")

    row.stage = to
    if to is DiscussionStage.SENT:
        row.sent_at = utcnow()
        row.outcome = DiscussionOutcome.WAITING
    if to is DiscussionStage.DRAFTING and row.writing is DiscussionWriting.FAILED:
        # Возврат на доработку снимает отметку о неудаче модели: причина
        # осталась в журнале, а в списке она сбивает с толку — замечание
        # пишется человеком, и красная метка означала бы, что оно сломано.
        row.writing = DiscussionWriting.READY
        row.trouble = ""
    if not row.assignee_id:
        row.assignee_id = user_id
    db.flush()
    if to is DiscussionStage.WITH_LAWYERS:
        _ask_lawyers(db, settings, row, by=user_id)
    return row


def _ask_lawyers(
    db: DbSession, settings: Settings | None, row: Discussion, *, by: uuid.UUID
) -> None:
    """Заводит юристам задачу отправить замечание заказчику.

    Задачей, а не одним уведомлением: уведомление читают и забывают, а задача
    остаётся в очереди отдела и видна на его столе, пока её не закроют с
    отчётом. Отправка необратима и делается руками через портал — забытая
    задача здесь стоит участия в закупке.

    Срок у задачи — час на отклик, а не срок обсуждения. Срок обсуждения
    отвечает на «когда поздно отправлять», а задача — на «когда её возьмут», и
    это разные числа: обсуждение живёт два дня, и задача с таким сроком не
    горит вовсе, пока не станет поздно. Взявший назовёт свой срок сам.

    Карточки лота может не быть: замечание заводится и по строке, которую в
    работу не брали. Тогда остаётся уведомление — задача без лота в очереди
    работы бессмысленна, очередь на то и очередь, что каждая запись о чём-то.
    """
    from platform_api.modules import cards

    card = cards.by_row(
        db, organization_id=row.organization_id, module=row.module, row_id=row.row_id
    )
    if card is None:
        if settings is not None:
            _tell_lawyers(db, settings, row)
        return

    try:
        cards.add_task(
            db,
            organization_id=row.organization_id,
            card_id=card.id,
            created_by=by,
            title=f"Отправить замечание заказчику · {row.code}",
            department=Department.LEGAL,
            body=(
                "Замечание проверено менеджером и передано юристам. "
                "Отправка идёт через портал и обратной силы не имеет."
            ),
            settings=settings,
        )
    except Exception as exc:
        # Задача не завелась — перевод всё равно состоялся. Откатывать его
        # значит врать о состоянии замечания, которое юрист уже видит у себя.
        logger.warning("Юристам не завелась задача", remark=str(row.id), error=str(exc))
        if settings is not None:
            _tell_lawyers(db, settings, row)


def _tell_lawyers(db: DbSession, settings: Settings, row: Discussion) -> None:
    """Запасной путь: позвать юристов без задачи, когда завести её не вышло."""
    from platform_api.modules import cards, notify

    people = cards.people_of(db, row.organization_id, Department.LEGAL)
    if not people:
        return
    notify.about(
        settings,
        event="remark.ready",
        payload={"lot": row.title, "number": row.code, "author": ""},
        users=people,
        url=f"/goszakup/remarks/{row.id}",
        deadline=row.deadline.isoformat() if row.deadline else "",
        group=f"remark:{row.id}",
        idempotency_key=f"remark-lawyers-{row.id}",
    )


def resolve(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    remark_id: uuid.UUID,
    role: Role,
    outcome: DiscussionOutcome,
    answer: str = "",
) -> Discussion:
    """Записывает, чем кончилось у заказчика.

    Только для отправленного: итог у неотправленного замечания означал бы, что
    кто-то отметил ответ на письмо, которого заказчик не получал.
    """
    row = _required(db, organization_id, remark_id)
    if row.stage is not DiscussionStage.SENT:
        raise SpokenError("Итог можно записать только у отправленного замечания")
    if role not in {Role.ADMIN, Role.ANALYST, Role.LAWYER}:
        raise SpokenError("Записывать итог обсуждения вам нельзя")

    row.outcome = outcome
    if answer.strip():
        row.answer = answer.strip()[:MAX_TEXT]
    if outcome is not DiscussionOutcome.WAITING:
        row.answered_at = utcnow()
    db.flush()
    return row


def assign(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    remark_id: uuid.UUID,
    assignee_id: uuid.UUID | None,
) -> Discussion:
    """Назначает ответственного. Пусто — снимает.

    Ничьё горящее обсуждение и есть то, что теряется, поэтому в списке видно
    и то и другое.
    """
    row = _required(db, organization_id, remark_id)
    row.assignee_id = assignee_id
    db.flush()
    return row


def written(
    db: DbSession,
    *,
    remark_id: uuid.UUID,
    text: str,
    model: str,
    trouble: str = "",
) -> None:
    """Складывает то, что написала модель.

    Зовётся из фоновой задачи, поэтому без проверки прав: у задачи нет
    человека, от чьего имени спрашивать.

    Текст менеджера не затирается. Задачу перезапускают, когда первая попытка
    вышла неудачной, и вторая не должна стереть то, что менеджер уже успел
    поправить руками.
    """
    row = db.get(Discussion, remark_id)
    if row is None:
        return
    row.ai_model = model
    row.ai_written_at = utcnow()
    row.trouble = trouble
    if trouble and not text:
        row.writing = DiscussionWriting.FAILED
        db.flush()
        return

    row.ai_text = text[:MAX_TEXT]
    row.writing = DiscussionWriting.READY
    if not row.text.strip():
        row.text = row.ai_text
        row.stage = DiscussionStage.MODERATION
    db.flush()


def starting(db: DbSession, *, remark_id: uuid.UUID) -> None:
    """Отмечает, что модель взялась за работу. Видно в списке, пока идёт."""
    row = db.get(Discussion, remark_id)
    if row is not None:
        row.writing = DiscussionWriting.RUNNING
        row.trouble = ""
        db.flush()


def _find(db: DbSession, organization_id: uuid.UUID, module: str, row_id: str) -> Discussion | None:
    return db.execute(
        select(Discussion).where(
            Discussion.organization_id == organization_id,
            Discussion.module == module,
            Discussion.row_id == row_id,
        )
    ).scalar_one_or_none()


def _required(db: DbSession, organization_id: uuid.UUID, remark_id: uuid.UUID) -> Discussion:
    row = db.get(Discussion, remark_id)
    if row is None or row.organization_id != organization_id:
        raise SpokenError("Обсуждение не найдено")
    return row


def _people(db: DbSession, rows: Sequence[Discussion]) -> dict[uuid.UUID, str]:
    """Имена ответственных одним запросом.

    Одним, а не по запросу на строку: список открывают чаще всего, и сотня
    строк превращалась бы в сотню походов в базу за именем, которое почти у
    всех одно и то же.
    """
    wanted = {row.assignee_id for row in rows if row.assignee_id}
    if not wanted:
        return {}
    found = db.execute(select(User).where(User.id.in_(wanted))).scalars()
    return {user.id: (user.full_name or user.email) for user in found}


def _shown(
    row: Discussion,
    people: dict[uuid.UUID, str],
    *,
    role: Role,
    user_id: uuid.UUID,
    now: datetime,
) -> Remark:
    left, burning, overdue = _time_left(row, now)
    return Remark(
        id=str(row.id),
        module=row.module,
        row_id=row.row_id,
        code=row.code,
        title=row.title,
        customer=row.customer,
        amount=row.amount,
        enstru_code=row.enstru_code,
        category=row.category,
        stage=row.stage.value,
        stage_name=STAGE_NAMES[row.stage],
        outcome=row.outcome.value,
        outcome_name=OUTCOME_NAMES[row.outcome],
        writing=row.writing.value,
        trouble=row.trouble,
        deadline=row.deadline.isoformat() if row.deadline else "",
        left=left,
        burning=burning,
        overdue=overdue,
        assignee=people.get(row.assignee_id, "") if row.assignee_id else "",
        assignee_id=str(row.assignee_id) if row.assignee_id else "",
        text=row.text,
        ai_text=row.ai_text,
        ai_model=row.ai_model,
        answer=row.answer,
        sent_at=row.sent_at.isoformat() if row.sent_at else "",
        answered_at=row.answered_at.isoformat() if row.answered_at else "",
        can=_can(row, role=role, user_id=user_id),
    )


def _can(row: Discussion, *, role: Role, user_id: uuid.UUID) -> tuple[str, ...]:
    """Что этому человеку доступно на этом этапе."""
    allowed = [
        stage.value
        for stage in TRANSITIONS[row.stage]
        if role in ALLOWED[stage]
        and (
            stage in {DiscussionStage.NOT_NEEDED, DiscussionStage.DRAFTING}
            or bool(row.text.strip())
        )
    ]
    if row.stage is not DiscussionStage.SENT and role in ALLOWED[row.stage]:
        allowed.append("edit")
    if row.stage is DiscussionStage.SENT and role in {Role.ADMIN, Role.ANALYST, Role.LAWYER}:
        allowed.append("resolve")
    return tuple(allowed)


def _time_left(row: Discussion, now: datetime) -> tuple[str, bool, bool]:
    """Сколько осталось до конца обсуждения, словами.

    Отправленному замечанию остаток не считается: срок нужен, чтобы успеть
    написать, а написанное и отправленное уже успело.
    """
    if row.deadline is None or row.stage is DiscussionStage.SENT:
        return "", False, False

    left = row.deadline - now
    seconds = int(left.total_seconds())
    if seconds <= 0:
        return "срок прошёл", False, True

    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    if hours >= 24:
        days, hours = divmod(hours, 24)
        words = f"{days} дн. {hours} ч."
    elif hours:
        words = f"{hours} ч. {minutes} мин."
    else:
        words = f"{minutes} мин."
    return words, left <= BURNING, False


__all__ = [
    "ALLOWED",
    "BURNING",
    "OUTCOME_NAMES",
    "SOON",
    "STAGE_NAMES",
    "TRANSITIONS",
    "Remark",
    "Subject",
    "assign",
    "listing",
    "move",
    "one",
    "open_remark",
    "resolve",
    "save_text",
    "starting",
    "written",
]
