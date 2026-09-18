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

from sqlalchemy import func, or_, select

from platform_api.auth.permissions import Permission
from platform_api.config import Settings
from platform_api.db.base import utcnow
from platform_api.db.models import (
    Approval,
    ApprovalKind,
    ApprovalState,
    CustomRole,
    Department,
    Discussion,
    DiscussionOutcome,
    DiscussionStage,
    LotCard,
    LotEvent,
    LotFile,
    LotFolder,
    LotOutcome,
    LotSeat,
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
    LotStatus.WORK: "В работе",
    LotStatus.APPROVAL: "На согласовании",
    LotStatus.SUBMISSION: "Подача",
    LotStatus.WAITING: "Ожидание протокола итогов",
    LotStatus.DONE: "Завершённый",
}

OUTCOME_NAMES: dict[LotOutcome, str] = {
    LotOutcome.NONE: "Итога нет",
    LotOutcome.WON: "Выиграли",
    LotOutcome.LOST: "Проиграли",
    LotOutcome.NOT_SUBMITTED: "Не успели подать",
    LotOutcome.NOT_LIQUID: "Не ликвидный тендер",
    LotOutcome.WRONG_CODE: "Код ТРУ не подходит",
    LotOutcome.CANCELLED: "Тендер отменён",
    LotOutcome.SKIPPED: "Не участвуем",
}

BY_DECISION: frozenset[LotOutcome] = frozenset(
    {
        LotOutcome.NOT_SUBMITTED,
        LotOutcome.NOT_LIQUID,
        LotOutcome.WRONG_CODE,
        LotOutcome.CANCELLED,
        LotOutcome.SKIPPED,
    }
)
"""Итоги, которые ставит человек, а не протокол.

Выигрыш и проигрыш приходят с протоколом и вместе с ценой: у них своя дверь
(`result`), и она требует поданной заявки. Остальные пять — это наше решение
или наша оплошность, и заявки по ним как раз и не было.
"""

NEEDS_REASON: frozenset[LotOutcome] = frozenset(
    {
        LotOutcome.NOT_LIQUID,
        LotOutcome.WRONG_CODE,
        LotOutcome.CANCELLED,
        LotOutcome.SKIPPED,
    }
)
"""Итоги, которые нельзя поставить молча.

У выигрыша и проигрыша объяснение — сам протокол, и оно рядом: цена и
победитель. У «не успели подать» причину пишет прогон. А «не ликвидный»,
«не тот код», «отменён» и «не участвуем» — это наше решение, и через месяц
на вопрос «почему прошли мимо этой закупки» отвечать будет нечем.
"""

# Порядок хода. По нему рисуется полоса в карточке: человек должен видеть, где
# лот стоит и сколько шагов до конца, а не одно слово без контекста.
FLOW: tuple[LotStatus, ...] = (
    LotStatus.WORK,
    LotStatus.APPROVAL,
    LotStatus.SUBMISSION,
    LotStatus.WAITING,
    LotStatus.DONE,
)

# Тупик один: дошедший до «Завершённого» получает `finished_at`. Чем именно
# кончилось, говорит итог, а не статус.
_FINAL = frozenset({LotStatus.DONE})


def submitted(card: LotCard) -> bool:
    """Подана ли заявка по лоту.

    Не по одной отметке времени. `submitted_at` ставит человек, нажимая «Подал»
    и называя сумму участия, — но переводить лот можно откуда угодно куда
    угодно, это снято намеренно, и лот, отправленный сразу в «Завершённый» с
    итогом «Выиграли», отметки не получил. Выиграть, не подавая заявку, нельзя.

    Завершённый сам по себе о подаче не говорит: там же лежат лоты, которые мы
    решили пропустить. Отличает их итог — он и спрашивается.

    Отметку задним числом не дорисовываем: время подачи мы не знаем, а
    придуманное хуже отсутствующего — по нему потом считают сроки.
    """
    if card.submitted_at is not None:
        return True
    if card.status is LotStatus.WAITING:
        return True
    return card.status is LotStatus.DONE and card.outcome is not LotOutcome.NONE


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
    # «В работе» объявляют те, кто в нём и работает: обсуждение заводит юрист,
    # разбор — тендерщик, и бежать за менеджером ради перевода незачем.
    LotStatus.WORK: _RUNS | {Role.LAWYER, Role.ANALYST},
    LotStatus.APPROVAL: _RUNS | {Role.ANALYST},
    LotStatus.SUBMISSION: _RUNS,
    LotStatus.WAITING: _RUNS,
    # Завершить может и тот, кто решает об участии: лот, который мы проходим
    # мимо, закрывает руководитель, а не менеджер задним числом.
    LotStatus.DONE: _DECIDES,
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

DESKS: tuple[tuple[Department, str, str], ...] = (
    (Department.ANALYSIS, "Поставка", "delivery"),
    (Department.DISCUSSION, "Обсуждение", "discussion"),
    (Department.LEGAL, "Юрист", "lawyer"),
    (Department.SUPPLY, "Снабжение", "buyer"),
    (Department.TECHNOLOGIST, "Технолог", "technologist"),
)
"""Пять отделов, у каждого своё место в лоте: отдел, слово и ключ роли.

«Поставка» села на отдел разбора намеренно: у нас это один человек — он
считает себестоимость и он же ведёт поставку. Заводить рядом шестой отдел
значило бы развести стол разбора, его задачи и подстатусы по двум местам, а
работает там один и тот же сотрудник.

Ключ роли — **подсказка, а не замок**. По нему решается, кого предложить и
кому слать уведомление; посадить в строку можно кого угодно. Иначе уволившийся
единственный юрист запирает строку до тех пор, пока администратор не выдаст
кому-то роль, — а лот к этому времени уже ушёл по сроку.
"""

DESK_TITLES = {desk: title for desk, title, _ in DESKS}
DESK_ROLE_KEYS = {desk: key for desk, _, key in DESKS}

LEAD = Department.ANALYSIS
"""Отдел, который ведёт лот. «Поставка»: она же считает себестоимость.

Вынесено именем, а не вписано по месту: «кто ведёт лот» спрашивают в пяти
местах — подстатус, отбор «мои», рассылка, отметка в списке, — и каждое из них
должно смотреть на одно и то же место.
"""


def seated(card: LotCard, desk: Department) -> uuid.UUID | None:
    """Кто сидит в этом отделе по лоту. `None` — место свободно."""
    for row in card.seats:
        if row.desk is desk:
            return row.user_id
    return None


def _seat(card: LotCard, desk: Department) -> LotSeat:
    """Строка отдела. Заводит недостающую: карточки бывают заведены до того,
    как отделы появились, и «строки нет» читателю знать незачем."""
    for row in card.seats:
        if row.desk is desk:
            return row
    made = LotSeat(card_id=card.id, desk=desk)
    card.seats.append(made)
    return made


def _seats_out(
    card: LotCard,
    known: dict[uuid.UUID, str],
    *,
    role: Role,
    user_id: uuid.UUID,
    permissions: frozenset[Permission],
) -> tuple[Seat, ...]:
    """Пять строк отделов по порядку — так, как их показывают.

    Порядок объявления, а не тот, в каком их вернула база: столбец читают
    сверху вниз, и перестановка строк между открытиями заставляет искать
    нужную заново.
    """
    rows = {row.desk: row for row in card.seats}
    out: list[Seat] = []
    for desk, title, _ in DESKS:
        row = rows.get(desk)
        who = row.user_id if row is not None else None
        # Сесть самому — своё право у каждого, кто работает с лотами: работу
        # своего отдела берут себе сами. Посадить другого — право руководящее.
        can: list[str] = []
        if who is None:
            can.append("take")
        if _may(Permission.LOT_ASSIGN, permissions) or role in {Role.ADMIN, Role.MANAGER}:
            can.append("assign")
        out.append(
            Seat(
                desk=desk.value,
                title=title,
                name=(known.get(who) if who else "") or (row.by_name if row else ""),
                user_id=str(who) if who else "",
                taken_at=row.taken_at.isoformat() if row and row.taken_at else "",
                can=tuple(can),
            )
        )
    return tuple(out)


def sits_anywhere(card: LotCard, user_id: uuid.UUID) -> bool:
    """Занимает ли человек хоть одно место в лоте. По этому и считается «моё»:
    вопрос «что на мне» не различает, в каком именно отделе."""
    return any(row.user_id == user_id for row in card.seats)


@dataclass(frozen=True, slots=True)
class Seat:
    """Место отдела в лоте так, как его показывают."""

    desk: str
    title: str
    name: str
    user_id: str
    taken_at: str
    can: tuple[str, ...] = ()
    """Что можно нажать на этой строке: `take` — сесть самому, `assign` —
    посадить другого. Решает сервер: второй набор правил в браузере разойдётся
    с первым, и человек нажмёт кнопку, получив отказ."""


def seats_of(card: LotCard, known: dict[uuid.UUID, str]) -> dict[Department, LotSeat]:
    """Места лота по отделам. Недостающие не выдумываем — их заводит `open_card`."""
    return {row.desk: row for row in card.seats}


def people_of_role(db: DbSession, organization_id: uuid.UUID, key: str) -> list[uuid.UUID]:
    """Кто в этой роли — встроенной или заведённой администратором.

    Одним запросом и по обоим путям сразу: у своей роли человек привязан
    ссылкой на `custom_roles`, у встроенной — значением в `memberships.role`,
    и спрашивать их порознь значит однажды забыть второй.
    """
    rows = db.execute(
        select(Membership.user_id, Membership.role, CustomRole.key)
        .join(User, User.id == Membership.user_id)
        .outerjoin(CustomRole, CustomRole.id == Membership.custom_role_id)
        .where(Membership.organization_id == organization_id, User.is_active.is_(True))
    ).all()
    return [user_id for user_id, role, own in rows if (own or role.value) == key]


