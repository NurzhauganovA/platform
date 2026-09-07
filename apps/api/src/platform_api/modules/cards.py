"""Карточка лота: сквозной путь закупки через отделы.

Одна карточка на лот и один статус на весь путь. Отделов пять, у каждого свой
взгляд, но вопрос на планёрке один — «что сейчас с этой закупкой», и отвечать
на него сложением пяти состояний означает пять разных ответов.

Переходы описаны таблицей, а не проверками по месту. Путь длинный, ветвится в
четырёх местах, и разложенный по обработчикам он разъезжается за месяц: одно
место разрешает то, что другое запрещает, и выясняется это на закупке, которую
уже подали.

Что можно нажать, решает сервер и присылает списком. Второй набор правил в
браузере однажды разойдётся с первым, и человек нажмёт кнопку, получив отказ.
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
    Approval,
    ApprovalKind,
    ApprovalState,
    Department,
    Discussion,
    DiscussionStage,
    LotCard,
    LotEvent,
    LotFile,
    LotStatus,
    Membership,
    Participation,
    Role,
    StoredFile,
    Task,
    TaskState,
    User,
)
from platform_api.errors import SpokenError
from platform_api.logging import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session as DbSession

BURNING = timedelta(hours=6)
"""За сколько до окончания приёма лот считается горящим."""

APPROVE_BEFORE = timedelta(hours=2)
"""За сколько до окончания приёма должно быть собрано согласование.

Два часа — не запас на подпись, а запас на подачу. Заявка подаётся руками
через портал, и подписи, собранные за десять минут до срока, означают, что
подавать будут в спешке: приложить не тот файл в этот момент проще всего.
"""

STATUS_NAMES: dict[LotStatus, str] = {
    LotStatus.NEW: "Новый",
    LotStatus.DISCUSSION: "Обсуждение",
    LotStatus.ANALYSIS: "На разборе",
    LotStatus.APPROVAL: "На согласовании",
    LotStatus.READY: "Готов к участию",
    LotStatus.AWAITING: "Ожидаем итоги",
    LotStatus.WON: "Выиграли",
    LotStatus.LOST: "Проиграли",
    LotStatus.CONTRACT: "Договор",
    LotStatus.FULFILLING: "Исполнение",
    LotStatus.AWAITING_PAYMENT: "Ожидаем оплату",
    LotStatus.DONE: "Завершён",
    LotStatus.SKIPPED: "Не участвуем",
    LotStatus.CANCELLED: "Отменён",
}

# Порядок хода. По нему рисуется полоса в карточке: человек должен видеть, где
# лот стоит и сколько шагов до конца, а не одно слово без контекста.
FLOW: tuple[LotStatus, ...] = (
    LotStatus.NEW,
    LotStatus.DISCUSSION,
    LotStatus.ANALYSIS,
    LotStatus.APPROVAL,
    LotStatus.READY,
    LotStatus.AWAITING,
    LotStatus.WON,
    LotStatus.CONTRACT,
    LotStatus.FULFILLING,
    LotStatus.AWAITING_PAYMENT,
    LotStatus.DONE,
)

# Тупики нужны для отметки времени окончания, а не для запрета: лот, доехавший
# до «Завершён», «Проиграли» или «Отменён», получает `finished_at`.
_FINAL = frozenset({LotStatus.DONE, LotStatus.LOST, LotStatus.CANCELLED})

TRANSITIONS: dict[LotStatus, tuple[LotStatus, ...]] = {
    status: tuple(other for other in LotStatus if other is not status) for status in LotStatus
}
"""Куда можно уйти с каждого шага. Отовсюду куда угодно.

Раньше здесь стояла таблица разрешённых переходов: из «Нового» только в
«Обсуждение» или «На разбор», из «Завершён» никуда. Она описывала процесс
таким, каким его задумали, — а компания молодая, и процесс ещё меняется.
Каждое расхождение с жизнью упиралось в отказ, объяснить который человеку
нечем: лот действительно закончился не так, как в таблице.

Порядок остался, но теперь он подсказка, а не забор: `FLOW` задаёт ход, экран
показывает следующий шаг заметнее прочих, и всё же перевести можно куда
угодно.

Что осталось запретом — не про порядок, а про деньги: «Готов к участию» без
пяти подписей и «Не участвуем» без причины. Оба проверяются в `move` и
объясняются словами."""

# Кто вправе перевести лот в это состояние. Набором, а не старшинством:
# иерархия подталкивает написать «не ниже менеджера», и снабжение получает
# право объявить лот готовым к участию.
_RUNS = frozenset({Role.ADMIN, Role.MANAGER})
_DECIDES = frozenset({Role.ADMIN, Role.MANAGER, Role.HEAD, Role.COMMERCIAL})
ALLOWED: dict[LotStatus, frozenset[Role]] = {
    LotStatus.NEW: _RUNS,
    LotStatus.DISCUSSION: _RUNS | {Role.LAWYER, Role.ANALYST},
    LotStatus.ANALYSIS: _RUNS | {Role.ANALYST},
    LotStatus.APPROVAL: _RUNS | {Role.ANALYST},
    LotStatus.READY: _RUNS,
    LotStatus.AWAITING: _RUNS,
    LotStatus.WON: _RUNS,
    LotStatus.LOST: _RUNS,
    LotStatus.CONTRACT: _RUNS,
    LotStatus.FULFILLING: _RUNS | {Role.BUYER},
    LotStatus.AWAITING_PAYMENT: _RUNS,
    LotStatus.DONE: _RUNS,
    LotStatus.SKIPPED: _DECIDES,
    LotStatus.CANCELLED: _RUNS,
}

# Кто ставит какую подпись. Одна роль — одна подпись: если один человек может
# подписать за двоих, согласование перестаёт быть согласованием.
SIGNS: dict[ApprovalKind, frozenset[Role]] = {
    ApprovalKind.MANAGER: frozenset({Role.ADMIN, Role.MANAGER}),
    ApprovalKind.SUPPLY: frozenset({Role.ADMIN, Role.BUYER}),
    ApprovalKind.LEGAL: frozenset({Role.ADMIN, Role.LAWYER}),
    ApprovalKind.TECHNOLOGIST: frozenset({Role.ADMIN, Role.TECHNOLOGIST}),
    ApprovalKind.ASSEMBLER: frozenset({Role.ADMIN, Role.ASSEMBLER}),
}

APPROVAL_NAMES: dict[ApprovalKind, str] = {
    ApprovalKind.MANAGER: "Менеджер",
    ApprovalKind.SUPPLY: "Снабжение",
    ApprovalKind.LEGAL: "Юрист",
    ApprovalKind.TECHNOLOGIST: "Технолог",
    ApprovalKind.ASSEMBLER: "Сборщик",
}

DISCUSSION_STAGE_NAMES: dict[DiscussionStage, str] = {
    DiscussionStage.DRAFTING: "Пишется",
    DiscussionStage.MODERATION: "На проверке",
    DiscussionStage.WITH_LAWYERS: "У юристов",
    DiscussionStage.SENT: "Отправлено",
    DiscussionStage.NOT_NEEDED: "Не требуется",
}
"""Те же слова, что в разделе обсуждений (`remarks.STAGE_NAMES`).

