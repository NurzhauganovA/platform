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

from platform_api.auth.permissions import Permission
from platform_api.config import Settings
from platform_api.db.base import utcnow
from platform_api.db.models import (
    Department,
    Discussion,
    DiscussionOutcome,
    DiscussionStage,
    DiscussionWriting,
    RemarkEvent,
    Role,
    User,
)
from platform_api.errors import SpokenError
from platform_api.logging import get_logger
from platform_api.modules import markup

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

RIGHTS: dict[DiscussionStage, Permission] = {
    DiscussionStage.DRAFTING: Permission.REMARK_WRITE,
    DiscussionStage.MODERATION: Permission.REMARK_WRITE,
    DiscussionStage.WITH_LAWYERS: Permission.REMARK_WRITE,
    # Отправка заказчику — своё право: это подпись под обращением от имени
    # компании, и достаётся она не заодно с правом писать текст.
    DiscussionStage.SENT: Permission.REMARK_SEND,
    DiscussionStage.NOT_NEEDED: Permission.REMARK_WRITE,
}
"""Каким правом делается переход.

Право спрашивается наравне с именем роли, а не вместо него: наборы в
`ALLOWED` — это те же люди, записанные по-другому, и встроенным ролям ничего
не меняется.

Нужно это ролям, заведённым администратором. У них встроенная часть намеренно
самая безопасная — «Наблюдатель», — и сравнение с именем роли отвечало им
«нельзя» на всё сразу: человек с ролью «Обсуждение», которому выдали и
`remark.write`, и `remark.send`, не мог ни поправить текст, ни передать его
юристам.
"""


def _may(right: Permission, permissions: frozenset[Permission]) -> bool:
    """Есть ли право. Администратор проходит везде — как и в `Identity.can`."""
    return Permission.ADMIN in permissions or right in permissions


def _may_stage(stage: DiscussionStage, role: Role, permissions: frozenset[Permission]) -> bool:
    """Вправе ли человек перевести замечание в это состояние."""
    return role in ALLOWED[stage] or _may(RIGHTS[stage], permissions)


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
class Step:
    """Строка хронологии обсуждения так, как её показывают."""

    id: str
    at: str
    actor: str
    """Кто: имя человека или «ИИ модель»."""

    role: str
    """Роль на момент действия, как её видит человек: «Обсуждение», «Юрист»."""

    by_machine: bool
    kind: str
    title: str
    detail: str


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
    permissions: frozenset[Permission] = frozenset(),
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
    found = [
        _shown(row, people, role=role, user_id=user_id, now=moment, permissions=permissions)
        for row in rows
    ]
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
    permissions: frozenset[Permission] = frozenset(),
) -> Remark:
    row = _required(db, organization_id, remark_id)
    return _shown(
        row,
        _people(db, [row]),
        role=role,
        user_id=user_id,
        now=now or utcnow(),
        permissions=permissions,
    )


MAX_DETAIL = 400
"""Сколько текста ложится в строку хронологии.

Лента читается целиком и сверху вниз. Замечание на три тысячи знаков в ней —
это не хронология, а второй экземпляр текста: сам текст лежит выше, на той же
вкладке, и повторять его строкой ленты незачем.
"""


def trace(
    db: DbSession,
    *,
    remark_id: uuid.UUID,
    kind: str,
    title: str,
    detail: str = "",
    actor_id: uuid.UUID | None = None,
    role_title: str = "",
    by_machine: bool = False,
) -> None:
    """Пишет строку хронологии обсуждения.

    Из службы, а не из обработчика HTTP, — по той же причине, что и лента
    лота: замечание пишет и человек, и модель, и переход, сделанный прогоном,
    — тоже работа над ним. Оставленная в обработчике запись второй путь молча
    пропускает.

    Имя и роль кладутся копиями на момент действия: сотрудник увольняется,
    ссылка обнуляется, а «кто это написал» спрашивают через полгода — и ответ
    «Наблюдатель» вместо «Обсуждение» тут неверен вдвойне.
    """
    name = ""
    if actor_id is not None:
        found = db.get(User, actor_id)
        name = (found.full_name or found.email) if found else ""
    db.add(
        RemarkEvent(
            discussion_id=remark_id,
            actor_id=actor_id,
            actor_name=name,
            actor_role=role_title,
            by_machine=by_machine,
            kind=kind,
            title=title[:255],
            detail=markup.plain(detail)[:MAX_DETAIL],
        )
    )


