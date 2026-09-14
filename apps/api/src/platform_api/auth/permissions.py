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
    """Что человеку можно. Список закрыт: каждое право кем-то проверяется."""

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

    ADMIN = "admin"
    """Управление платформой: люди, роли, журнал действий, обход портала.

    Даёт и всё остальное: администратор и так распоряжается доступами, и
    запирать его от раздела значит заставить выдать себе роль, чтобы
    посмотреть."""


PERMISSION_NAMES: dict[Permission, str] = {
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
BUILT_IN: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: _ALL,
    Role.ANALYST: frozenset(
        {
            Permission.READ,
            Permission.MONEY,
            Permission.SOURCING,
            Permission.REMARKS,
            Permission.CRM,
            Permission.MOVE,
        }
    ),
    Role.MANAGER: frozenset(
        {
            Permission.READ,
            Permission.MONEY,
            Permission.SOURCING,
            Permission.CRM,
            Permission.DECIDE,
            Permission.MOVE,
            Permission.SIGN_MANAGER,
        }
    ),
    Role.BUYER: frozenset(
        {
            Permission.READ,
            Permission.SOURCING,
            Permission.CRM,
            Permission.SIGN_SUPPLY,
        }
    ),
    Role.LAWYER: frozenset(
        {
            Permission.REMARKS,
            Permission.CRM,
            Permission.MOVE,
            Permission.SIGN_LEGAL,
        }
    ),
    Role.TECHNOLOGIST: frozenset({Permission.CRM, Permission.SIGN_TECHNOLOGIST}),
    Role.ASSEMBLER: frozenset({Permission.CRM, Permission.SIGN_ASSEMBLER}),
    Role.HEAD: frozenset(
        {
            Permission.READ,
            Permission.MONEY,
            Permission.CRM,
            Permission.DECIDE,
        }
    ),
    Role.COMMERCIAL: frozenset(
        {
            Permission.READ,
            Permission.MONEY,
            Permission.CRM,
            Permission.DECIDE,
        }
    ),
    Role.VIEWER: frozenset({Permission.READ}),
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