WORK_STAGES: tuple[tuple[str, str], ...] = (
    ("legal", "У юристов"),
    ("talk", "В обсуждении"),
    ("desk", "В разборе"),
    ("supply", "У снабжения"),
    ("done", "Разбор закончен"),
)
"""Где сейчас мяч. Верхний ряд отбора внутри «В работе».

Лот попадает ровно в одну кнопку — это лестница, а не набор признаков: в
списке у строки одно место, и лот, подходящий под три ответа сразу, должен
попасть в тот, который ближе всего к действию.

Порядок объявления и есть порядок разбора. Юристы первыми: у обсуждения срок
два рабочих дня со дня публикации, а поиск товара идёт неделями — застрявший у
юристов лот теряется быстрее. Дальше само обсуждение, потом разбор, снабжение
и законченное.
"""

WORK_STAGE_NAMES = dict(WORK_STAGES)


def work_stage(
    card: LotCard,
    *,
    talk: Discussion | None,
    talking: bool,
    to_supply: bool,
    now: datetime,
) -> str:
    """Где сейчас мяч по этому лоту.

    Окно обсуждения считается открытым, пока письмо не ушло и срок не вышел.
    Просроченное ненаписанное мяча не держит: отправлять уже нечего, и
    показывать такой лот в «В обсуждении» значит звать делать работу, которую
    сделать нельзя.

    Открытая задача отдела держит мяч независимо от сроков — её кто-то должен
    закрыть, и пока она висит, лот у этого отдела.
    """
    live = [task for task in card.tasks if task.state is TaskState.OPEN]
    open_talk = (
        talking
        and talk is not None
        and talk.stage not in {DiscussionStage.SENT, DiscussionStage.NOT_NEEDED}
        and (talk.deadline is None or talk.deadline > now)
    )

    if any(task.department is Department.LEGAL for task in live) or (
        open_talk and talk is not None and talk.stage is DiscussionStage.WITH_LAWYERS
    ):
        return "legal"
    if (
        open_talk
        and talk is not None
        and (
            not talk.text.strip()
            or talk.stage in {DiscussionStage.DRAFTING, DiscussionStage.MODERATION}
        )
    ):
        return "talk"
    # Открытая задача разбора — это и первый разбор, и возврат из снабжения:
    # товара по части позиций нет или цена не набирается, и таблицу
    # переделывают. Мяч в обоих случаях у разбора.
    if seated(card, LEAD) is None or any(task.department is Department.ANALYSIS for task in live):
        return "desk"
    if any(task.department is Department.SUPPLY for task in live):
        return "supply"
    return "done" if to_supply else "desk"


TALK_STAGES: tuple[tuple[str, str], ...] = (
    ("none", "Не написано"),
    ("running", "В процессе"),
    ("sent", "Письмо отправлено"),
    ("accepted", "Письмо удовлетворили"),
    ("rejected", "Письмо отклонили"),
    ("not_needed", "Письмо не требуется"),
)
"""Где обсуждение по лоту — словами отбора в списке.

Не то же самое, что `DiscussionStage`. Тот отвечает на вопрос «что мы с ним
делаем» и нужен в самом разделе обсуждений; здесь вопрос другой — «чего по
этому лоту ждать», и ответов на него меньше. Три этапа написания сходятся в
«в процессе»: тендерщику, смотрящему список из сотни лотов, разница между
«пишется» и «на проверке» не меняет ничего, а три колонки вместо одной делают
отбор нечитаемым.
"""

DESK_STAGES: tuple[tuple[str, str], ...] = (
    ("unowned", "Разбор не начат"),
    ("legal", "У юристов"),
    ("supply", "У снабженцев"),
    ("done", "Разбор закончен"),
    ("running", "Разбор в процессе"),
)
"""Где лот внутри «В работе» — по отделам.

Порядок здесь не для показа, а для разбора: лот бывает сразу в двух местах —
у юристов по обсуждению и у снабжения по задачам, — и показать его надо один
раз. Юристы идут раньше снабжения намеренно: у обсуждения срок в два рабочих
дня со дня публикации, а поиск товара идёт неделями. Лот, застрявший у
юристов, теряется быстрее, и в отборе он должен попасться на глаза первым.
"""

TALK_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("finished", "Завершённые", ("sent", "accepted", "rejected")),
)
"""Кнопки, собирающие несколько подстатусов под одним словом.

Состав здесь, а не в браузере. «По каким письмам уже есть ответ» спрашивают
чаще, чем «сколько именно удовлетворили», и группа нужна; но второе такое же
определение на другом языке разойдётся с первым молча — в платформе уже есть
`_TALK_DONE`, где завершённым считается совсем другое.
"""

TALK_STAGE_NAMES = dict(TALK_STAGES)
DESK_STAGE_NAMES = dict(DESK_STAGES)


def talk_stage(talk: Discussion | None, *, talking: bool = True) -> str:
    """Где обсуждение по лоту.

    Нет обсуждения — «не написано», и это не то же самое, что «не требуется»:
    первое значит, что до лота не дошли руки, второе — что посмотрели и
    решили не трогать. Смешать их значит потерять ровно ту работу, которую
    ищут в этом отборе.

    Признак «не написано» — пустой текст, а не этап. Менеджер возвращает
    готовое письмо на переделку обратно в «Пишется», и по этапу такой лот
    числился бы ненаписанным при полном тексте — то есть попадал бы в отбор
    «до него не дошли руки», хотя руки дошли дважды.
    """
    if not talking:
        # Площадка обсуждений не ведёт — в тендерный отбор закупки приходят
        # папкой по почте, и обсуждать их не с кем. Пусто, а не «не написано»:
        # иначе весь отбор оказался бы в подстатусе «до него не дошли руки».
        return ""
    if talk is None or not talk.text.strip():
        return "none"
    if talk.stage is DiscussionStage.NOT_NEEDED:
        return "not_needed"
    if talk.stage is not DiscussionStage.SENT:
        return "running"
    if talk.outcome is DiscussionOutcome.ACCEPTED:
        return "accepted"
    # Закрытое после отказа и ушедшее на жалобу — тоже отказ: заказчик
    # требование не снял, и участвовать придётся с ним.
    if talk.outcome in {
        DiscussionOutcome.REJECTED,
        DiscussionOutcome.CLOSED,
        DiscussionOutcome.COMPLAINT,
    }:
        return "rejected"
    return "sent"


def desk_stage(card: LotCard, *, talk: Discussion | None, to_supply: bool) -> str:
    """Где лот по отделам внутри «В работе».

    Лестницей, а не набором признаков: в списке у строки одно место, и лот,
    подходящий под три подстатуса сразу, должен попасть в тот, который ближе
    всего к действию.

    «Не начат» — выше всего: пока лот никто не ведёт, остальное не имеет
    значения, и именно такие лоты и ищут в этом отборе. До сих пор их было
    видно только по пустой колонке «Ведёт».
    """
    if seated(card, LEAD) is None:
        return "unowned"

    live = [task for task in card.tasks if task.state is TaskState.OPEN]
    if talk is not None and talk.stage is DiscussionStage.WITH_LAWYERS:
        return "legal"
    if any(task.department is Department.LEGAL for task in live):
        return "legal"
    # Открытая задача разбора — это возврат из снабжения: товара по части
    # позиций нет или цена не набирается, и таблицу переделывают. Проверяется
    # раньше снабжения: таблица снабжению уже заведена, и без этой строки
    # вернувшийся лот числился бы законченным — то есть пропадал бы из
    # отбора ровно тогда, когда над ним и идёт работа.
    if any(task.department is Department.ANALYSIS for task in live):
        return "running"
    if any(task.department is Department.SUPPLY for task in live):
        return "supply"
    # Таблица снабжению ушла, незакрытых задач по ней нет — разбор своё
    # отработал и ждёт согласования.
    return "done" if to_supply else "running"


SIGN_RIGHTS: dict[ApprovalKind, Permission] = {
    ApprovalKind.MANAGER: Permission.SIGN_MANAGER,
    ApprovalKind.SUPPLY: Permission.SIGN_SUPPLY,
    ApprovalKind.LEGAL: Permission.SIGN_LEGAL,
    ApprovalKind.TECHNOLOGIST: Permission.SIGN_TECHNOLOGIST,
    ApprovalKind.ASSEMBLER: Permission.SIGN_ASSEMBLER,
}
"""Какое право отвечает за какую подпись.

Наборы в `SIGNS` и права в `BUILT_IN` совпадают роль в роль — это перевод
одного и того же на два языка. Таблица нужна, чтобы своя роль, которой выдали
подпись снабжения, могла её поставить: по имени роли она «Наблюдатель».
"""

MOVE_RIGHTS: dict[LotStatus, Permission] = {
    LotStatus.WORK: Permission.MOVE,
    LotStatus.APPROVAL: Permission.MOVE,
    LotStatus.SUBMISSION: Permission.MOVE,
    LotStatus.WAITING: Permission.MOVE,
    LotStatus.DONE: Permission.DECIDE,
}
"""Каким правом двигают лот по состояниям.

Завершение — за тем, кто решает об участии: лот, мимо которого прошли,
закрывает руководитель, а не менеджер задним числом.

Право одно на четыре шага, а не своё на каждый: «двигать лот» — это одно
умение, и дробить его на четыре галочки значит заставить администратора
ставить их всегда вчетвером.
"""

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


