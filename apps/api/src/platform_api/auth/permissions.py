"""Права: что человек может, а не кто он.

Раньше каждая проверка перечисляла роли: «сюда пускаем тендерщика, менеджера,
руководителя и коммерческого». Работало, пока роли были прибиты в коде. Стоит
дать администратору заводить свои — «снабженец без цен», «стажёр тендерного
отдела», — и такая проверка их не знает: новая роль не перечислена нигде и
получает отказ везде.

Отсюда слой между ними. Роль — это набор прав; проверка спрашивает право, а не
имя роли. Список прав определён кодом и закрыт: право появляется вместе с
местом, которое его проверяет, и «выдать право, которого никто не спрашивает»
невозможно по построению. Роли же заводятся и правятся в платформе.

Названы права по делу, а не по отделу. `MONEY` — это «видеть себестоимость и
маржу», и его одинаково осмысленно дать тендерщику и не дать закупщику;
`SIGN_SUPPLY` — «подписывать за снабжение», и подпись остаётся одна на роль,
даже если роль назвали иначе.
"""

from __future__ import annotations

from enum import StrEnum

from platform_api.db.models import Role


class Permission(StrEnum):
    """Что человеку можно. Список закрыт: каждое право кем-то проверяется.

    Два вида прав, и различать их важно.

    **Страницы** (`page.*`) — куда человек может зайти. Ими управляется меню:
    пункт без права не показывается, а его адрес отвечает отказом. Одно право
    на страницу, а не одно на модуль: «Лоты портала» и «Обход портала» лежат в
    одном модуле, но первое — ежедневная работа, второе — настройка, которую
    правит один человек.

    **Действия** (всё остальное) — что он может сделать и что увидеть внутри
    страницы. Ими скрываются кнопки и столбцы: «видеть себестоимость» и
    «двигать лот» — это не про доступ к экрану, а про то, что на нём можно.

    Список закрыт кодом. Право появляется вместе с местом, которое его
    проверяет, и выдать несуществующее нельзя по построению — а значит, на
    экране роли не бывает галочки, которая ничего не делает.
    """

    # --- Страницы -----------------------------------------------------------

    PAGE_LOTS = "page.lots"
    """«Лоты в работе» — сквозной список закупок."""

    PAGE_DESK_DISCUSSION = "page.desk_discussion"
    PAGE_DESK_ANALYSIS = "page.desk_analysis"
    PAGE_DESK_SUPPLY = "page.desk_supply"
    PAGE_DESK_LEGAL = "page.desk_legal"
    """Столы отделов. По праву на каждый, а не одно на все: очередь чужого
    отдела — это чужая работа, и смотреть в неё незачем."""

    PAGE_TASKS = "page.tasks"
    """«Задачи» — поручения людям, вне лота.

    Отдельно от столов отделов: те про очередь работы по закупкам, а этот
    раздел личный — что поручили тебе и что поручил ты."""

    PAGE_SUBMIT = "page.submit"
    """«Подача» — календарь подач и итоги."""

    PAGE_APPROVAL = "page.approval"
    """«Согласование» — где чьи подписи."""

    PAGE_REMARKS = "page.remarks"
    """«Замечания заказчику» — переписка до подачи."""

    PAGE_PORTAL = "page.portal"
    """«Лоты портала» — что выгрузилось с госзакупок."""

    PAGE_PORTAL_CODES = "page.portal_codes"
    """«Обход портала» — список кодов ЕНС ТРУ. Настройка, не работа."""

    PAGE_SKSTORE = "page.skstore"
    PAGE_SKSTORE_ANALYTICS = "page.skstore_analytics"
    PAGE_OMARKET = "page.omarket"
    PAGE_OMARKET_ANALYTICS = "page.omarket_analytics"
    """Площадки и их аналитика. Раздельно: список нужен закупщику, аналитика —
    тем, кто смотрит объёмы и маржу."""

    PAGE_TENDER_PICK = "page.tender_pick"
    """«Отбор тендеров» — за ним суммы и маржа: без них он пуст."""

    PAGE_TENDER_WORKS = "page.tender_works"
    """«Тендеры в работе» — общий стол разбора и снабжения."""

    PAGE_TENDER_ANALYTICS = "page.tender_analytics"

    PAGE_AUDIT = "page.audit"
    """«Журнал действий» — кто что сделал."""

    PAGE_PEOPLE = "page.people"
    """«Сотрудники» и роли."""

    PAGE_NOTIFY = "page.notify"
    """«Уведомления» — работает ли рассылка."""

    # --- Действия -----------------------------------------------------------

    READ = "read"
    """Рабочие списки, очередь задач, справочники.

    За списками цены, поэтому это не «вход в платформу», а отдельное право:
    юристу, технологу и сборщику списки не нужны — их работа идёт от карточки
    лота."""

    MONEY = "money"
    """Себестоимость, маржа, наша отпускная цена.

    Самое дорогое право в платформе. Уходит вместе с человеком, и давать его
    «на всякий случай» нельзя."""

    SOURCING = "sourcing"
    """Задание закупщику: поставщики, целевая цена закупа, статусы."""

    REMARKS = "remarks"
    """Замечания к спецификациям и жалобы — переписка с заказчиком."""

    CRM = "crm"
    """Карточка лота: задачи, файлы, переписка коллег, ход по отделам."""

    DECIDE = "decide"
    """Решение об участии. Решать «берёмся или нет», не видя маржи, нельзя —
    поэтому это право идёт в паре с `MONEY`."""

    MOVE = "move"
    """Переводить лот по состояниям."""

    SIGN_MANAGER = "sign.manager"
    SIGN_SUPPLY = "sign.supply"
    SIGN_LEGAL = "sign.legal"
    SIGN_TECHNOLOGIST = "sign.technologist"
    SIGN_ASSEMBLER = "sign.assembler"
    """Подписи под участием. Одна роль — одна подпись: если один человек может
    подписать за двоих, согласование перестаёт быть согласованием."""

    LOT_TAKE = "lot.take"
    """Брать закупку в работу — заводить карточку из списка портала."""

    LOT_CLAIM = "lot.claim"
    """Брать ничей лот на себя."""

    LOT_ASSIGN = "lot.assign"
    """Поручать лот другому: менять ведущего и менеджера."""

    LOT_SUBMIT = "lot.submit"
    """Отмечать подачу заявки и сумму участия."""

    LOT_RESULT = "lot.result"
    """Записывать итоги протокола: выиграли, проиграли, за сколько."""

    TASKS = "tasks"
    """Заводить и закрывать задачи по лоту."""

    FILES = "files"
    """Прикладывать и убирать файлы лота."""

    SHEET_EDIT = "sheet.edit"
    """Править таблицу разбора: столбцы, строки, значения."""

    SHEET_BUILD = "sheet.build"
    """Звать модель разобрать спецификацию. Стоит денег."""

    REMARK_WRITE = "remark.write"
    """Править текст замечания и звать модель его написать."""

    REMARK_SEND = "remark.send"
    """Отправлять замечание заказчику. Необратимо и от имени компании."""

    ADMIN = "admin"
    """Управление платформой: люди, роли, журнал действий, обход портала.

    Даёт и всё остальное: администратор и так распоряжается доступами, и
    запирать его от раздела значит заставить выдать себе роль, чтобы
    посмотреть."""