Повторены, а не взяты оттуда: `remarks` про обсуждения знает всё и читает
карточки, а карточкам от него нужны пять слов. Общий импорт свёл бы два
модуля в кольцо ради словаря на пять строк. Тест на совпадение есть."""


DEPARTMENT_ROLES: dict[Department, tuple[Role, ...]] = {
    Department.DISCUSSION: (Role.ADMIN, Role.MANAGER, Role.LAWYER),
    Department.ANALYSIS: (Role.ADMIN, Role.MANAGER, Role.ANALYST),
    Department.SUPPLY: (Role.ADMIN, Role.MANAGER, Role.BUYER),
    Department.LEGAL: (Role.ADMIN, Role.MANAGER, Role.LAWYER),
    Department.TECHNOLOGIST: (Role.ADMIN, Role.TECHNOLOGIST),
    Department.ASSEMBLER: (Role.ADMIN, Role.ASSEMBLER),
    Department.APPROVAL: (Role.ADMIN, Role.MANAGER),
    Department.SUBMISSION: (Role.ADMIN, Role.MANAGER),
}
"""Кого звать, когда работа пришла отделу.

Отдел — про очередь, роль — про право видеть цифры, и связи между ними в базе
нет: задача адресуется отделу, а человек числится ролью. Сводится это здесь,
одним объявлением на всю платформу. Раскладывать по месту в каждом обработчике
значило бы завести пять ответов на вопрос «кто у нас разборщики» и однажды
разослать лот мимо тех, кто его ждёт.

Наблюдателя нет нигде: он смотрит отчёты, а уведомление зовёт к работе.
"""


def people_of(db: DbSession, organization_id: uuid.UUID, desk: Department) -> list[uuid.UUID]:
    """Кто работает в отделе — по ролям, действующие.

    Выключенный сотрудник не зовётся: уволившийся продолжал бы получать письма
    о наших закупках, и заметили бы это не скоро.
    """
    roles = DEPARTMENT_ROLES.get(desk, ())
    if not roles:
        return []
    return list(
        db.scalars(
            select(User.id)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.organization_id == organization_id,
                Membership.role.in_(roles),
                User.is_active.is_(True),
            )
            .distinct()
        )
    )


DEPARTMENT_NAMES: dict[Department, str] = {
    Department.DISCUSSION: "Обсуждение",
    Department.ANALYSIS: "Разбор",
    Department.SUPPLY: "Снабжение",
    Department.LEGAL: "Юристы",
    Department.TECHNOLOGIST: "Технолог",
    Department.ASSEMBLER: "Сборщик",
    Department.APPROVAL: "Согласование",
    Department.SUBMISSION: "Подача",
}

# Отдел, которому лот принадлежит на этом шаге. По нему задача попадает в
# нужную очередь, когда её заводят с карточки без указания отдела.
DEPARTMENT_OF: dict[LotStatus, Department] = {
    LotStatus.NEW: Department.ANALYSIS,
    LotStatus.DISCUSSION: Department.DISCUSSION,
    LotStatus.ANALYSIS: Department.ANALYSIS,
    LotStatus.APPROVAL: Department.APPROVAL,
    LotStatus.READY: Department.SUBMISSION,
    LotStatus.AWAITING: Department.SUBMISSION,
    LotStatus.WON: Department.SUBMISSION,
    LotStatus.LOST: Department.SUBMISSION,
    LotStatus.CONTRACT: Department.SUBMISSION,
    LotStatus.FULFILLING: Department.SUPPLY,
    LotStatus.AWAITING_PAYMENT: Department.SUBMISSION,
    LotStatus.DONE: Department.SUBMISSION,
    LotStatus.SKIPPED: Department.ANALYSIS,
    LotStatus.CANCELLED: Department.ANALYSIS,
}


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Закупка на момент заведения карточки."""

    code: str
    title: str
    source_number: str = ""
    """Номер закупки на площадке. По нему лот находят в списке и на портале."""

    customer: str = ""
    amount: Decimal | None = None
    enstru_code: str = ""
    category: str = ""
    deadline: datetime | None = None


@dataclass(frozen=True, slots=True)
class Person:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Sign:
    """Одна подпись под участием."""

    kind: str
    name: str
    state: str
    by: str
    at: str
    note: str
    can_sign: bool
    """Может ли этот человек поставить именно эту подпись. Считается на
    сервере: показывать кнопку всем и отвечать отказом четверым из пяти —
    самый быстрый способ научить людей не доверять интерфейсу."""


@dataclass(frozen=True, slots=True)
class Job:
    """Задача в том виде, в каком её показывают."""

    id: str
    card_id: str
    card_code: str
    card_title: str
    department: str
    department_name: str
    title: str
    body: str
    assignee: str
    assignee_id: str
    due_at: str
    left: str
    burning: bool
    overdue: bool
    state: str
    result: str
    created_at: str