def history(db: DbSession, *, organization_id: uuid.UUID, remark_id: uuid.UUID) -> list[Step]:
    """Хронология обсуждения, снизу свежие.

    Сверху вниз, как разговор: первым — что написала модель, дальше правки и
    переходы. Так её и читают, когда пришёл отказ и надо понять, что именно
    ушло заказчику и чем оно отличалось от написанного.
    """
    _required(db, organization_id, remark_id)
    rows = db.execute(
        select(RemarkEvent)
        .where(RemarkEvent.discussion_id == remark_id)
        .order_by(RemarkEvent.created_at)
    ).scalars()
    return [
        Step(
            id=str(row.id),
            at=row.created_at.isoformat(),
            actor=row.actor_name or ("ИИ модель" if row.by_machine else "—"),
            role=row.actor_role,
            by_machine=row.by_machine,
            kind=row.kind,
            title=row.title,
            detail=row.detail,
        )
        for row in rows
    ]


def save_text(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    remark_id: uuid.UUID,
    role: Role,
    user_id: uuid.UUID,
    text: str,
    permissions: frozenset[Permission] = frozenset(),
    role_title: str = "",
) -> Discussion:
    """Правка текста замечания.

    Написанное моделью не переписывается: `ai_text` остаётся тем, чем было.
    Сравнить отправленное с исходным нужно ровно тогда, когда пришёл отказ, —
    и именно в этот момент выясняется, что подлинник затёрли.
    """
    row = _required(db, organization_id, remark_id)
    if row.stage is DiscussionStage.SENT:
        raise SpokenError("Замечание уже отправлено, править его нельзя")
    if not _may_stage(row.stage, role, permissions):
        raise SpokenError("Править замечание на этом этапе вам нельзя")

    # Разметку вычищаем до проверки длины: из вставленного документа она бывает
    # девять десятых объёма, и отказ «слишком длинное» приходил бы на текст,
    # который после чистки укладывается втрое.
    clean = markup.tidy(text)
    if len(clean) > MAX_TEXT:
        raise SpokenError("Замечание слишком длинное")
    было = row.text
    row.text = clean
    row.edited_by_id = user_id
    row.edited_at = utcnow()
    # Пишем только настоящую правку. Поле сохраняют и не тронув текста —
    # нажали «Сохранить», подумав; лента из десяти одинаковых строк «поправил»
    # перестаёт отвечать на вопрос, что именно меняли.
    if clean != было:
        trace(
            db,
            remark_id=row.id,
            kind="edited" if было.strip() else "written",
            title="Поправил текст" if было.strip() else "Написал текст",
            detail=clean,
            actor_id=user_id,
            role_title=role_title,
        )
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
    permissions: frozenset[Permission] = frozenset(),
    role_title: str = "",
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
    if not _may_stage(to, role, permissions):
        raise SpokenError(f"Перевести замечание в «{STAGE_NAMES[to]}» вам нельзя")
    # Пустое замечание не уходит дальше проверки. Исключение — «не требуется»
    # и возврат на доработку: у них текста и не должно быть.
    без_текста = {DiscussionStage.NOT_NEEDED, DiscussionStage.DRAFTING}
    if to not in без_текста and not row.text.strip():
        raise SpokenError("Замечание пустое: сначала напишите текст")

    was = row.stage
    row.stage = to
    trace(
        db,
        remark_id=row.id,
        kind="sent" if to is DiscussionStage.SENT else "moved",
        title=(
            "Отправил заказчику"
            if to is DiscussionStage.SENT
            else f"Перевёл: «{STAGE_NAMES[was]}» → «{STAGE_NAMES[to]}»"
        ),
        actor_id=user_id,
        role_title=role_title,
    )
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
    permissions: frozenset[Permission] = frozenset(),
    user_id: uuid.UUID | None = None,
    role_title: str = "",
) -> Discussion:
    """Записывает, чем кончилось у заказчика.

    Только для отправленного: итог у неотправленного замечания означал бы, что
    кто-то отметил ответ на письмо, которого заказчик не получал.
    """
    row = _required(db, organization_id, remark_id)
    if row.stage is not DiscussionStage.SENT:
        raise SpokenError("Итог можно записать только у отправленного замечания")
    if role not in {Role.ADMIN, Role.ANALYST, Role.LAWYER} and not _may(
        Permission.REMARK_WRITE, permissions
    ):
        raise SpokenError("Записывать итог обсуждения вам нельзя")

    row.outcome = outcome
    if answer.strip():
        row.answer = answer.strip()[:MAX_TEXT]
    if outcome is not DiscussionOutcome.WAITING:
        row.answered_at = utcnow()
    trace(
        db,
        remark_id=row.id,
        kind="answered",
        title=f"Ответ заказчика: {OUTCOME_NAMES.get(outcome, outcome.value)}",
        detail=answer,
        actor_id=user_id,
        role_title=role_title,
    )
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
        trace(
            db,
            remark_id=row.id,
            kind="failed",
            title="Модель не написала",
            detail=trouble,
            by_machine=True,
        )
        db.flush()
        return

    row.ai_text = text[:MAX_TEXT]
    row.writing = DiscussionWriting.READY
    # Пишем до подстановки: `ai_text` затирается при каждом перезапуске
    # прогона, и без этой записи предыдущая версия пропадает бесследно — а
    # сравнивают их ровно тогда, когда пришёл отказ.
    trace(
        db,
        remark_id=row.id,
        kind="written",
        title=f"Написала модель ({model})" if model else "Написала модель",
        detail=row.ai_text,
        by_machine=True,
    )
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
    permissions: frozenset[Permission] = frozenset(),
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
        can=_can(row, role=role, user_id=user_id, permissions=permissions),
    )