PERMISSION_NAMES: dict[Permission, str] = {
    Permission.PAGE_LOTS: "Лоты в работе",
    Permission.PAGE_DESK_DISCUSSION: "Стол: Обсуждение",
    Permission.PAGE_DESK_ANALYSIS: "Стол: Разбор",
    Permission.PAGE_DESK_SUPPLY: "Стол: Снабжение",
    Permission.PAGE_DESK_LEGAL: "Стол: Юристы",
    Permission.PAGE_TASKS: "Задачи",
    Permission.PAGE_SUBMIT: "Подача",
    Permission.PAGE_APPROVAL: "Согласование",
    Permission.PAGE_REMARKS: "Замечания заказчику",
    Permission.PAGE_PORTAL: "Лоты портала",
    Permission.PAGE_PORTAL_CODES: "Обход портала",
    Permission.PAGE_SKSTORE: "Закупы SKStore",
    Permission.PAGE_SKSTORE_ANALYTICS: "Аналитика закупов",
    Permission.PAGE_OMARKET: "Предзаказы OMarket",
    Permission.PAGE_OMARKET_ANALYTICS: "Аналитика предзаказов",
    Permission.PAGE_TENDER_PICK: "Отбор тендеров",
    Permission.PAGE_TENDER_WORKS: "Тендеры в работе",
    Permission.PAGE_TENDER_ANALYTICS: "Аналитика тендеров",
    Permission.PAGE_AUDIT: "Журнал действий",
    Permission.PAGE_PEOPLE: "Сотрудники и роли",
    Permission.PAGE_NOTIFY: "Уведомления",
    Permission.LOT_TAKE: "Брать закупку в работу",
    Permission.LOT_CLAIM: "Брать лот на себя",
    Permission.LOT_ASSIGN: "Поручать лот другому",
    Permission.LOT_SUBMIT: "Отмечать подачу",
    Permission.LOT_RESULT: "Записывать итоги протокола",
    Permission.TASKS: "Задачи по лоту",
    Permission.FILES: "Файлы лота",
    Permission.SHEET_EDIT: "Править таблицу разбора",
    Permission.SHEET_BUILD: "Звать модель на разбор",
    Permission.REMARK_WRITE: "Писать замечание",
    Permission.REMARK_SEND: "Отправлять замечание",
    Permission.READ: "Рабочие списки",
    Permission.MONEY: "Себестоимость и маржа",
    Permission.SOURCING: "Задание закупщику",
    Permission.REMARKS: "Замечания заказчику",
    Permission.CRM: "Карточки лотов",
    Permission.DECIDE: "Решение об участии",
    Permission.MOVE: "Перевод лота по состояниям",
    Permission.SIGN_MANAGER: "Подпись менеджера",
    Permission.SIGN_SUPPLY: "Подпись снабжения",
    Permission.SIGN_LEGAL: "Подпись юриста",
    Permission.SIGN_TECHNOLOGIST: "Подпись технолога",
    Permission.SIGN_ASSEMBLER: "Подпись сборщика",
    Permission.ADMIN: "Управление платформой",
}