@dataclass(frozen=True, slots=True)
class Talk:
    """Обсуждение по этому лоту — коротко, для правого столбца.

    Своим блоком, а не строкой в сводке: у обсуждения свой срок, и он не
    совпадает со сроком подачи. Два рабочих дня со дня публикации проходят,
    пока лот ещё числится «в разборе», и человек, глядя на «осталось 6 дней»
    от приёма заявок, узнаёт о закрытом окне постфактум.
    """

    id: str
    stage: str
    stage_name: str
    deadline: str
    left: str
    burning: bool
    overdue: bool


@dataclass(frozen=True, slots=True)
class Card:
    """Карточка лота целиком."""

    id: str
    module: str
    row_id: str
    code: str
    source_number: str
    title: str
    customer: str
    amount: Decimal | None
    enstru_code: str
    category: str

    status: str
    status_name: str
    step: int
    """Какой это шаг пути, считая с единицы. Ноль — лот сошёл с дистанции."""

    participation: str
    skip_reason: str

    manager: str
    manager_id: str
    owner: str
    owner_id: str

    deadline: str
    left: str
    burning: bool
    overdue: bool

    approve_by: str
    """До какого момента нужно собрать подписи. Срок приёма минус два часа."""

    approve_left: str
    approve_burning: bool
    approve_overdue: bool

    note: str
    won_amount: Decimal | None
    winner: str
    started_at: str
    """Когда лот взяли в работу. Первый вопрос к залежавшейся карточке."""

    submitted_at: str
    finished_at: str

    approvals: tuple[Sign, ...]
    approved: bool
    """Все пять подписей стоят. По нему открывается «Готов к участию»."""

    open_tasks: int
    done_tasks: int
    can: tuple[str, ...]

    discussion: Talk | None = None
    """Обсуждение по лоту, если его заводили. В списке пусто: там оно не
    показывается, а запрос на сотню строк ради него — сотня лишних чтений."""


def open_card(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    module: str,
    row_id: str,
    snapshot: Snapshot,
    by: uuid.UUID | None = None,
    settings: Settings | None = None,
) -> LotCard:
    """Заводит карточку. Уже заведённую возвращает как есть.

    Идемпотентно: кнопку «Взять в работу» нажимают дважды, и второе нажатие не
    должно ни падать, ни заводить вторую карточку по тому же лоту.

    `settings` — чтобы позвать разбор и обсуждение. Не передали — не зовём:
    так работают прогоны проверок и переносы, где рассылка людям не нужна.
    Оповещение стоит здесь, а не в обработчике HTTP, по той же причине, по
    которой отсюда пишется лента: карточка заводится и кнопкой, и выборкой по
    номеру, и оба пути должны звать одних и тех же людей.
    """
    found = _find(db, organization_id, module, row_id)
    if found is not None:
        return found

    found = LotCard(
        organization_id=organization_id,
        module=module,
        row_id=row_id,
        code=snapshot.code,
        source_number=snapshot.source_number,
        title=snapshot.title[:4000],
        customer=snapshot.customer,
        amount=snapshot.amount,
        enstru_code=snapshot.enstru_code,
        category=snapshot.category,
        deadline=snapshot.deadline,
        status=LotStatus.NEW,
        participation=Participation.MAYBE,
        manager_id=by,
        owner_id=by,
    )
    db.add(found)
    db.flush()

    _opened(db, settings, found)

    # Пять подписей заводятся сразу пустыми, а не по мере появления. Иначе
    # «согласовано» у лота с одной подписью выглядит так же, как у лота с
    # пятью: в обоих случаях ни одного отказа.
    for kind in ApprovalKind:
        db.add(Approval(card_id=found.id, kind=kind))
    trace(
        db,
        card_id=found.id,
        kind="took",
        title="Взял лот в работу",
        actor_id=by,
        moved_to=found.status,
    )
    db.flush()
    return found


def move(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    card_id: uuid.UUID,
    role: Role,
    user_id: uuid.UUID,
    to: LotStatus,
    reason: str = "",
) -> LotCard:
    """Переводит лот на следующий шаг."""
    card = _required(db, organization_id, card_id)
    if to is card.status:
        return card
    was = card.status
    if to not in TRANSITIONS[card.status]:
        raise SpokenError(
            f"Из состояния «{STATUS_NAMES[card.status]}» нельзя перейти в «{STATUS_NAMES[to]}»"
        )
    if role not in ALLOWED[to]:
        raise SpokenError(f"Перевести лот в «{STATUS_NAMES[to]}» вам нельзя")
    if to is LotStatus.READY and not _all_signed(card):
        raise SpokenError("Не все подписи под участием собраны")
    if to is LotStatus.SKIPPED and not reason.strip():
        raise SpokenError("Укажите, почему не участвуем: через месяц это спросят")

    card.status = to
    if to is LotStatus.SKIPPED:
        card.participation = Participation.NO
        card.skip_reason = reason.strip()[:2000]
    if to is LotStatus.AWAITING:
        card.submitted_at = utcnow()
    if to in _FINAL:
        card.finished_at = utcnow()
    if to is not LotStatus.SKIPPED:
        card.participation = Participation.YES
    card.owner_id = user_id
    trace(
        db,
        card_id=card.id,
        kind="moved",
        title=f"Перевёл в «{STATUS_NAMES[to]}»",
        actor_id=user_id,
        role=role,
        detail=reason,
        moved_from=was,
        moved_to=to,
    )
    db.flush()
    return card


def trace(
    db: DbSession,
    *,
    card_id: uuid.UUID,
    kind: str,
    title: str,
    actor_id: uuid.UUID | None = None,
    role: Role | None = None,
    detail: str = "",
    by_machine: bool = False,
    moved_from: LotStatus | None = None,
    moved_to: LotStatus | None = None,
) -> None:
    """Записывает, что с лотом сделали.

    Зовётся из самих действий, а не из обработчиков запросов: действие,
    сделанное в обход HTTP — прогоном, разбором, моделью, — тоже работа над
    лотом, и в ленте она должна быть. Пропущенный вызов означает премию,
    посчитанную по неполным данным, и заметят это на планёрке.

    Роль записывается на момент действия: снабженец, ставший руководителем,
    подписывал за снабжение, и в ленте должно остаться так.
    """
    db.add(
        LotEvent(
            card_id=card_id,
            actor_id=actor_id,
            actor_role=role.value if role is not None else "",
            by_machine=by_machine,
            kind=kind,
            title=title[:255],
            detail=detail.strip()[:4000],
            from_status=moved_from.value if moved_from else "",
            to_status=moved_to.value if moved_to else "",
        )
    )