DEFAULT_WORK = timedelta(hours=1)
"""Сколько даётся на задачу, если срок не назвали.

Час — не срок отклика, а срок работы: столько занимает большинство задач
целиком. Раньше сроков было два — «взять до» у ничьей задачи и «сделать до» у
взятой, — и второй назначал себе исполнитель в момент взятия. Это давало
задаче, заведённой под конец приёма, срок позже самого приёма: человек берёт в
16:50 «на три часа», а заявку подают в 18:00.

Теперь срок один и ставит его тот, кто задачу завёл: он знает, к какому часу
нужен ответ. Взятие срок не двигает.
"""

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
    # «В работе» держат разом четыре отдела, и какой из них «тот самый», по
    # статусу не сказать. Разбор — потому что с него начинают: он считает,
    # берёмся ли вообще, и задача без указанного отдела чаще всего его.
    LotStatus.WORK: Department.ANALYSIS,
    LotStatus.APPROVAL: Department.APPROVAL,
    LotStatus.SUBMISSION: Department.SUBMISSION,
    LotStatus.WAITING: Department.SUBMISSION,
    LotStatus.DONE: Department.SUBMISSION,
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

    taken_at: str = ""
    """Когда взяли. Пусто — ещё ничья, и срок означает «взять до», а не
    «сделать до». Экрану это нужно, чтобы не писать «просрочена» там, где
    просрочен отклик, а не работа."""

    done_at: str = ""
    done_by: str = ""
    """Кто закрыл. Не тот же, кто взял: задачу передают и доделывают за
    коллегу."""

    author: str = ""
    """Кто поставил. Вопрос «а кто это придумал» задают ровно тогда, когда
    задача выглядит лишней, — и адресовать его нужно не исполнителю."""

    author_id: str = ""
    """Кто поставил, ключом. По нему экран решает, показывать ли правку и
    снятие: поручение отзывает тот, кто его дал, и администратор."""

    talk: int = 0
    """Сколько реплик в переписке задачи.

    Числом на строке, а не только внутри. Разговор о задаче — это половина
    работы по ней («подойдёт ли вот этот?»), и задачу открывают ради него;
    строка без числа выглядит нетронутой, и ответа ждут сутки."""

    card_amount: Decimal | None = None
    """Сумма закупки по снимку карточки. Нужна в очереди отдела: за что взяться,
    человек решает по деньгам и сроку, а до сих пор в строке стояло одно
    название — за остальным он открывал лот по одному."""

    card_customer: str = ""
    """Заказчик. Отвечает на «чья это закупка»: по нему узнают тех, с кем уже
    работали, и тех, с кем связываться не стоит."""


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

    writing: str = ""
    """Как идёт написание моделью: `queued`, `running`, `ready`, `failed`.

    В карточке, а не только в разделе обсуждений. Написание запускается само
    при взятии лота в работу, и человек, открывший карточку через минуту,
    должен видеть, что работа идёт, — иначе пустое обсуждение выглядит
    незаведённым, и он нажимает «написать» второй раз."""


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
    outcome: str
    outcome_name: str

    taken_by: str
    taken_by_id: str
    """Кто взял закупку в работу. Ставится один раз и не переписывается: до
    сих пор этот человек молча становился менеджером, и первое же назначение
    его затирало."""

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

    status_at: str
    """Когда статус менялся последний раз. По нему список и отсортирован —
    свежее сверху."""

    bid_amount: Decimal | None
    """За сколько подали заявку. Пусто — не подавали или подали до того, как
    сумму стали спрашивать."""

    submitted_at: str
    submitted: bool
    """Подана ли заявка. Считает сервер: правило шире одной отметки времени, и
    второй такой же расчёт в браузере разошёлся бы с первым."""
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

    desks: tuple[DeskMark, ...] = ()
    """Отработали ли отделы. Четыре точки в строке списка и галочки в карточке.

    Считает сервер, а не браузер: правила у отделов разные и не выводятся одно
    из другого, а список и карточка должны говорить одно и то же."""

    talk_stage: str = ""
    talk_stage_name: str = ""
    """Где обсуждение по лоту — ключ и слово. Пусто у площадок без обсуждений.

    Считает сервер по тем же данным, что и раздел обсуждений. В браузере это
    развалилось бы на два правила: он видит не все поля — исход заказчика в
    список не приезжал вовсе, — и «отправлено» от «отклонили» отличить ему
    нечем."""

    stage: str = ""
    stage_name: str = ""
    """Где сейчас мяч: `legal`, `talk`, `desk`, `supply`, `done`. Лот попадает
    ровно в одну кнопку верхнего ряда — это лестница, а не набор признаков."""

    seats: tuple[Seat, ...] = ()
    """Пять отделов и кто в них. Место занимают сами («беру на себя») или
    сажают те, кто вправе поручать."""

    desk_stage: str = ""
    desk_stage_name: str = ""
    """Где лот по отделам внутри «В работе»: не начат, у юристов, у
    снабженцев, закончен, в процессе.

    Полем в ответе, а не выводом в браузере: правило лестничное и опирается на
    таблицу снабжения, которой в списке нет и быть не должно — это отдельная
    запись на каждый лот."""


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
        # Взяли в работу — значит, в работе. Отдельного «Нового» больше нет:
        # он означал «появился в выгрузке, никто не смотрел», а карточка и
        # заводится тем, кто уже посмотрел. Лишний шаг, который все пролистывали
        # не глядя, и первый вопрос по нему был «а что с ним делать».
        status=LotStatus.WORK,
        status_at=utcnow(),
        participation=Participation.MAYBE,
        # Взявший не становится ответственным ни за что. Лот с портала берёт
        # госзакупщик — он его нашёл, — но разбор считает не он. Пока взявший
        # молча становился менеджером, лот выглядел разобранным: в списке
        # стояло его имя, тендерщики видели занятую работу и проходили мимо, а
        # он ждал, что разберут.
        taken_by_id=by,
        taken_by_name=_name_of(db, by),
    )
    db.add(found)
    db.flush()

    # Пять мест отделов и пять подписей заводятся сразу пустыми — «строки
    # нет» и «строка пуста» должны выглядеть одинаково.
    #
    # Через связи, а не `db.add` с готовым `card_id`: иначе коллекция у
    # карточки останется пустой до следующего чтения из базы, и служба,
    # которая тут же спросит `card.approvals`, заведёт их второй раз.
    found.seats.extend(LotSeat(desk=desk) for desk, _, _ in DESKS)
    found.approvals.extend(Approval(kind=kind) for kind in ApprovalKind)
    db.flush()

    _opened(db, settings, found)
    _seats_told(db, settings, found)

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


def _seats_told(db: DbSession, settings: Settings | None, card: LotCard) -> None:
    """Говорит отделам про новый лот. Отказ рассылки не роняет взятие."""
    if settings is None:
        return
    from platform_api.modules import alerts

    try:
        alerts.seats_filled(db, settings, card)
    except Exception as exc:  # рассылка не должна ронять работу
        logger.warning("Не позвали отделы", card=str(card.id), error=str(exc))


def _may(
    permission: Permission,
    permissions: frozenset[Permission],
) -> bool:
    """Есть ли право. Администратор проходит везде — как и в `Identity.can`."""
    return Permission.ADMIN in permissions or permission in permissions


def _may_move(to: LotStatus, permissions: frozenset[Permission]) -> bool:
    """Можно ли перевести лот в это состояние по праву."""
    right = MOVE_RIGHTS.get(to)
    return right is not None and _may(right, permissions)


"""Право или встроенная роль — годится любое из двух.

Проверки по именам ролей писались до того, как появились права, и переписать
их разом нельзя: у каждого действия свой набор ролей, и одно право вместо
шести наборов раздало бы тендерщику возврат лота в «Новый».

Поэтому право добавлено вторым путём, а не заменой. Встроенным ролям это не
меняет ничего — их наборы прав в `BUILT_IN` собраны ровно из этих же списков,
— а своя роль наконец начинает работать: до сих пор она проваливалась во все
проверки сразу, потому что встроенная часть у неё «Наблюдатель» (самое
безопасное значение), и сравнение с ролью всегда отвечало «нельзя».
"""