PERMISSION_ABOUT: dict[Permission, str] = {
    Permission.PAGE_LOTS: "Сквозной список закупок: где какая и у кого",
    Permission.PAGE_DESK_DISCUSSION: "Очередь задач по замечаниям заказчику",
    Permission.PAGE_DESK_ANALYSIS: "Очередь задач разбора: себестоимость и решение",
    Permission.PAGE_DESK_SUPPLY: "Очередь задач снабжения: поиск товара и сроки",
    Permission.PAGE_DESK_LEGAL: "Очередь задач юристов",
    Permission.PAGE_TASKS: "Поручения вне лота: что на тебе и что ты поручил",
    Permission.PAGE_SUBMIT: "Календарь подач и итоги",
    Permission.PAGE_APPROVAL: "Где чьи подписи под участием",
    Permission.PAGE_REMARKS: "Переписка с заказчиком до подачи заявки",
    Permission.PAGE_PORTAL: "Что выгрузилось с госзакупок по нашим кодам",
    Permission.PAGE_PORTAL_CODES: "Список кодов ЕНС ТРУ: настройка, не работа",
    Permission.PAGE_SKSTORE: "Список закупов площадки",
    Permission.PAGE_SKSTORE_ANALYTICS: "Разрезы и объёмы закупов. За ними суммы",
    Permission.PAGE_OMARKET: "Список предзаказов площадки",
    Permission.PAGE_OMARKET_ANALYTICS: "Разрезы и объёмы предзаказов",
    Permission.PAGE_TENDER_PICK: "Отбор: за ним суммы и маржа, без них он пуст",
    Permission.PAGE_TENDER_WORKS: "Общий стол разбора и снабжения по тендерам",
    Permission.PAGE_TENDER_ANALYTICS: "Разрезы и объёмы тендеров",
    Permission.PAGE_AUDIT: "Кто что сделал. О человеке спрашивают не его",
    Permission.PAGE_PEOPLE: "Люди, роли и права",
    Permission.PAGE_NOTIFY: "Доходят ли сообщения до людей",
    Permission.LOT_TAKE: "Заводить карточку из списка портала",
    Permission.LOT_CLAIM: "Становиться ведущим у ничьего лота",
    Permission.LOT_ASSIGN: "Менять ведущего и менеджера. Право руководящее",
    Permission.LOT_SUBMIT: "Отмечать, что заявка подана, и за сколько",
    Permission.LOT_RESULT: "Выиграли, проиграли, кто и за сколько взял",
    Permission.TASKS: "Заводить задачи отделам и закрывать свои",
    Permission.FILES: "Прикладывать документы к лоту и убирать их",
    Permission.SHEET_EDIT: "Столбцы, строки и значения таблицы разбора",
    Permission.SHEET_BUILD: "Модель раскладывает спецификацию. Стоит денег",
    Permission.REMARK_WRITE: "Править текст и звать модель его написать",
    Permission.REMARK_SEND: "Отправка заказчику: необратима и от имени компании",
    Permission.READ: "Списки закупок, очередь задач, справочники. За ними цены",
    Permission.MONEY: "Себестоимость, маржа, наша цена. Самое дорогое право",
    Permission.SOURCING: "Поставщики, целевая цена закупа, статусы поиска",
    Permission.REMARKS: "Переписка с заказчиком до подачи заявки",
    Permission.CRM: "Карточка лота: задачи, файлы, ход по отделам",
    Permission.DECIDE: "Берёмся или нет. Идёт в паре с себестоимостью",
    Permission.MOVE: "Двигать лот: в работу, на согласование, на подачу",
    Permission.SIGN_MANAGER: "Одна из пяти подписей под участием",
    Permission.SIGN_SUPPLY: "Одна из пяти подписей под участием",
    Permission.SIGN_LEGAL: "Одна из пяти подписей под участием",
    Permission.SIGN_TECHNOLOGIST: "Одна из пяти подписей под участием",
    Permission.SIGN_ASSEMBLER: "Одна из пяти подписей под участием",
    Permission.ADMIN: "Люди, роли, журнал, обход портала. Даёт и всё остальное",
}