def decide(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    card_id: uuid.UUID,
    role: Role,
    participation: Participation,
    reason: str = "",
    user_id: uuid.UUID | None = None,
) -> LotCard:
    """Берём лот в работу или нет.

    Отдельно от статуса: это первый отсев, до всякой работы. Под наши коды
    приходит вчетверо больше, чем мы способны разобрать.
    """
    card = _required(db, organization_id, card_id)
    if role not in _DECIDES:
        raise SpokenError("Решать об участии вам нельзя")
    if participation is Participation.NO and not reason.strip():
        raise SpokenError("Укажите причину отказа от участия")

    card.participation = participation
    card.skip_reason = reason.strip()[:2000] if participation is Participation.NO else ""
    if participation is Participation.NO and card.status not in _FINAL:
        card.status = LotStatus.SKIPPED
        card.finished_at = utcnow()
    trace(
        db,
        card_id=card.id,
        kind="decided",
        title="Решил участвовать" if participation is Participation.YES else "Решил не участвовать",
        actor_id=user_id,
        role=role,
        detail=reason,
    )
    db.flush()
    return card


def sign(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    card_id: uuid.UUID,
    role: Role,
    user_id: uuid.UUID,
    kind: ApprovalKind,
    state: ApprovalState,
    note: str = "",
) -> LotCard:
    """Ставит подпись отдела под участием.

    Отказ требует причины. Подпись «нет» без слова о том, что не так, ставит
    работу и не говорит, что чинить.
    """
    card = _required(db, organization_id, card_id)
    if role not in SIGNS[kind]:
        raise SpokenError(f"Подпись «{APPROVAL_NAMES[kind]}» ставите не вы")
    if state is ApprovalState.REJECTED and not note.strip():
        raise SpokenError("Укажите, что мешает согласовать")

    found = next((item for item in card.approvals if item.kind is kind), None)
    if found is None:
        found = Approval(card_id=card.id, kind=kind)
        db.add(found)
    found.state = state
    found.by_id = user_id
    found.decided_at = utcnow()
    found.note = note.strip()[:2000]
    trace(
        db,
        card_id=card.id,
        kind="signed" if state is ApprovalState.APPROVED else "rejected",
        title=(
            f"Подписал за «{APPROVAL_NAMES[kind]}»"
            if state is ApprovalState.APPROVED
            else f"Отказал в подписи «{APPROVAL_NAMES[kind]}»"
        ),
        actor_id=user_id,
        role=role,
        detail=note,
    )
    db.flush()
    db.refresh(card)
    return card


def result(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    card_id: uuid.UUID,
    role: Role,
    won_amount: Decimal | None = None,
    winner: str = "",
    user_id: uuid.UUID | None = None,
) -> LotCard:
    """Записывает итоги подачи.

    Только у поданного лота: «выиграли за» у неподанного означало бы итоги
    закупки, в которой мы не участвовали.

    Цена и победитель хранятся оба и не мешают друг другу. Своя цена нужна,
    чтобы через год понять, с какой маржой брали; чужая — чтобы понять, с кем
    соревнуемся и по какой цене они берут.
    """
    card = _required(db, organization_id, card_id)
    if card.submitted_at is None:
        raise SpokenError("Итоги записываются у поданного лота")
    if role not in _RUNS:
        raise SpokenError("Записывать итоги подачи вам нельзя")

    if won_amount is not None:
        card.won_amount = won_amount
    if winner.strip():
        card.winner = winner.strip()[:2000]
    trace(
        db,
        card_id=card.id,
        kind="result",
        title="Записал итоги подачи",
        actor_id=user_id,
        role=role,
        detail=winner,
    )
    db.flush()
    return card


def assign(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    card_id: uuid.UUID,
    manager_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    role: Role | None = None,
    change_manager: bool = False,
    change_owner: bool = False,
) -> LotCard:
    """Меняет менеджера или текущего ответственного.

    Признаки `change_*` нужны, чтобы отличить «снять ответственного» от «не
    трогать его»: и то и другое приходит пустым значением.
    """
    card = _required(db, organization_id, card_id)
    if change_manager:
        card.manager_id = manager_id
    if change_owner:
        card.owner_id = owner_id
    trace(
        db,
        card_id=card.id,
        kind="assigned",
        title="Сменил ответственных",
        actor_id=user_id,
        role=role,
    )
    db.flush()
    return card


def add_task(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    card_id: uuid.UUID,
    created_by: uuid.UUID,
    title: str,
    department: Department | None = None,
    body: str = "",
    assignee_id: uuid.UUID | None = None,
    due_at: datetime | None = None,
    settings: Settings | None = None,
) -> Task:
    """Заводит задачу по лоту.

    Отдел не указан — берётся тот, у кого лот сейчас: чаще всего задачу заводят
    себе же, и переспрашивать об этом каждый раз значит добавить нажатие к
    самому частому действию.
    """
    card = _required(db, organization_id, card_id)
    clean = " ".join(title.split())
    if not clean:
        raise SpokenError("У задачи должно быть название")

    task = Task(
        organization_id=organization_id,
        card_id=card.id,
        department=department or DEPARTMENT_OF[card.status],
        title=clean[:2000],
        body=body.strip(),
        assignee_id=assignee_id,
        created_by_id=created_by,
        due_at=due_at or card.deadline,
    )
    db.add(task)
    trace(
        db,
        card_id=card.id,
        kind="task",
        title=f"Завёл задачу отделу «{DEPARTMENT_NAMES[task.department]}»",
        actor_id=created_by,
        detail=clean,
    )
    db.flush()
    _task_added(db, settings, task, card)
    return task