def _can(
    row: Discussion,
    *,
    role: Role,
    user_id: uuid.UUID,
    permissions: frozenset[Permission] = frozenset(),
) -> tuple[str, ...]:
    """Что этому человеку доступно на этом этапе.

    Считается теми же условиями, что стоят в службах: кнопка, которую
    показали, а служба отвергла, — это человек, уверенный, что дело сделано.
    """
    allowed = [
        stage.value
        for stage in TRANSITIONS[row.stage]
        if _may_stage(stage, role, permissions)
        and (
            stage in {DiscussionStage.NOT_NEEDED, DiscussionStage.DRAFTING}
            or bool(row.text.strip())
        )
    ]
    if row.stage is not DiscussionStage.SENT and _may_stage(row.stage, role, permissions):
        allowed.append("edit")
    if row.stage is DiscussionStage.SENT and (
        role in {Role.ADMIN, Role.ANALYST, Role.LAWYER}
        or _may(Permission.REMARK_WRITE, permissions)
    ):
        allowed.append("resolve")
    return tuple(allowed)


_NO_DEADLINE = frozenset({DiscussionStage.SENT, DiscussionStage.NOT_NEEDED})
"""Этапы, на которых срок обсуждения уже ничего не значит."""


def _time_left(row: Discussion, now: datetime) -> tuple[str, bool, bool]:
    """Сколько осталось до конца обсуждения, словами.

    Отправленному замечанию остаток не считается: срок нужен, чтобы успеть
    написать, а написанное и отправленное уже успело.

    Ненужному — тоже. «Обсуждать нечего» означает, что требования заказчика нас
    устраивают и отправлять нечего; просроченный срок у такого замечания красил
    строку красным «не отправили», хотя отправлять было незачем — а кружок
    отдела в карточке в это же время стоял зелёным. Одна строка давала два
    разных ответа про один лот.
    """
    if row.deadline is None or row.stage in _NO_DEADLINE:
        return "", False, False

    # Тот же расчёт, что у лотов и задач: «просрочено на 3 ч. 20 мин.», а не
    # «срок прошёл». Двадцать минут опоздания догоняются сегодня, три дня —
    # означают, что замечание вообще никто не открывал.
    from platform_api.modules.cards import time_left as _left

    return _left(row.deadline, now)


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