# Подписи отдельной группой: их пять, они однотипны, и в списке прав их удобнее
# показывать вместе.
SIGNATURES: tuple[Permission, ...] = (
    Permission.SIGN_MANAGER,
    Permission.SIGN_SUPPLY,
    Permission.SIGN_LEGAL,
    Permission.SIGN_TECHNOLOGIST,
    Permission.SIGN_ASSEMBLER,
)

_ALL = frozenset(Permission)

# Права встроенных ролей. Ровно те, что были у них прибитыми наборами: этот
# словарь — перевод прежних проверок на язык прав, а не повод что-то раздать
# заново. Равенство проверяется тестом.
_DESKS = frozenset(
    {
        Permission.PAGE_DESK_DISCUSSION,
        Permission.PAGE_DESK_ANALYSIS,
        Permission.PAGE_DESK_SUPPLY,
        Permission.PAGE_DESK_LEGAL,
    }
)

_PAGES_WORK = (
    frozenset(
        {
            Permission.PAGE_LOTS,
            Permission.PAGE_SUBMIT,
            Permission.PAGE_APPROVAL,
            Permission.PAGE_TASKS,
        }
    )
    | _DESKS
)

_MARKETS = frozenset({Permission.PAGE_SKSTORE, Permission.PAGE_OMARKET})

_ANALYTICS = frozenset(
    {
        Permission.PAGE_SKSTORE_ANALYTICS,
        Permission.PAGE_OMARKET_ANALYTICS,
        Permission.PAGE_TENDER_ANALYTICS,
    }
)