def move(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    card_id: uuid.UUID,
    role: Role,
    user_id: uuid.UUID,
    to: LotStatus,
    reason: str = "",
    permissions: frozenset[Permission] = frozenset(),
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
    if role not in ALLOWED[to] and not _may_move(to, permissions):
        raise SpokenError(f"Перевести лот в «{STATUS_NAMES[to]}» вам нельзя")
    # Запрет один, и он про деньги: подавать без пяти подписей — это участие в
    # закупке, товара под которую нет. Стоял он на «Готов к участию»; теперь на
    # «Подаче» — состоянии, из которого заявка и уходит.
    if to is LotStatus.SUBMISSION and not _all_signed(card):
        raise SpokenError("Не все подписи под участием собраны")
    # Второй запрет — про причину — переехал в решение об участии (`decide`):
    # состояния «Не участвуем» больше нет, а причина спрашивается там же, где
    # принимается само решение.

    card.status = to

    card.status_at = utcnow()
    if to is LotStatus.WAITING and card.submitted_at is None:
        # Подачу отмечают кнопкой с суммой (`submit`), но лот переводят и
        # руками. Отметку ставим и здесь: «ждём протокол» без поданной заявки
        # не бывает, а красный срок на таком лоте означал бы, что мы не подали.
        card.submitted_at = utcnow()
    if to in _FINAL:
        card.finished_at = utcnow()
    # Участие перестаёт быть «может быть» на любом шаге дальше нового: лот
    # ведут, значит, участвуем. Отказ ставится решением, и его не трогаем.
    if card.participation is not Participation.NO:
        card.participation = Participation.YES
    # Ведущего перевод больше не перехватывает. Пока полей было два, любой
    # перевод статуса молча забирал лот на себя; при пяти строках это
    # переписывало бы «Юриста» на того, кто двинул лот на согласование.
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


def advance(
    db: DbSession,
    *,
    card: LotCard,
    to: LotStatus,
    why: str,
) -> bool:
    """Двигает лот вперёд по итогу фоновой работы. Возвращает, сдвинулся ли.

    Ради того, чтобы статус не приходилось выставлять руками после каждого
    прогона. Лот берут в работу — он «Новый»; модель дописала замечание — он
    «Обсуждение»; собрался разбор спецификации — «На разборе». Человек эти
    переводы всё равно делал, только позже и не всегда: лот с готовым разбором
    неделю числился новым, и на планёрке его считали нетронутым.

    **Только вперёд и только по дорожке.** Порядок берётся из `FLOW`, и если
    лот уже дальше — прогон его не трогает: разбор досчитался через десять
    минут после того, как менеджер отправил лот на согласование, и откат туда,
    где он был, стёр бы работу человека. Завершённый и тот, по которому решили
    не участвовать, не двигаются вовсе: там решение принято, и фоновая задача
    его не пересматривает.

    **Прав тут не спрашивают, и это осознанно.** `ALLOWED` отвечает на вопрос
    «кому можно нажать кнопку», а здесь кнопки нет: перевод — следствие
    работы, которую человек уже заказал, взяв лот в работу. Записывается он
    отметкой машины (`by_machine`), поэтому в сводке «кто работал» не крадёт
    премию у людей.
    """
    if card.status is to:
        return False
    if card.status in _FINAL or card.participation is Participation.NO:
        return False

    order = {status: place for place, status in enumerate(FLOW)}
    here, there = order.get(card.status), order.get(to)
    if here is None or there is None or here >= there:
        return False

    was = card.status
    card.status = to
    card.status_at = utcnow()
    trace(
        db,
        card_id=card.id,
        kind="moved",
        title=f"Перевёл в «{STATUS_NAMES[to]}»",
        detail=why,
        by_machine=True,
        moved_from=was,
        moved_to=to,
    )
    db.flush()
    logger.info("cards.advanced", card=card.code, was=was.value, now=to.value)
    return True


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

    Имя — тоже копией. Ссылка на человека обнуляется, когда его запись удаляют,
    и без имени лента превратилась бы в список действий без авторов: «перевёл в
    „Подача“» без имени неотличимо от прогона по расписанию.
    """
    db.add(
        LotEvent(
            card_id=card_id,
            actor_id=actor_id,
            actor_name=_name_of(db, actor_id),
            actor_role=role.value if role is not None else "",
            by_machine=by_machine,
            kind=kind,
            title=title[:255],
            detail=detail.strip()[:4000],
            from_status=moved_from.value if moved_from else "",
            to_status=moved_to.value if moved_to else "",
        )
    )


def _name_of(db: DbSession, user_id: uuid.UUID | None) -> str:
    """Имя человека для записи в историю. Пусто — действие без входа.

    Читается из сессии, которая уже держит объект: за именем в базу второй раз
    не идём, а если человека в ней нет вовсе, пустая строка честнее выдуманной.
    """
    if user_id is None:
        return ""
    found = db.get(User, user_id)
    return (found.full_name or found.email) if found is not None else ""


def decide(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    card_id: uuid.UUID,
    role: Role,
    participation: Participation,
    reason: str = "",
    user_id: uuid.UUID | None = None,
    permissions: frozenset[Permission] = frozenset(),
) -> LotCard:
    """Берём лот в работу или нет.

    Отдельно от статуса: это первый отсев, до всякой работы. Под наши коды
    приходит вчетверо больше, чем мы способны разобрать.
    """
    card = _required(db, organization_id, card_id)
    if role not in _DECIDES and not _may(Permission.DECIDE, permissions):
        raise SpokenError("Решать об участии вам нельзя")
    if participation is Participation.NO and not reason.strip():
        raise SpokenError("Укажите причину отказа от участия")

    # «Да» по лоту, который мы сами и закрыли, возвращает его в работу. Иначе
    # переключатель врёт: участвуем — а лот числится завершённым, и найти его
    # можно только во вкладке «Завершённые». Протокольные итоги так не
    # отменяются: выигрыш и проигрыш — не наше решение, и стирать их нажатием
    # нельзя.
    if participation is Participation.YES and card.outcome in NEEDS_REASON:
        card.outcome = LotOutcome.NONE
        card.finished_at = None
        if card.status is LotStatus.DONE:
            card.status = LotStatus.WORK
            card.status_at = utcnow()

    card.participation = participation
    card.skip_reason = reason.strip()[:2000] if participation is Participation.NO else ""
    if participation is Participation.NO and card.status not in _FINAL:
        # Отдельного состояния «Не участвуем» больше нет: работа над лотом
        # кончилась, и это «Завершённый» — с пустым итогом, потому что
        # протокола по нам не будет. Отличает такие лоты само решение
        # (`participation`) и причина рядом с ним.
        card.status = LotStatus.DONE
        card.status_at = utcnow()
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
    permissions: frozenset[Permission] = frozenset(),
) -> LotCard:
    """Ставит подпись отдела под участием.

    Отказ требует причины. Подпись «нет» без слова о том, что не так, ставит
    работу и не говорит, что чинить.
    """
    card = _required(db, organization_id, card_id)
    if role not in SIGNS[kind] and not _may(SIGN_RIGHTS[kind], permissions):
        raise SpokenError(f"Подпись «{APPROVAL_NAMES[kind]}» ставите не вы")
    if state is ApprovalState.REJECTED and not note.strip():
        raise SpokenError("Укажите, что мешает согласовать")

    found = next((item for item in card.approvals if item.kind is kind), None)
    if found is None:
        found = Approval(card_id=card.id, kind=kind)
        db.add(found)
    found.state = state
    found.by_id = user_id
    # Имя копией: «кто это одобрил» спрашивают через полгода, когда человек мог
    # уволиться и его запись удалить — ссылка к тому времени обнулена.
    found.by_name = _name_of(db, user_id)
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


def submit(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    card_id: uuid.UUID,
    role: Role,
    amount: Decimal,
    user_id: uuid.UUID | None = None,
) -> LotCard:
    """Отмечает поданную заявку и запоминает, за сколько подали.

    **Сумма обязательна, и это главное в этой команде.** Подача до сих пор
    была одним нажатием: лот переводили в «Ждём итоги», и всё, что о ней
    оставалось, — время перевода. За сколько заходили, держали в голове и в
    переписке, а спрашивают это ровно тогда, когда итоги пришли: насколько
    промахнулись и с какой маржой брали бы. Через месяц вспомнить некому.

    Отметка ставится здесь, а не выводится из состояния. Переводить лот можно
    откуда угодно куда угодно — это снято намеренно, — и состояние «Договор»
    говорит о подаче лишь косвенно. Здесь же человек нажал «Подал» и назвал
    сумму: дальше лот знает об этом постоянно, и срок приёма красится по этому
    признаку, а не по догадке.

    Повторная подача не заводит вторую: сумма поправляется, время остаётся
    первым. Поправляют её обычно сразу — ошиблись разрядом, — а «когда подали»
    от этого не меняется.
    """
    card = _required(db, organization_id, card_id)
    if role not in _RUNS:
        raise SpokenError("Отмечать подачу вам нельзя: это делает менеджер")
    if amount <= 0:
        raise SpokenError("Назовите сумму, за которую участвуем: без неё подача не считается")

    was = card.submitted_at
    card.bid_amount = amount
    card.submitted_at = was or utcnow()
    card.participation = Participation.YES
    # Двигаем по пути, а не выставляем жёстко: лот мог уже уехать дальше —
    # например, сразу в «Завершённый» с итогом, — и возвращать его в ожидание
    # протокола значит стирать то, что человек уже отметил.
    order = {status: place for place, status in enumerate(FLOW)}
    if order.get(card.status, -1) < order[LotStatus.WAITING]:
        card.status = LotStatus.WAITING
        card.status_at = utcnow()
    trace(
        db,
        card_id=card.id,
        kind="submit",
        title="Отметил подачу" if was else "Подал заявку",
        actor_id=user_id,
        role=role,
        detail=f"{amount:,.0f} ₸".replace(",", " "),
    )
    db.flush()
    db.refresh(card)
    return card


def finish(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    card_id: uuid.UUID,
    role: Role,
    outcome: LotOutcome,
    reason: str,
    user_id: uuid.UUID | None = None,
    permissions: frozenset[Permission] = frozenset(),
) -> LotCard:
    """Закрывает лот без протокола: не участвуем, отменён, не тот код.

    Отдельно от `result`. Тот записывает протокол и потому требует поданной
    заявки: «выиграли за» у неподанного лота означало бы итоги закупки, в
    которой мы не участвовали. Здесь наоборот — заявки как раз и не было, и
    требовать её значило бы не дать закрыть лот, мимо которого прошли.

    Причина обязательна. Через месяц на вопрос «почему прошли мимо этой
    закупки» отвечать будет некому: тот, кто закрывал, помнит первые три, а
    закрывают их десятками.
    """
    if outcome not in BY_DECISION:
        raise SpokenError("Этот итог записывается вместе с протоколом подачи")
    if role not in _DECIDES and not _may(Permission.DECIDE, permissions):
        raise SpokenError("Закрывать лот вам нельзя")
    clean = reason.strip()
    if not clean and outcome in NEEDS_REASON:
        raise SpokenError(f"Напишите, почему «{OUTCOME_NAMES[outcome]}»")
    if not clean:
        # У «не успели подать» причина одна на все случаи, и спрашивать её у
        # человека нечего: срок истёк, заявки не было.
        clean = "Срок приёма заявок истёк, заявки не было"

    card = _required(db, organization_id, card_id)
    card.outcome = outcome
    card.status = LotStatus.DONE
    card.status_at = utcnow()
    card.finished_at = card.finished_at or utcnow()
    # Причина ложится туда же, где живёт причина отказа от участия: это один и
    # тот же ответ на один и тот же вопрос, и второе поле рядом означало бы
    # два места, где его ищут.
    card.skip_reason = clean[:2000]
    # Не участвуем — при любой из четырёх причин. «Тендер отменён» и «код не
    # подходит» — это тоже ответ «нет» на вопрос «участвуем ли»: пока отметку
    # ставил только «не участвуем», человек выбирал «код не подходит», лот
    # закрывался, а переключатель оставался на «Да» — и нажатие выглядело как
    # будто ничего не произошло.
    card.participation = Participation.NO
    trace(
        db,
        card_id=card.id,
        kind="result",
        title=f"Закрыл лот: {OUTCOME_NAMES[outcome]}",
        actor_id=user_id,
        role=role,
        detail=clean,
    )
    db.flush()
    return card


def result(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    card_id: uuid.UUID,
    role: Role,
    outcome: LotOutcome | None = None,
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

    if outcome is not None:
        # Итог и завершение — одно действие. Протокол пришёл, значит, закупка
        # для нас кончилась: держать её в «Ожидании протокола» после того, как
        # он прочитан, значит каждое утро открывать лот, чтобы убедиться, что
        # там ничего нового.
        card.outcome = outcome
        if outcome is not LotOutcome.NONE:
            card.status = LotStatus.DONE
            card.status_at = utcnow()
            card.finished_at = card.finished_at or utcnow()
    if won_amount is not None:
        card.won_amount = won_amount
    if winner.strip():
        card.winner = winner.strip()[:2000]
    trace(
        db,
        card_id=card.id,
        kind="result",
        title=(
            f"Записал итог: {OUTCOME_NAMES[outcome]}"
            if outcome is not None
            else "Записал итоги подачи"
        ),
        actor_id=user_id,
        role=role,
        detail=winner,
    )
    db.flush()
    return card


def claim(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    card_id: uuid.UUID,
    user_id: uuid.UUID,
    role: Role,
    desk: Department = LEAD,
) -> LotCard:
    """Садится на свободное место отдела.

    Отдельно от `seat`, и это не то же самое. `seat` — «посадить другого»,
    право руководящее: менеджер раздаёт работу. А взять свободную работу
    своего отдела должен любой, кто её делает: бежать за менеджером ради
    этого значит потерять день из двух, что даёт срок обсуждения.

    Занятое место не перехватывается. Двое, взявшие один лот, считают его
    дважды, а узнают об этом на согласовании — когда сходятся две разные
    себестоимости. Освободить место может тот, кто вправе назначать.
    """
    card = _required(db, organization_id, card_id)
    place = _seat(card, desk)
    if place.user_id is not None:
        if place.user_id == user_id:
            return card
        raise SpokenError(f"Место «{DESK_TITLES[desk]}» уже занято")

    place.user_id = user_id
    place.by_name = _name_of(db, user_id)
    place.taken_at = utcnow()
    trace(
        db,
        card_id=card.id,
        kind="claimed",
        title="Взял лот на себя",
        actor_id=user_id,
        role=role,
    )
    db.flush()
    db.refresh(card)
    return card


def seat(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    card_id: uuid.UUID,
    desk: Department,
    user_id: uuid.UUID | None = None,
    by: uuid.UUID | None = None,
    role: Role | None = None,
) -> LotCard:
    """Сажает человека в строку отдела или освобождает её.

    Пустой `user_id` освобождает место — отдельного признака «снять» больше не
    нужно: отдел задан явно, и «поставить никого» ни с чем не путается.

    Кого сажать, не проверяется по роли. Роль — подсказка для автоназначения и
    для рассылки, а не замок: уволившийся единственный юрист иначе запирает
    строку до тех пор, пока администратор не выдаст кому-то роль, — а лот к
    этому времени уже ушёл по сроку.
    """
    card = _required(db, organization_id, card_id)
    place = _seat(card, desk)
    place.user_id = user_id
    place.by_name = _name_of(db, user_id) if user_id else ""
    place.taken_at = utcnow() if user_id else None
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
    card_id: uuid.UUID | None,
    created_by: uuid.UUID,
    title: str,
    department: Department | None = None,
    body: str = "",
    assignee_id: uuid.UUID | None = None,
    due_at: datetime | None = None,
    settings: Settings | None = None,
) -> Task:
    """Заводит задачу — по лоту или саму по себе.

    Отдел не указан — берётся тот, у кого лот сейчас: чаще всего задачу заводят
    себе же, и переспрашивать об этом каждый раз значит добавить нажатие к
    самому частому действию.

    **Без лота задача адресуется человеку.** «Собрать доверенности», «оформить
    пропуск на склад» — это поручения, а не работа по закупке, и отдела у них
    нет: положить такую в общую очередь снабжения значит засорить очередь, ради
    которой её и заводили. Поэтому исполнитель обязателен: ничья задача вне
    лота не всплывёт нигде и не будет сделана никогда.
    """
    card = _required(db, organization_id, card_id) if card_id is not None else None
    clean = " ".join(title.split())
    if not clean:
        raise SpokenError("У задачи должно быть название")
    if card is None and assignee_id is None:
        raise SpokenError("Задаче вне лота нужен исполнитель: ничью её никто не возьмёт")

    # Задача с исполнителем считается взятой сразу: её завели конкретному
    # человеку, и подбирать её некому.
    #
    # Срок ставит автор. Не назвал — час: у задачи без срока нет и очереди, она
    # не горит и не всплывает никогда.
    taken = utcnow() if assignee_id else None
    when = due_at if due_at is not None else utcnow() + DEFAULT_WORK

    task = Task(
        organization_id=organization_id,
        card_id=card.id if card is not None else None,
        # Отдел — только у лотовой задачи: у поручения человеку его нет, и
        # придуманный отдел вывел бы такую задачу в чужую очередь.
        department=(department or DEPARTMENT_OF[card.status] if card is not None else department),
        title=clean[:2000],
        body=body.strip(),
        assignee_id=assignee_id,
        taken_at=taken,
        created_by_id=created_by,
        due_at=when,
    )
    db.add(task)
    if card is not None and task.department is not None:
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


def edit_task(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    task_id: uuid.UUID,
    user_id: uuid.UUID,
    role: Role,
    title: str | None = None,
    body: str | None = None,
    assignee_id: uuid.UUID | None = None,
    change_assignee: bool = False,
    due_at: datetime | None = None,
    change_due: bool = False,
    settings: Settings | None = None,
) -> Task:
    """Правит поручение: название, текст, исполнителя, срок.

    Правит только тот, кто задачу завёл, и администратор. Исполнитель здесь не
    вправе: поручение — это чужая просьба, и человек, переписавший себе срок,
    отвечает уже на другой вопрос.

    Смена исполнителя отдельным признаком, а не пустым значением: «не указан» и
    «указан пустым» приходят в JSON одинаково, и правка одного названия молча
    снимала бы исполнителя.

    Нового исполнителя зовём как при заведении: для него это задача, о которой
    он до сих пор не знал, и узнать о ней он должен так же.
    """
    task = db.get(Task, task_id)
    if task is None or task.organization_id != organization_id:
        raise SpokenError("Задача не найдена")
    if task.created_by_id != user_id and role is not Role.ADMIN:
        raise SpokenError("Править задачу может тот, кто её завёл")

    if title is not None:
        clean = " ".join(title.split())
        if not clean:
            raise SpokenError("У задачи должно быть название")
        task.title = clean[:2000]
    if body is not None:
        task.body = body.strip()
    if change_due:
        task.due_at = due_at

    was = task.assignee_id
    if change_assignee:
        if assignee_id is None and task.card_id is None:
            raise SpokenError("Задаче вне лота нужен исполнитель: ничью её никто не возьмёт")
        task.assignee_id = assignee_id
        # Взятой считается та, у которой есть исполнитель: поручение адресное,
        # и подбирать его некому.
        task.taken_at = utcnow() if assignee_id else None

    db.flush()
    if change_assignee and assignee_id is not None and assignee_id != was:
        _task_added(db, settings, task, db.get(LotCard, task.card_id) if task.card_id else None)
    return task


def take_task(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    task_id: uuid.UUID,
    user_id: uuid.UUID | None,
    settings: Settings | None = None,
) -> Task:
    """Берёт задачу себе. Пустой человек — вернуть в очередь отдела.

    Одно действие и без вопросов. Раньше берущий называл, за сколько сделает, и
    этим переписывал срок: задача, заведённая «к 16:00», после взятия в 15:50
    становилась задачей «до 18:50». К какому часу нужен ответ, знает тот, кто
    задачу завёл; берущий знает только, свободен ли он сейчас.

    Поэтому `due_at` здесь не трогается вовсе — ни при взятии, ни при возврате.
    Возврат снимает исполнителя, срок остаётся прежним: он был про работу, а не
    про то, кто её делает.

    Чужую взятую не перехватить. Двое, делающие одно и то же и не знающие об
    этом, — худший исход из возможных.
    """
    task = db.get(Task, task_id)
    if task is None or task.organization_id != organization_id:
        raise SpokenError("Задача не найдена")

    if user_id is None:
        task.assignee_id = None
        task.taken_at = None
        # Лента лота пишется только у лотовой задачи: у задачи вне лота ленты
        # нет вовсе, а о своей работе она рассказывает сама.
        if task.card_id is not None:
            trace(
                db,
                card_id=task.card_id,
                kind="task_taken",
                title=f"Вернул в очередь отдела задачу «{task.title}»",
                actor_id=None,
            )
        db.flush()
        return task

    if task.state is not TaskState.OPEN:
        raise SpokenError("Задача закрыта — брать нечего")
    if task.assignee_id is not None and task.assignee_id != user_id:
        raise SpokenError("Задачу уже взял другой сотрудник")

    task.assignee_id = user_id
    task.taken_at = utcnow()
    if task.card_id is not None:
        trace(
            db,
            card_id=task.card_id,
            kind="task_taken",
            title=f"Взял задачу «{task.title}»",
            actor_id=user_id,
        )
    db.flush()
    _task_taken(db, settings, task)
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
    # Кто закрыл, а не кто взял: задачу передают и доделывают за коллегу, а на
    # вопрос «кому платить премию» отвечает второе имя, не первое.
    task.done_by_id = user_id if state is not TaskState.OPEN else None
    if result.strip():
        task.result = result.strip()[:4000]
    if task.card_id is not None:
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
            # Имя сегодняшнее, нет человека — записанное тогда, нет и его —
            # честное «неизвестно кто». Копия нужна затем, что уволенного
            # удаляют, а лента отвечает на «кто это сделал» и через полгода.
            actor=name or item.actor_name or ("платформа" if item.by_machine else "неизвестно кто"),
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
    permissions: frozenset[Permission] = frozenset(),
    talks: frozenset[str] = frozenset(),
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
        # «Моё» — это любое место в лоте плюс тот, кто его завёл. Вопрос «что
        # на мне» не различает, в каком именно отделе я сижу.
        query = query.where(
            (LotCard.taken_by_id == user_id) | LotCard.seats.any(LotSeat.user_id == user_id)
        )
    if want.unowned:
        # «Можно взять»: есть хоть одно свободное место. Слово «ничьи» ушло —
        # лот целиком ничьим не бывает, свободной бывает строка отдела.
        query = query.where(LotCard.seats.any(LotSeat.user_id.is_(None)))

    rows = list(db.execute(query).scalars())
    if want.search:
        needle = want.search.strip().lower()
        rows = [
            row
            for row in rows
            if needle in f"{row.code} {row.title} {row.customer} {row.row_id}".lower()
        ]

    # Сортировка в памяти: строк здесь сотни, а «без времени в конец» на
    # стороне базы пишется по-разному в SQLite и PostgreSQL и однажды
    # разъезжается между проверочной средой и рабочей.
    #
    # Свежее сверху — по времени последней смены статуса. Раньше сортировали по
    # сроку приёма, и на вопрос «что нового» список отвечал «что горит»: лот,
    # который вчера перевели на согласование, лежал в середине между теми, к
    # которым никто не прикасался. Срок при этом никуда не делся — он в строке
    # и красным, когда горит.
    #
    # Сошедшие с дистанции по-прежнему внизу: у завершённого статус менялся
    # только что, и без этого он занимал бы весь верх списка.
    rows.sort(
        key=lambda row: (
            row.status in _FINAL,
            -(row.status_at or row.created_at).timestamp(),
        )
    )
    known = people(db, rows)
    # Обсуждения — одним запросом на весь список. Их читают ради точки хода в
    # строке: без них «Обсуждение» у всех выглядело бы незакрытым. По одному на
    # карточку было бы сто запросов на сто строк — это и есть та секунда, из-за
    # которой список «подтормаживает».
    discussions = _talks_for(db, rows, organization_id=organization_id)
    # Кому заведена таблица снабжения — одним запросом на весь список. По
    # запросу на карточку сотня лотов стоила бы сотни обращений к базе.
    from platform_api.modules import sheets

    to_supply = sheets.handed_many(db, rows, organization_id=organization_id)
    found = [
        _shown(
            row,
            known,
            role=role,
            user_id=user_id,
            now=moment,
            talk=discussions.get((row.module, row.row_id)),
            brief=True,
            permissions=permissions,
            to_supply=(row.module, row.row_id) in to_supply,
            talks=row.module in talks,
        )
        for row in rows
    ]
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
    permissions: frozenset[Permission] = frozenset(),
    talks: frozenset[str] = frozenset(),
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
        permissions=permissions,
        to_supply=bool(sheets_handed(db, card)),
        talks=card.module in talks,
    )


def sheets_handed(db: DbSession, card: LotCard) -> bool:
    """Заведена ли лоту таблица снабжения. Через ленивый импорт: таблицы знают
    о карточке, карточка о них — только здесь, и общий импорт свёл бы их в
    кольцо."""
    from platform_api.modules import sheets

    return sheets.handed(db, card)


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
    author_id: uuid.UUID | None = None,
    involving: uuid.UUID | None = None,
    standalone: bool | None = None,
    state: TaskState | None = TaskState.OPEN,
    now: datetime | None = None,
) -> list[Job]:
    """Задачи под отбором.

    По умолчанию только открытые: очередь работы — это то, что не сделано, а
    закрытые смотрят отдельной вкладкой и редко.

    `involving` — «что на мне и что я поручил». Это раздел задач: поручение
    касается двоих, и человек ходит туда за обеими половинами.

    `standalone` делит два разных списка. Стол отдела — про работу по лотам, и
    поручение «оформить пропуск» там лишнее: очередь, в которой половина
    записей ни к чему не привязана, перестаёт быть очередью работы. Раздел
    задач — наоборот, про поручения людям. Поэтому признак трёхзначный: `True`
    — только вне лота, `False` — только лотовые, `None` — всё подряд (так
    смотрят «что вообще на человеке»).
    """
    moment = now or utcnow()
    query = select(Task).where(Task.organization_id == organization_id)
    if department is not None:
        query = query.where(Task.department == department)
    if author_id is not None:
        query = query.where(Task.created_by_id == author_id)
    if involving is not None:
        # «Что на мне и что я поручил» одним списком. Двумя запросами это
        # значило бы склеивать их в питоне и вычищать задачи, где человек и
        # автор, и исполнитель, — а такие как раз самые частые.
        query = query.where(or_(Task.assignee_id == involving, Task.created_by_id == involving))
    if standalone is True:
        query = query.where(Task.card_id.is_(None))
    elif standalone is False:
        query = query.where(Task.card_id.is_not(None))
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
    talk = _talk_of(db, organization_id, rows)
    return [_job(row, known, cards, moment, talk) for row in rows]


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
    # Карточки может не быть вовсе — у поручения вне лота её нет; `db.get` с
    # пустым ключом ругается на состав первичного ключа, а не возвращает None.
    card = db.get(LotCard, row.card_id) if row.card_id is not None else None
    return _job(
        row,
        people(db, [row]),
        {card.id: card} if card is not None else {},
        moment,
        _talk_of(db, organization_id, [row]),
    )


def _cards_of(db: DbSession, rows: Sequence[Task]) -> dict[uuid.UUID, LotCard]:
    """Карточки задач одним запросом — задача без лота не читается."""
    wanted = {row.card_id for row in rows if row.card_id is not None}
    if not wanted:
        return {}
    found = db.execute(select(LotCard).where(LotCard.id.in_(wanted))).scalars()
    return {card.id: card for card in found}


def _talk_of(
    db: DbSession, organization_id: uuid.UUID, rows: Sequence[Task]
) -> dict[uuid.UUID, int]:
    """Сколько реплик у каждой задачи. Лениво: обсуждение знает о задачах,
    задачи об обсуждении — только здесь, и общий импорт свёл бы их в кольцо."""
    from platform_api.modules import discussion

    return discussion.counts_for_tasks(db, organization_id, [row.id for row in rows])


def _job(
    row: Task,
    known: dict[uuid.UUID, str],
    cards: dict[uuid.UUID, LotCard],
    now: datetime,
    talk: dict[uuid.UUID, int] | None = None,
) -> Job:
    card = cards.get(row.card_id) if row.card_id else None
    left, burning, overdue = time_left(row.due_at, now)
    return Job(
        id=str(row.id),
        card_id=str(row.card_id) if row.card_id else "",
        card_code=card.code if card else "",
        card_title=card.title if card else "",
        card_amount=card.amount if card else None,
        card_customer=card.customer if card else "",
        department=row.department.value if row.department else "",
        department_name=DEPARTMENT_NAMES[row.department] if row.department else "",
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
        taken_at=row.taken_at.isoformat() if row.taken_at else "",
        done_at=row.done_at.isoformat() if row.done_at else "",
        done_by=known.get(row.done_by_id, "") if row.done_by_id else "",
        author=known.get(row.created_by_id, "") if row.created_by_id else "",
        author_id=str(row.created_by_id) if row.created_by_id else "",
        talk=(talk or {}).get(row.id, 0),
    )


_TALK_DONE = frozenset(
    {
        DiscussionStage.WITH_LAWYERS,
        DiscussionStage.SENT,
        DiscussionStage.NOT_NEEDED,
    }
)
"""Этапы, на которых обсуждение своё отработало."""

DESK_MARKS: tuple[tuple[Department, str], ...] = (
    (Department.DISCUSSION, "Обсуждение"),
    (Department.ANALYSIS, "Разбор"),
    (Department.SUPPLY, "Снабжение"),
    (Department.TECHNOLOGIST, "Технолог"),
)
"""Четыре отдела, по которым видно ход лота одним взглядом.

Именно эти четыре, а не все восемь. В списке лотов у строки есть место на
четыре точки, и выбраны те, через которые проходит каждая закупка по порядку:
замечание заказчику, разбор спецификации, поиск товара, подтверждение
технологом. Юрист подключается не всегда, сборщик и подача идут после решения
об участии, а согласование видно подписями.
"""


@dataclass(frozen=True, slots=True)
class DeskMark:
    """Отработал ли отдел по лоту.

    Ответ на вопрос планёрки «что сейчас с этой закупкой» одним взглядом на
    строку: четыре точки вместо открывания четырёх карточек подряд.
    """

    desk: str
    title: str
    done: bool
    """Отдел закончил. Правило у каждого своё и объяснено в `desk_marks`."""

    open_tasks: int
    """Сколько задач отдела ещё висит. Ноль при `done=False` означает, что до
    отдела просто не дошли, — и это другое состояние, чем «работает»."""


def desk_marks(card: LotCard, *, talk: Discussion | None = None) -> tuple[DeskMark, ...]:
    """Отметки отделов — те же, что рисует правый столбец карточки.

    Считаются здесь, а не в браузере, потому что нужны в двух местах: в списке
    лотов точками и в карточке галочками. Два расчёта разошлись бы на первом же
    правиле — а правила у отделов разные и не выводятся одно из другого:

    * **Обсуждение** закончено, когда своё оно отработало: замечание передано
      юристам, отправлено заказчику или признано ненужным. Именно передано, а
      не отправлено: дальше работа не у нас — у юристов на неё стоит своя
      задача и свой кружок, и держать оба незакрытыми значит показывать одну
      работу дважды. Написанный и не отправленный текст закрытым не считается:
      это работа, которую ещё делают.
    * **Разбор** закончен, когда лот прошёл этот этап пути. Таблица к этому
      моменту собрана, но собранная таблица сама по себе не значит, что решение
      принято, — а точка отвечает именно за «отдел отпустил лот дальше».
    * **Снабжение и технолог** — когда у отдела не осталось открытых задач, и
      хотя бы одна была. Работа этих отделов и есть задачи: «найти товар»,
      «подтвердить, что подходит». Отсутствие задач вовсе — не готовность, а
      «руки не дошли», и точка остаётся пустой.
    """
    order = {status: place for place, status in enumerate(FLOW)}
    here = order.get(card.status, -1)
    # Разбор закончен, когда лот вышел из «В работе»: отделы работают внутри
    # этого статуса, и уход дальше означает, что разбор отпустил лот. Раньше
    # проверялся собственный статус «На разборе» — его больше нет.
    analysis_done = here > order[LotStatus.WORK]

    marks: list[DeskMark] = []
    for desk, title in DESK_MARKS:
        mine = [task for task in card.tasks if task.department is desk]
        live = sum(1 for task in mine if task.state is TaskState.OPEN)
        if desk is Department.DISCUSSION:
            done = talk is not None and talk.stage in _TALK_DONE
        elif desk is Department.ANALYSIS:
            done = analysis_done
        else:
            done = bool(mine) and live == 0
        marks.append(DeskMark(desk=desk.value, title=title, done=done, open_tasks=live))
    return tuple(marks)


def _talks_for(
    db: DbSession, rows: Sequence[LotCard], *, organization_id: uuid.UUID
) -> dict[tuple[str, str], Discussion]:
    """Обсуждения списка лотов — одним запросом.

    Ключ тот же, что у карточки: площадка плюс строка. Берётся последнее по
    времени: обсуждение на лоте одно, но история переписывалась, и запись с
    тем же ключом теоретически бывает не одна.
    """
    if not rows:
        return {}
    keys = {(row.module, row.row_id) for row in rows}
    found = db.execute(
        select(Discussion)
        .where(
            # Организация обязательна: ключ «площадка плюс строка» между
            # организациями не уникален, и без неё в список одной компании
            # приехало бы обсуждение другой.
            Discussion.organization_id == organization_id,
            Discussion.module.in_({module for module, _ in keys}),
            Discussion.row_id.in_({row_id for _, row_id in keys}),
        )
        .order_by(Discussion.created_at)
    ).scalars()
    return {(one.module, one.row_id): one for one in found if (one.module, one.row_id) in keys}


def _shown(
    card: LotCard,
    known: dict[uuid.UUID, str],
    *,
    role: Role,
    user_id: uuid.UUID,
    now: datetime,
    talk: Discussion | None = None,
    brief: bool = False,
    permissions: frozenset[Permission] = frozenset(),
    to_supply: bool = False,
    talks: bool = True,
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
    signs = tuple(
        _sign(item, known, role=role, permissions=permissions) for item in _ordered(card.approvals)
    )
    open_tasks = sum(1 for task in card.tasks if task.state is TaskState.OPEN)
    # Считаем по разу: подстатус нужен и ключом для отбора, и словом для
    # показа, а правило в нём лестничное и не бесплатное.
    talk_key = talk_stage(talk, talking=talks)
    desk_key = desk_stage(card, talk=talk, to_supply=to_supply)
    here = work_stage(card, talk=talk, talking=talks, to_supply=to_supply, now=now)

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
        outcome=card.outcome.value,
        outcome_name=OUTCOME_NAMES[card.outcome],
        taken_by=(known.get(card.taken_by_id) if card.taken_by_id else "") or card.taken_by_name,
        taken_by_id=str(card.taken_by_id) if card.taken_by_id else "",
        seats=_seats_out(card, known, role=role, user_id=user_id, permissions=permissions),
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
        status_at=card.status_at.isoformat() if card.status_at else "",
        bid_amount=card.bid_amount,
        submitted_at=card.submitted_at.isoformat() if card.submitted_at else "",
        submitted=submitted(card),
        finished_at=card.finished_at.isoformat() if card.finished_at else "",
        approvals=signs,
        approved=_all_signed(card),
        open_tasks=open_tasks,
        done_tasks=len(card.tasks) - open_tasks,
        can=_can(card, role=role, user_id=user_id, permissions=permissions),
        # В списке обсуждение целиком не отдаётся: там оно не показывается, а
        # сотня вложенных объектов — это лишний вес ответа. Отметка отдела при
        # этом считается по нему же, и для неё оно и читалось.
        discussion=None if brief else _talk(talk, now),
        desks=desk_marks(card, talk=talk),
        stage=here,
        stage_name=WORK_STAGE_NAMES.get(here, ""),
        talk_stage=talk_key,
        talk_stage_name=TALK_STAGE_NAMES.get(talk_key, ""),
        desk_stage=desk_key,
        desk_stage_name=DESK_STAGE_NAMES.get(desk_key, ""),
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
        writing=row.writing.value if row.writing else "",
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


def _task_added(db: DbSession, settings: Settings | None, task: Task, card: LotCard | None) -> None:
    """Зовёт исполнителя или отдел. Отказ рассылки не роняет заведение задачи."""
    if settings is None:
        return
    from platform_api.modules import alerts

    try:
        alerts.task_added(db, settings, task, card)
    # Ловим всё: рассылка не должна ронять работу.
    except Exception as exc:
        logger.warning("Не позвали на задачу", task=str(task.id), error=str(exc))


def _task_taken(db: DbSession, settings: Settings | None, task: Task) -> None:
    """Сообщает отделу, что задачу взяли и к какому сроку.

    Отделу, а не только взявшему: остальные перестают на неё смотреть, и это
    ровно то, ради чего очередь и заводили.
    """
    if settings is None:
        return
    from platform_api.modules import alerts

    try:
        alerts.task_taken(db, settings, task)
    # Ловим всё: рассылка не должна ронять работу.
    except Exception as exc:
        logger.warning("Не сообщили о взятии задачи", task=str(task.id), error=str(exc))


def _ordered(approvals: Sequence[Approval]) -> list[Approval]:
    """Подписи всегда в одном порядке.

    Порядок объявления, а не тот, в каком их вернула база: строка согласования
    читается взглядом слева направо, и перестановка подписей между открытиями
    заставляет читать её заново каждый раз.
    """
    order = list(ApprovalKind)
    return sorted(approvals, key=lambda item: order.index(item.kind))


def _sign(
    item: Approval,
    known: dict[uuid.UUID, str],
    *,
    role: Role,
    permissions: frozenset[Permission] = frozenset(),
) -> Sign:
    return Sign(
        kind=item.kind.value,
        name=APPROVAL_NAMES[item.kind],
        state=item.state.value,
        # Имя из ссылки, а нет её — из копии рядом. Копия остаётся, когда
        # человека удалили: подпись должна остаться подписью.
        by=(known.get(item.by_id) if item.by_id else None) or item.by_name,
        at=item.decided_at.isoformat() if item.decided_at else "",
        note=item.note,
        can_sign=role in SIGNS[item.kind] or _may(SIGN_RIGHTS[item.kind], permissions),
    )


def _can(
    card: LotCard,
    *,
    role: Role,
    user_id: uuid.UUID,
    permissions: frozenset[Permission] = frozenset(),
) -> tuple[str, ...]:
    """Что этому человеку доступно на этом шаге.

    Считается по праву или по встроенной роли — по любому из двух. Список
    собирается ровно теми же условиями, что стоят в службах: кнопка, которую
    показали, а служба отвергла, — это человек, уверенный, что дело сделано.
    """
    allowed = [
        status.value
        for status in TRANSITIONS[card.status]
        if (role in ALLOWED[status] or _may_move(status, permissions))
        # «Подачу» без всех подписей не предлагаем: кнопка, которая всегда
        # отвечает отказом, читается как поломка, а не как правило.
        and (status is not LotStatus.SUBMISSION or _all_signed(card))
    ]
    # «Беру на себя» переехало на строки отделов: лот целиком ничьим не
    # бывает, свободной бывает строка. Что можно нажать на каждой — в `Seat.can`.
    if role in _DECIDES or _may(Permission.DECIDE, permissions):
        allowed.append("decide")
    # Назначение — только по праву, без оглядки на имя роли. Набор прав у
    # встроенных ролей собран из того же списка `{админ, менеджер}`, поэтому им
    # не меняется ничего, а своя роль получает ровно то, что ей выдали.
    if _may(Permission.LOT_ASSIGN, permissions):
        allowed.append("assign")
    if any(role in SIGNS[kind] or _may(SIGN_RIGHTS[kind], permissions) for kind in ApprovalKind):
        allowed.append("sign")
    allowed.append("task")
    return tuple(allowed)


@dataclass(frozen=True, slots=True)
class Folder:
    """Папка лота в том виде, в каком её показывают."""

    id: str
    name: str
    files: int
    """Сколько файлов внутри. Пустая папка — это не ошибка: её завели заранее."""


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
    folder_id: str = ""
    """В какой папке лежит. Пусто — в корне."""


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
            folder_id=str(link.folder_id) if link.folder_id else "",
        )
        for link, stored in rows
    ]


def folders(db: DbSession, *, organization_id: uuid.UUID, card_id: uuid.UUID) -> list[Folder]:
    """Папки лота с числом файлов в каждой.

    Число считается запросом, а не перебором связей: у лота с перепиской по
    трём поставщикам файлов набирается под сотню, и складывать их в питоне
    ради трёх чисел — это сотня строк, поднятых объектами.
    """
    card = _required(db, organization_id, card_id)
    counted: dict[uuid.UUID, int] = {
        folder: int(count)
        for folder, count in db.execute(
            select(LotFile.folder_id, func.count())
            .where(LotFile.card_id == card.id, LotFile.folder_id.is_not(None))
            .group_by(LotFile.folder_id)
        ).all()
        if folder is not None
    }
    rows = db.execute(
        select(LotFolder).where(LotFolder.card_id == card.id).order_by(LotFolder.name)
    ).scalars()
    return [Folder(id=str(row.id), name=row.name, files=counted.get(row.id, 0)) for row in rows]


def make_folder(
    db: DbSession, *, organization_id: uuid.UUID, card_id: uuid.UUID, name: str, by: uuid.UUID
) -> LotFolder:
    """Заводит папку. Повтор по имени отклоняет словами.

    Проверка здесь, а не только ограничением базы: `IntegrityError` доходит до
    человека пятисотой, и «Такая папка уже есть» он узнаёт из журнала
    администратора, а не с экрана.
    """
    card = _required(db, organization_id, card_id)
    clean = " ".join(name.split())[:120]
    if not clean:
        raise SpokenError("У папки должно быть название")

    taken = db.execute(
        select(LotFolder).where(
            LotFolder.card_id == card.id, func.lower(LotFolder.name) == clean.lower()
        )
    ).scalar_one_or_none()
    if taken is not None:
        raise SpokenError(f"Папка «{taken.name}» уже есть")

    made = LotFolder(card_id=card.id, name=clean, created_by_id=by)
    db.add(made)
    db.flush()
    return made


def drop_folder(db: DbSession, *, organization_id: uuid.UUID, folder_id: uuid.UUID) -> int:
    """Убирает папку. Файлы из неё возвращаются в корень.

    Возвращает, сколько файлов вернулось: человеку это надо сказать до
    нажатия, а после — подтвердить, что они не пропали.

    Связь снимается здесь же, хотя в базе стоит `SET NULL`: сессия держит
    объекты в памяти, и без явного снятия открытая страница показывала бы
    файлы в папке, которой уже нет.
    """
    folder = db.get(LotFolder, folder_id)
    if folder is None:
        raise SpokenError("Папка не найдена")
    card = db.get(LotCard, folder.card_id)
    if card is None or card.organization_id != organization_id:
        raise SpokenError("Папка не найдена")

    inside = list(db.execute(select(LotFile).where(LotFile.folder_id == folder.id)).scalars())
    for link in inside:
        link.folder_id = None
    db.delete(folder)
    db.flush()
    return len(inside)


def move_file(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    link_id: uuid.UUID,
    folder_id: uuid.UUID | None,
) -> LotFile:
    """Перекладывает файл в папку. Пустая папка — в корень."""
    link = db.get(LotFile, link_id)
    if link is None:
        raise SpokenError("Файл не найден")
    card = db.get(LotCard, link.card_id)
    if card is None or card.organization_id != organization_id:
        raise SpokenError("Файл не найден")
    link.folder_id = _folder_of(db, card, folder_id)
    db.flush()
    return link


def _folder_of(db: DbSession, card: LotCard, folder_id: uuid.UUID | None) -> uuid.UUID | None:
    """Папка этого лота — или отказ.

    Чужая папка увела бы файл в соседнюю карточку: в своей он при этом просто
    перестаёт быть виден, и выглядит это как пропажа.
    """
    if folder_id is None:
        return None
    folder = db.get(LotFolder, folder_id)
    if folder is None or folder.card_id != card.id:
        raise SpokenError("Такой папки у этого лота нет")
    return folder.id


@dataclass(frozen=True, slots=True)
class Attached:
    """Чем кончилась попытка приложить файл.

    Нужно не для отчётности, а чтобы было что сказать человеку. Повторная
    загрузка того же содержимого выглядит на экране как пропажа: файл не
    появился там, куда его клали, а тихо переехал из соседней папки. Из этих
    полей собирается фраза, которая объясняет, что произошло.
    """

    link: LotFile
    known: bool
    """Файл уже был приложен к этому лоту — то же содержимое, а не то же имя."""

    stored_name: str
    """Под каким именем он лежит у нас. У повторной загрузки имя берётся от
    первой: хранилище складывает по содержимому, а имя у содержимого одно."""

    moved: bool
    """Пришлось ли его перенести в новую папку."""

    moved_from: str
    """Откуда перенесли. Пусто — из общего списка, вне папок."""

    folder: str
    """Где он лежит теперь. Пусто — в общем списке.

    Нужно для случая, когда переносить некуда: файл прикладывают кнопкой из
    шапки, папка не выбрана, а он уже лежит в одной из них. Тогда он остаётся
    на месте — иначе кнопка «Приложить» молча вынимала бы файлы из папок, —
    и человеку надо сказать, где его искать: в общем списке он не появится."""


def attach(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    card_id: uuid.UUID,
    file_id: uuid.UUID,
    added_by: uuid.UUID,
    note: str = "",
    folder_id: uuid.UUID | None = None,
) -> Attached:
    """Привязывает уже загруженный файл к лоту.

    Один и тот же файл к одному лоту дважды не привязывается — и «тот же»
    здесь про содержимое, а не про имя. Хранилище складывает по хэшу байтов:
    `Resume.pdf` и `Резюме.pdf` с одинаковой начинкой — одна запись, а два
    разных документа, названных одинаково, остаются двумя. Иначе рядом со
    счётом лежала бы его же копия, а «какой из двух свежий» выяснялось бы
    открыванием обоих.

    Тот же файл, положенный в другую папку, переезжает туда. Это то, ради чего
    его и грузят второй раз: снимок переписки, лежавший в общем списке,
    человек прикладывает в папку поставщика именно затем, чтобы он оказался
    там. Две записи на одно содержимое дали бы папку, где файл есть, и папку,
    где он тоже есть, — а удалив один, человек считал бы удалённым оба.

    Папка не выбрана — файл остаётся, где лежал. Кнопка «Приложить» в шапке
    вкладки не говорит «в общий список», она говорит «к лоту», и вынимать ею
    файлы из папок значило бы разбирать чужую раскладку случайным нажатием.

    Молчать об этом переезде нельзя: файл исчезает оттуда, где лежал, и
    сказать об этом должен тот, кто переносит. Отсюда `Attached`.
    """
    card = _required(db, organization_id, card_id)
    where = _folder_of(db, card, folder_id)
    stored_name = _stored_name(db, file_id)
    found = db.execute(
        select(LotFile).where(LotFile.card_id == card.id, LotFile.file_id == file_id)
    ).scalar_one_or_none()
    if found is not None:
        moved = where is not None and found.folder_id != where
        came_from = _folder_name(db, found.folder_id) if moved else ""
        if moved:
            found.folder_id = where
            db.flush()
        return Attached(
            link=found,
            known=True,
            stored_name=stored_name,
            moved=moved,
            moved_from=came_from,
            folder=_folder_name(db, found.folder_id),
        )

    found = LotFile(
        card_id=card.id,
        file_id=file_id,
        added_by_id=added_by,
        note=note.strip(),
        folder_id=where,
    )
    db.add(found)
    db.flush()
    return Attached(
        link=found,
        known=False,
        stored_name=stored_name,
        moved=False,
        moved_from="",
        folder=_folder_name(db, where),
    )


def _stored_name(db: DbSession, file_id: uuid.UUID) -> str:
    stored = db.get(StoredFile, file_id)
    return stored.original_name if stored is not None else ""


def _folder_name(db: DbSession, folder_id: uuid.UUID | None) -> str:
    if folder_id is None:
        return ""
    folder = db.get(LotFolder, folder_id)
    return folder.name if folder is not None else ""


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
        for field in ("manager_id", "owner_id", "assignee_id", "done_by_id", "created_by_id"):
            value = getattr(row, field, None)
            if value:
                wanted.add(value)
    if not wanted:
        return {}
    found = db.execute(select(User).where(User.id.in_(wanted))).scalars()
    return {user.id: (user.full_name or user.email) for user in found}


def time_left(when: datetime | None, now: datetime) -> tuple[str, bool, bool]:
    """Сколько осталось, словами. Возвращает ещё «горит» и «просрочено».

    У прошедшего срока — насколько опоздали, а не «срок прошёл». Разница в
    работе большая: задача, просроченная на двадцать минут, догоняется сегодня,
    а просроченная на три дня означает, что её вообще никто не видел. Пока обе
    выглядели одинаково, очередь отдела сортировали на глаз по дате заведения.
    """
    if when is None:
        return "", False, False
    left = when - now
    seconds = int(left.total_seconds())
    if seconds <= 0:
        return f"просрочено на {_words(-seconds)}", False, True
    return _words(seconds), left <= BURNING, False


def _words(seconds: int) -> str:
    """Промежуток словами: «2 дн. 4 ч.», «3 ч. 20 мин.», «15 мин.»."""
    hours, rest = divmod(max(seconds, 0), 3600)
    minutes = rest // 60
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"{days} дн. {hours} ч."
    if hours:
        return f"{hours} ч. {minutes} мин."
    return f"{minutes} мин."


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
    "Folder",
    "Job",
    "Person",
    "Sign",
    "Snapshot",
    "add_task",
    "advance",
    "attach",
    "by_row",
    "close_task",
    "decide",
    "detach",
    "drop_folder",
    "edit_task",
    "files",
    "folders",
    "listing",
    "move",
    "one",
    "open_card",
    "people",
    "result",
    "seat",
    "sign",
    "take_task",
    "task",
    "tasks",
    "time_left",
]