def close_task(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    task_id: uuid.UUID,
    state: TaskState,
    result: str = "",
    user_id: uuid.UUID | None = None,
    role: Role | None = None,
) -> Task:
    """Закрывает задачу или снова открывает.

    Закрыть без отчёта нельзя. Поле было в базе с самого начала, но его никто
    не спрашивал, и в истории оставалось только «закрыл»: ни премию посчитать,
    ни спросить, что именно нашли. Проверка стоит здесь, а не на экране, —
    закрывают задачу и с доски, и из окна в карточке, и вторая дверь без
    проверки сводит на нет первую.

    Возврат в работу отчёта не требует: там объяснять нечего — задача не
    сделана, и это видно по её состоянию.
    """
    task = db.get(Task, task_id)
    if task is None or task.organization_id != organization_id:
        raise SpokenError("Задача не найдена")

    if state is not TaskState.OPEN and not result.strip():
        raise SpokenError(
            "Напишите, что сделано: по записи «закрыл» через месяц не понять, "
            "что именно нашли и кому за это платить"
        )

    task.state = state
    task.done_at = utcnow() if state is not TaskState.OPEN else None
    if result.strip():
        task.result = result.strip()[:4000]
    trace(
        db,
        card_id=task.card_id,
        kind="task_done" if state is TaskState.DONE else "task",
        title=(
            f"Закрыл задачу «{task.title}»"
            if state is TaskState.DONE
            else f"Вернул в работу задачу «{task.title}»"
        ),
        actor_id=user_id,
        role=role,
        detail=result,
    )
    db.flush()
    return task


@dataclass(frozen=True, slots=True)
class Event:
    """Одна запись ленты в том виде, в каком её показывают."""

    id: str
    at: str
    actor: str
    actor_id: str
    actor_role: str
    by_machine: bool
    kind: str
    title: str
    detail: str
    from_status: str
    to_status: str


@dataclass(frozen=True, slots=True)
class Worker:
    """Сколько сделал человек. По этому считают премию."""

    name: str
    user_id: str
    role: str
    actions: int
    first_at: str
    last_at: str


@dataclass(frozen=True, slots=True)
class Stage:
    """Сколько лот простоял на этапе и у кого.

    Отвечает на «где закупка застряла». Одно число «в работе сутки» этого не
    говорит: сутки в разборе и сутки на согласовании — разные разговоры и
    разные люди.
    """

    status: str
    name: str
    seconds: int
    owner: str
    running: bool
    """Этап идёт прямо сейчас — время считается до текущего момента."""


def history(
    db: DbSession, *, organization_id: uuid.UUID, card_id: uuid.UUID
) -> tuple[list[Event], list[Worker], list[Stage]]:
    """Лента лота и сводка по людям.

    Сводка считается здесь, а не в браузере: по ней делят премию, и второй
    расчёт на клиенте однажды разойдётся с первым — а спорить будут о деньгах.

    Прогоны и модель в сводку не идут: премию получает человек.
    """
    _required(db, organization_id, card_id)
    rows = (
        db.execute(
            select(LotEvent, User.full_name)
            .outerjoin(User, User.id == LotEvent.actor_id)
            .where(LotEvent.card_id == card_id)
            .order_by(LotEvent.created_at.desc())
        )
        .tuples()
        .all()
    )

    events = [
        Event(
            id=str(item.id),
            at=item.created_at.isoformat(),
            actor=name or ("платформа" if item.by_machine else "неизвестно кто"),
            actor_id=str(item.actor_id) if item.actor_id else "",
            actor_role=item.actor_role,
            by_machine=item.by_machine,
            kind=item.kind,
            title=item.title,
            detail=item.detail,
            from_status=item.from_status,
            to_status=item.to_status,
        )
        for item, name in rows
    ]

    counted: dict[str, Worker] = {}
    # Идём от старых к новым: так «впервые коснулся» и «в последний раз»
    # берутся без лишней сортировки.
    for event in reversed(events):
        if event.by_machine or not event.actor_id:
            continue
        was = counted.get(event.actor_id)
        counted[event.actor_id] = Worker(
            name=event.actor,
            user_id=event.actor_id,
            role=event.actor_role or (was.role if was else ""),
            actions=(was.actions if was else 0) + 1,
            first_at=was.first_at if was else event.at,
            last_at=event.at,
        )

    workers = sorted(counted.values(), key=lambda item: (-item.actions, item.name))
    return events, workers, _stages(rows)


def _stages(rows: Sequence[tuple[LotEvent, str | None]]) -> list[Stage]:
    """Сколько лот пробыл на каждом этапе.

    По переходам, а не по разбору названий: `from_status` и `to_status`
    записаны отдельно ровно для этого.

    Хозяином этапа считается тот, кто на него перевёл: следующий переход
    делает уже кто-то другой, и приписывать ему чужое время нельзя.
    """
    moves = sorted(
        ((item, name) for item, name in rows if item.to_status),
        key=lambda pair: pair[0].created_at,
    )
    if not moves:
        return []

    known = {status.value: STATUS_NAMES[status] for status in LotStatus}
    made: list[Stage] = []
    for index, (item, name) in enumerate(moves):
        after = moves[index + 1][0].created_at if index + 1 < len(moves) else None
        ends = after or utcnow()
        made.append(
            Stage(
                status=item.to_status,
                name=known.get(item.to_status, item.to_status),
                seconds=max(int((ends - item.created_at).total_seconds()), 0),
                owner=name or "",
                running=after is None,
            )
        )
    return made


def take_task(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    task_id: uuid.UUID,
    user_id: uuid.UUID | None,
) -> Task:
    """Берёт задачу себе. Пустой человек — возвращает в общую очередь."""
    task = db.get(Task, task_id)
    if task is None or task.organization_id != organization_id:
        raise SpokenError("Задача не найдена")
    task.assignee_id = user_id
    trace(
        db,
        card_id=task.card_id,
        kind="task_taken",
        title=(
            f"Взял задачу «{task.title}»"
            if user_id is not None
            else f"Вернул в очередь отдела задачу «{task.title}»"
        ),
        actor_id=user_id,
    )
    db.flush()
    return task