BUILT_IN: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: _ALL,
    Role.ANALYST: _PAGES_WORK
    | frozenset(
        {
            Permission.READ,
            Permission.MONEY,
            Permission.SOURCING,
            Permission.REMARKS,
            Permission.CRM,
            Permission.MOVE,
            Permission.PAGE_REMARKS,
            Permission.PAGE_PORTAL,
            *_MARKETS,
            Permission.PAGE_TENDER_PICK,
            Permission.PAGE_TENDER_WORKS,
            *_ANALYTICS,
            Permission.LOT_TAKE,
            Permission.LOT_CLAIM,
            Permission.TASKS,
            Permission.FILES,
            Permission.SHEET_EDIT,
            Permission.SHEET_BUILD,
            Permission.REMARK_WRITE,
        }
    ),
    Role.MANAGER: _PAGES_WORK
    | frozenset(
        {
            Permission.READ,
            Permission.MONEY,
            Permission.SOURCING,
            Permission.CRM,
            Permission.DECIDE,
            Permission.MOVE,
            Permission.SIGN_MANAGER,
            Permission.PAGE_PORTAL,
            *_MARKETS,
            Permission.PAGE_TENDER_PICK,
            Permission.PAGE_TENDER_WORKS,
            *_ANALYTICS,
            Permission.LOT_TAKE,
            Permission.LOT_CLAIM,
            Permission.LOT_ASSIGN,
            Permission.LOT_SUBMIT,
            Permission.LOT_RESULT,
            Permission.TASKS,
            Permission.FILES,
            Permission.SHEET_EDIT,
        }
    ),
    Role.BUYER: frozenset(
        {
            Permission.READ,
            Permission.SOURCING,
            Permission.CRM,
            Permission.SIGN_SUPPLY,
            Permission.PAGE_LOTS,
            *_DESKS,
            Permission.PAGE_TASKS,
            *_MARKETS,
            # Отбора тендеров здесь нет намеренно: за ним суммы и маржа, а без
            # них он пуст. Остаётся общий стол двух отделов.
            Permission.PAGE_TENDER_WORKS,
            Permission.TASKS,
            Permission.FILES,
            Permission.SHEET_EDIT,
        }
    ),
    Role.LAWYER: frozenset(
        {
            Permission.REMARKS,
            Permission.CRM,
            Permission.MOVE,
            Permission.SIGN_LEGAL,
            Permission.PAGE_LOTS,
            *_DESKS,
            Permission.PAGE_TASKS,
            Permission.PAGE_REMARKS,
            Permission.TASKS,
            Permission.FILES,
            Permission.REMARK_WRITE,
            Permission.REMARK_SEND,
        }
    ),
    Role.TECHNOLOGIST: frozenset(
        {
            Permission.CRM,
            Permission.SIGN_TECHNOLOGIST,
            Permission.PAGE_LOTS,
            *_DESKS,
            Permission.PAGE_TASKS,
            Permission.PAGE_APPROVAL,
            Permission.TASKS,
            Permission.FILES,
        }
    ),
    Role.ASSEMBLER: frozenset(
        {
            Permission.CRM,
            Permission.SIGN_ASSEMBLER,
            Permission.PAGE_LOTS,
            *_DESKS,
            Permission.PAGE_TASKS,
            Permission.PAGE_APPROVAL,
            Permission.TASKS,
            Permission.FILES,
        }
    ),
    Role.HEAD: _PAGES_WORK
    | frozenset(
        {
            Permission.READ,
            Permission.MONEY,
            Permission.CRM,
            Permission.DECIDE,
            *_ANALYTICS,
            Permission.PAGE_TENDER_PICK,
            Permission.PAGE_TENDER_WORKS,
            *_MARKETS,
        }
    ),
    Role.COMMERCIAL: _PAGES_WORK
    | frozenset(
        {
            Permission.READ,
            Permission.MONEY,
            Permission.CRM,
            Permission.DECIDE,
            *_ANALYTICS,
            Permission.PAGE_TENDER_PICK,
            Permission.PAGE_TENDER_WORKS,
            *_MARKETS,
        }
    ),
    Role.VIEWER: frozenset(
        {
            Permission.READ,
            # Раздел задач есть и у наблюдателя: поручение дают человеку, а не
            # должности, и без раздела заведённая ему задача не видна нигде.
            Permission.PAGE_TASKS,
            *_ANALYTICS,
            *_MARKETS,
            Permission.PAGE_TENDER_PICK,
            Permission.PAGE_TENDER_WORKS,
        }
    ),
}

ROLE_NAMES: dict[Role, str] = {
    Role.ADMIN: "Администратор",
    Role.ANALYST: "Тендерщик",
    Role.MANAGER: "Менеджер поставки",
    Role.BUYER: "Закупщик",
    Role.LAWYER: "Юрист",
    Role.TECHNOLOGIST: "Технолог",
    Role.ASSEMBLER: "Сборщик",
    Role.HEAD: "Руководитель",
    Role.COMMERCIAL: "Коммерческий директор",
    Role.VIEWER: "Наблюдатель",
}

ROLE_ABOUT: dict[Role, str] = {
    Role.ADMIN: "Настройки, люди, роли, журнал действий",
    Role.ANALYST: "Разбор закупок, себестоимость, маржа, замечания",
    Role.MANAGER: "Ведёт лот от объявления до оплаты, решает об участии",
    Role.BUYER: "Поиск товара, поставщики, сроки. Цен не видит",
    Role.LAWYER: "Замечания к спецификациям и жалобы. Цен не видит",
    Role.TECHNOLOGIST: "Подтверждает, что товар подходит под требования",
    Role.ASSEMBLER: "Подтверждает, что заказ соберут и отгрузят в срок",
    Role.HEAD: "Решает, участвуем ли, когда цифры спорные",
    Role.COMMERCIAL: "Второй голос в решении об участии",
    Role.VIEWER: "Только чтение отчётов",
}


def of_builtin(key: str) -> frozenset[Permission]:
    """Права встроенной роли по её ключу. Незнакомый ключ — без прав.

    Без прав, а не с ошибкой: ключ приходит из базы, и упавший на нём запрос
    закрыл бы платформу целиком из-за одной испорченной строки. Человек без
    прав увидит пустое меню и позвонит — это поправимо.
    """
    try:
        return BUILT_IN[Role(key)]
    except ValueError:
        return frozenset()


__all__ = [
    "BUILT_IN",
    "PERMISSION_ABOUT",
    "PERMISSION_NAMES",
    "ROLE_ABOUT",
    "ROLE_NAMES",
    "SIGNATURES",
    "Permission",
    "of_builtin",
]