@dataclass(frozen=True, slots=True)
class Filters:
    """Отбор карточек. Всё необязательно, пустое поле ничего не сужает."""

    module: str | None = None
    status: LotStatus | None = None
    participation: Participation | None = None
    category: str | None = None
    enstru_code: str | None = None
    amount_from: Decimal | None = None
    amount_to: Decimal | None = None
    mine: bool = False
    """Мои: где я менеджер или текущий ответственный. Оба сразу, потому что
    вопрос «что на мне» этих двух ролей не различает."""

    unowned: bool = False
    burning: bool = False
    search: str = ""


def listing(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    role: Role,
    user_id: uuid.UUID,
    filters: Filters | None = None,
    now: datetime | None = None,
) -> list[Card]:
    """Карточки под отбором.

    Порядок: сначала те, у кого срок ближе. Без срока — в конец: торопиться по
    ним некуда, а место наверху нужно тем, у кого часы идут. Сошедшие с
    дистанции уходят вниз независимо от срока.
    """
    moment = now or utcnow()
    want = filters or Filters()

    query = select(LotCard).where(LotCard.organization_id == organization_id)
    if want.module:
        query = query.where(LotCard.module == want.module)
    if want.status is not None:
        query = query.where(LotCard.status == want.status)
    if want.participation is not None:
        query = query.where(LotCard.participation == want.participation)
    if want.category:
        query = query.where(LotCard.category == want.category)
    if want.enstru_code:
        query = query.where(LotCard.enstru_code == want.enstru_code)
    if want.amount_from is not None:
        query = query.where(LotCard.amount >= want.amount_from)
    if want.amount_to is not None:
        query = query.where(LotCard.amount <= want.amount_to)
    if want.mine:
        query = query.where((LotCard.manager_id == user_id) | (LotCard.owner_id == user_id))
    if want.unowned:
        query = query.where(LotCard.owner_id.is_(None))

    rows = list(db.execute(query).scalars())
    if want.search:
        needle = want.search.strip().lower()
        rows = [
            row
            for row in rows
            if needle in f"{row.code} {row.title} {row.customer} {row.row_id}".lower()
        ]

    # Сортировка в памяти: строк здесь сотни, а «без срока в конец» на стороне
    # базы пишется по-разному в SQLite и PostgreSQL и однажды разъезжается
    # между проверочной средой и рабочей.
    rows.sort(key=lambda row: (row.status in _FINAL, row.deadline is None, row.deadline or moment))
    known = people(db, rows)
    found = [_shown(row, known, role=role, user_id=user_id, now=moment) for row in rows]
    if want.burning:
        found = [item for item in found if item.burning and not item.overdue]
    return found


def one(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    card_id: uuid.UUID,
    role: Role,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> Card:
    card = _required(db, organization_id, card_id)
    # Обсуждение читается только для одной карточки. В списке оно не
    # показывается, и запрос на сотню строк ради него — сотня лишних чтений.
    talk = db.execute(
        select(Discussion).where(
            Discussion.organization_id == organization_id,
            Discussion.module == card.module,
            Discussion.row_id == card.row_id,
        )
    ).scalar_one_or_none()
    return _shown(
        card,
        people(db, [card]),
        role=role,
        user_id=user_id,
        now=now or utcnow(),
        talk=talk,
    )


def by_row(
    db: DbSession, *, organization_id: uuid.UUID, module: str, row_id: str
) -> LotCard | None:
    """Карточка строки, если её заводили.

    Нужна рабочему списку: по ней он отмечает взятое в работу и показывает, у
    кого лот сейчас.
    """
    return _find(db, organization_id, module, row_id)


def tasks(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    department: Department | None = None,
    assignee_id: uuid.UUID | None = None,
    unassigned: bool = False,
    card_id: uuid.UUID | None = None,
    state: TaskState | None = TaskState.OPEN,
    now: datetime | None = None,
) -> list[Job]:
    """Задачи под отбором.

    По умолчанию только открытые: очередь работы — это то, что не сделано, а
    закрытые смотрят отдельной вкладкой и редко.
    """
    moment = now or utcnow()
    query = select(Task).where(Task.organization_id == organization_id)
    if department is not None:
        query = query.where(Task.department == department)
    if assignee_id is not None:
        query = query.where(Task.assignee_id == assignee_id)
    if unassigned:
        query = query.where(Task.assignee_id.is_(None))
    if card_id is not None:
        query = query.where(Task.card_id == card_id)
    if state is not None:
        query = query.where(Task.state == state)

    rows = list(db.execute(query).scalars())
    rows.sort(key=lambda row: (row.due_at is None, row.due_at or moment))
    known = people(db, rows)
    cards = _cards_of(db, rows)
    return [_job(row, known, cards, moment) for row in rows]


def task(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    task_id: uuid.UUID,
    now: datetime | None = None,
) -> Job:
    """Одна задача.

    Отдельно от `tasks`, хотя разница в одном условии. Через общий список это
    читалось так: вычитать все задачи организации, собрать их карточки и найти
    среди них одну. На двух десятках задач разницы нет, на нескольких тысячах
    это полный обход таблицы на каждое нажатие «закрыть».
    """
    row = db.get(Task, task_id)
    if row is None or row.organization_id != organization_id:
        raise SpokenError("Задача не найдена")
    moment = now or utcnow()
    card = db.get(LotCard, row.card_id)
    return _job(
        row,
        people(db, [row]),
        {card.id: card} if card is not None else {},
        moment,
    )


def _cards_of(db: DbSession, rows: Sequence[Task]) -> dict[uuid.UUID, LotCard]:
    """Карточки задач одним запросом — задача без лота не читается."""
    wanted = {row.card_id for row in rows}
    if not wanted:
        return {}
    found = db.execute(select(LotCard).where(LotCard.id.in_(wanted))).scalars()
    return {card.id: card for card in found}


def _job(
    row: Task, known: dict[uuid.UUID, str], cards: dict[uuid.UUID, LotCard], now: datetime
) -> Job:
    card = cards.get(row.card_id)
    left, burning, overdue = time_left(row.due_at, now)
    return Job(
        id=str(row.id),
        card_id=str(row.card_id),
        card_code=card.code if card else "",
        card_title=card.title if card else "",
        department=row.department.value,
        department_name=DEPARTMENT_NAMES[row.department],
        title=row.title,
        body=row.body,
        assignee=known.get(row.assignee_id, "") if row.assignee_id else "",
        assignee_id=str(row.assignee_id) if row.assignee_id else "",
        due_at=row.due_at.isoformat() if row.due_at else "",
        left=left,
        burning=burning,
        overdue=overdue,
        state=row.state.value,
        result=row.result,
        created_at=row.created_at.isoformat(),
    )


def _shown(
    card: LotCard,
    known: dict[uuid.UUID, str],
    *,
    role: Role,
    user_id: uuid.UUID,
    now: datetime,
    talk: Discussion | None = None,
) -> Card:
    # Срок считается только пока лот в игре. У завершённого «осталось 3 дня»
    # означало бы, что по нему ещё что-то нужно сделать.
    left, burning, overdue = (
        time_left(card.deadline, now) if card.status not in _FINAL else ("", False, False)
    )
    # Срок согласования отдельно от срока приёма: собрать подписи надо
    # раньше, и разница в два часа как раз та, из-за которой подают в спешке.
    approve_at = card.deadline - APPROVE_BEFORE if card.deadline else None
    approve_left, approve_burning, approve_overdue = (
        time_left(approve_at, now) if card.status not in _FINAL else ("", False, False)
    )
    signs = tuple(_sign(item, known, role=role) for item in _ordered(card.approvals))
    open_tasks = sum(1 for task in card.tasks if task.state is TaskState.OPEN)

    return Card(
        id=str(card.id),
        module=card.module,
        row_id=card.row_id,
        code=card.code,
        source_number=card.source_number,
        title=card.title,
        customer=card.customer,
        amount=card.amount,
        enstru_code=card.enstru_code,
        category=card.category,
        status=card.status.value,
        status_name=STATUS_NAMES[card.status],
        step=FLOW.index(card.status) + 1 if card.status in FLOW else 0,
        participation=card.participation.value,
        skip_reason=card.skip_reason,
        manager=known.get(card.manager_id, "") if card.manager_id else "",
        manager_id=str(card.manager_id) if card.manager_id else "",
        owner=known.get(card.owner_id, "") if card.owner_id else "",
        owner_id=str(card.owner_id) if card.owner_id else "",
        deadline=card.deadline.isoformat() if card.deadline else "",
        left=left,
        burning=burning,
        overdue=overdue,
        approve_by=approve_at.isoformat() if approve_at else "",
        approve_left=approve_left,
        approve_burning=approve_burning,
        approve_overdue=approve_overdue,
        note=card.note,
        won_amount=card.won_amount,
        winner=card.winner,
        started_at=card.created_at.isoformat() if card.created_at else "",
        submitted_at=card.submitted_at.isoformat() if card.submitted_at else "",
        finished_at=card.finished_at.isoformat() if card.finished_at else "",
        approvals=signs,
        approved=_all_signed(card),
        open_tasks=open_tasks,
        done_tasks=len(card.tasks) - open_tasks,
        can=_can(card, role=role, user_id=user_id),
        discussion=_talk(talk, now),
    )


def _talk(row: Discussion | None, now: datetime) -> Talk | None:
    """Обсуждение коротко. Срок считается тем же способом, что и у лота."""
    if row is None:
        return None
    left, burning, overdue = time_left(row.deadline, now)
    return Talk(
        id=str(row.id),
        stage=row.stage.value,
        stage_name=DISCUSSION_STAGE_NAMES[row.stage],
        deadline=row.deadline.isoformat() if row.deadline else "",
        left=left,
        burning=burning,
        overdue=overdue,
    )


def _opened(db: DbSession, settings: Settings | None, card: LotCard) -> None:
    """Зовёт отделы на новый лот. Отказ рассылки не роняет заведение карточки.

    Несделанная рассылка — это плохо; незаведённая карточка — хуже: человек
    нажал «взять в работу» и получил красный экран из-за того, что у бота
    неполадки.
    """
    if settings is None:
        return
    from platform_api.modules import alerts

    try:
        alerts.lot_opened(db, settings, card)
    # Ловим всё: рассылка не должна ронять работу.
    except Exception as exc:
        logger.warning("Не позвали отделы на новый лот", card=str(card.id), error=str(exc))


def _task_added(db: DbSession, settings: Settings | None, task: Task, card: LotCard) -> None:
    """Зовёт исполнителя или отдел. Отказ рассылки не роняет заведение задачи."""
    if settings is None:
        return
    from platform_api.modules import alerts

    try:
        alerts.task_added(db, settings, task, card)
    # Ловим всё: рассылка не должна ронять работу.
    except Exception as exc:
        logger.warning("Не позвали на задачу", task=str(task.id), error=str(exc))


def _ordered(approvals: Sequence[Approval]) -> list[Approval]:
    """Подписи всегда в одном порядке.

    Порядок объявления, а не тот, в каком их вернула база: строка согласования
    читается взглядом слева направо, и перестановка подписей между открытиями
    заставляет читать её заново каждый раз.
    """
    order = list(ApprovalKind)
    return sorted(approvals, key=lambda item: order.index(item.kind))


def _sign(item: Approval, known: dict[uuid.UUID, str], *, role: Role) -> Sign:
    return Sign(
        kind=item.kind.value,
        name=APPROVAL_NAMES[item.kind],
        state=item.state.value,
        by=known.get(item.by_id, "") if item.by_id else "",
        at=item.decided_at.isoformat() if item.decided_at else "",
        note=item.note,
        can_sign=role in SIGNS[item.kind],
    )


def _can(card: LotCard, *, role: Role, user_id: uuid.UUID) -> tuple[str, ...]:
    """Что этому человеку доступно на этом шаге."""
    allowed = [
        status.value
        for status in TRANSITIONS[card.status]
        if role in ALLOWED[status]
        # «Готов к участию» без всех подписей не предлагаем: кнопка, которая
        # всегда отвечает отказом, читается как поломка, а не как правило.
        and (status is not LotStatus.READY or _all_signed(card))
    ]
    if role in _DECIDES:
        allowed.append("decide")
    if role in {Role.ADMIN, Role.MANAGER}:
        allowed.append("assign")
    if any(role in SIGNS[kind] for kind in ApprovalKind):
        allowed.append("sign")
    allowed.append("task")
    return tuple(allowed)


@dataclass(frozen=True, slots=True)
class Attachment:
    """Файл, приложенный к лоту руками."""

    id: str
    name: str
    sha256: str
    size_bytes: int
    note: str
    added_by: str
    added_at: str


def files(db: DbSession, *, organization_id: uuid.UUID, card_id: uuid.UUID) -> list[Attachment]:
    """Что приложили к лоту.

    Отдельно от документов заказчика: те лежат на портале и приходят
    выгрузкой. Здесь то, что добавили мы — переписка, счёт поставщика, снимок
    экрана спецификации, — и пересборка списка их не трогает.
    """
    card = _required(db, organization_id, card_id)
    rows = list(
        db.execute(
            select(LotFile, StoredFile)
            .join(StoredFile, StoredFile.id == LotFile.file_id)
            .where(LotFile.card_id == card.id)
            .order_by(LotFile.created_at.desc())
        ).all()
    )
    known = _people_by_id(db, [link.added_by_id for link, _ in rows if link.added_by_id])
    return [
        Attachment(
            id=str(link.id),
            name=stored.original_name or stored.sha256[:12],
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            note=link.note,
            added_by=known.get(link.added_by_id, "") if link.added_by_id else "",
            added_at=link.created_at.isoformat(),
        )
        for link, stored in rows
    ]


def attach(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    card_id: uuid.UUID,
    file_id: uuid.UUID,
    added_by: uuid.UUID,
    note: str = "",
) -> LotFile:
    """Привязывает уже загруженный файл к лоту.

    Один и тот же файл к одному лоту дважды не привязывается: хранилище
    складывает по хэшу содержимого, и повторная загрузка того же счёта даёт ту
    же запись — а в списке она выглядела бы двумя разными.
    """
    card = _required(db, organization_id, card_id)
    found = db.execute(
        select(LotFile).where(LotFile.card_id == card.id, LotFile.file_id == file_id)
    ).scalar_one_or_none()
    if found is not None:
        return found

    found = LotFile(card_id=card.id, file_id=file_id, added_by_id=added_by, note=note.strip())
    db.add(found)
    db.flush()
    return found


def detach(db: DbSession, *, organization_id: uuid.UUID, link_id: uuid.UUID) -> None:
    """Отвязывает файл от лота.

    Из хранилища он не удаляется: тот же файл может быть привязан к соседнему
    лоту, а хранилище складывает по хэшу содержимого.
    """
    link = db.get(LotFile, link_id)
    if link is None:
        raise SpokenError("Файл не найден")
    card = db.get(LotCard, link.card_id)
    if card is None or card.organization_id != organization_id:
        raise SpokenError("Файл не найден")
    db.delete(link)
    db.flush()


def _people_by_id(db: DbSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    wanted = set(ids)
    if not wanted:
        return {}
    found = db.execute(select(User).where(User.id.in_(wanted))).scalars()
    return {user.id: (user.full_name or user.email) for user in found}


def _find(db: DbSession, organization_id: uuid.UUID, module: str, row_id: str) -> LotCard | None:
    return db.execute(
        select(LotCard).where(
            LotCard.organization_id == organization_id,
            LotCard.module == module,
            LotCard.row_id == row_id,
        )
    ).scalar_one_or_none()


def _required(db: DbSession, organization_id: uuid.UUID, card_id: uuid.UUID) -> LotCard:
    card = db.get(LotCard, card_id)
    if card is None or card.organization_id != organization_id:
        raise SpokenError("Лот не найден")
    return card


def _all_signed(card: LotCard) -> bool:
    signed = {item.kind for item in card.approvals if item.state is ApprovalState.APPROVED}
    return signed == set(ApprovalKind)


def people(db: DbSession, rows: Sequence[LotCard] | Sequence[Task]) -> dict[uuid.UUID, str]:
    """Имена людей одним запросом.

    Одним, а не по запросу на строку: список открывают чаще всего, и сотня
    строк превращалась бы в сотню походов в базу за именем, которое почти у
    всех одно и то же.
    """
    wanted: set[uuid.UUID] = set()
    for row in rows:
        for field in ("manager_id", "owner_id", "assignee_id"):
            value = getattr(row, field, None)
            if value:
                wanted.add(value)
    if not wanted:
        return {}
    found = db.execute(select(User).where(User.id.in_(wanted))).scalars()
    return {user.id: (user.full_name or user.email) for user in found}


def time_left(when: datetime | None, now: datetime) -> tuple[str, bool, bool]:
    """Сколько осталось, словами. Возвращает ещё «горит» и «просрочено»."""
    if when is None:
        return "", False, False
    left = when - now
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
    "APPROVAL_NAMES",
    "APPROVE_BEFORE",
    "DEPARTMENT_NAMES",
    "DEPARTMENT_OF",
    "FLOW",
    "SIGNS",
    "STATUS_NAMES",
    "TRANSITIONS",
    "Attachment",
    "Card",
    "Filters",
    "Job",
    "Person",
    "Sign",
    "Snapshot",
    "add_task",
    "assign",
    "attach",
    "by_row",
    "close_task",
    "decide",
    "detach",
    "files",
    "listing",
    "move",
    "one",
    "open_card",
    "people",
    "result",
    "sign",
    "take_task",
    "task",
    "tasks",
    "time_left",
]
