"""Разбор одной строки отбора.

Те же разделы и в том же порядке, что на листе разбора в книге ядра: решение,
деньги, из чего состоит комплект, где купить, как считали себестоимость,
предложения конкурентов, на что смотреть перед подачей. Человек читает одно и
то же в двух местах, и переставлять разделы значит заставлять его искать
заново.

Ничего не считает: всё уже посчитано ядром и лежит в строке. Текст «на что
смотреть» разбирается на блоки той же функцией, что и в книге, — свой разбор
одного и того же текста однажды разошёлся бы с ним.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from platform_api.modules.detail import (
    Detail,
    Field,
    Section,
    Table,
    money_field,
    text_field,
)
from platform_api.modules.table import Visibility

if TYPE_CHECKING:
    from tender_analyze.application.hunt import RankedRow

_WIDE = Decimal("2.5")
"""Во сколько раз находки должны разойтись, чтобы считать их разными товарами
под одним названием, а не разницей цен."""


def build_detail(item: RankedRow, pick: str = "") -> Detail:
    """Разбор строки отбора.

    `pick` — находка, по которой пересчитать себестоимость вместо выбранной
    ядром. Считает при этом ядро; здесь только показывается результат.
    """
    from platform_api.modules.tender.worklist import recalculate, row_id, tone_of

    row = item.row
    recount = recalculate(row, pick)
    return Detail(
        id=row_id(item),
        title=row.title or "Закупка",
        subtitle=row.customer or row.subject or "",
        verdict=item.verdict.label,
        tone=tone_of(item),
        # Ссылки на площадку у тендерной закупки нет: она пришла папкой по
        # почте, а не из кабинета. Путь к папке показан в разделе «Закупка».
        url=None,
        sections=(
            _about(row),
            _decision(item),
            _money(row, recount),
            _kit(row),
            _where_to_buy(row, recount),
            _cost_lines(row, recount),
            _quotes(row),
            _before_submit(row),
            _files(row),
        ),
    )


def _about(row: Any) -> Section:
    return Section(
        title="Закупка",
        fields=(
            text_field("Заказчик", row.customer),
            text_field("Предмет", row.subject),
            text_field("Категория", row.category),
            text_field("Количество", _plain(row.quantity)),
            text_field("ЕНС ТРУ", row.ens_code),
            text_field("Признак закупки", row.kind),
            text_field("Способ закупки", row.method),
            text_field("Дата закупки", row.date),
            text_field("Папка", row.folder),
        ),
    )


def _decision(item: RankedRow) -> Section:
    """Вердикт и за что он выставлен.

    Основания идут сразу за словом намеренно: балл без них ничего не стоит —
    тендерщик должен видеть, за что закупке начислено, и не согласиться.
    """
    reasons = tuple(Field(label="", text=reason, tone="") for reason in item.verdict.reasons)
    return Section(
        title="Решение",
        fields=(
            text_field("Вердикт", item.verdict.label),
            text_field("Балл", f"{item.verdict.score} из 100"),
            *reasons,
        ),
        access=Visibility.MONEY,
    )


def _money(row: Any, recount: Any = None) -> Section:
    """Четыре числа, ради которых строку и открывают.

    Когда человек выбрал поставщика сам, показываются его числа, а не те, что
    посчитало умолчание: иначе выбор ничего не меняет и смысла в нём нет.
    Считает их ядро — здесь только берётся готовое.
    """
    cost = recount[0] if recount is not None and recount[0] is not None else row.cost
    profit = row.total - cost if row.total is not None and cost is not None else None
    percent = (profit / row.total * 100) if profit is not None and row.total else None
    fields = [
        money_field("Сумма закупки", row.total),
        money_field("Средняя цена КП", row.average_quote),
        money_field("Себестоимость", cost),
        money_field(
            "Заработок",
            profit,
            tone="good" if profit and profit > 0 else "critical" if profit else "",
        ),
        text_field(
            "Маржа",
            f"{percent:.1f} %" if percent is not None else None,
            tone="good" if profit and profit > 0 else "",
        ),
    ]

    note = ""
    low, high = getattr(row, "cost_low", None), getattr(row, "cost_high", None)
    if low is not None and high is not None and low != high:
        fields.append(text_field("Рынок дал", f"от {_plain(low)} до {_plain(high)} ₸"))
        if low > 0 and high / low >= _WIDE:
            note = (
                "Находки разошлись более чем втрое. Это уже не разница цен, а разные"
                " товары под одним названием: какая из них наша — зависит от того, что"
                " пройдёт по ТЗ. Сверьте требования и запросите цену у поставщика."
            )
    return Section(
        title="Деньги",
        fields=tuple(fields),
        note=note,
        access=Visibility.MONEY,
    )


def _kit(row: Any) -> Section:
    """Состав комплекта по техническому заданию.

    Заказчик пишет одну строку, а поставить надо всё перечисленное: цену
    считают по комплекту целиком, а не по головному изделию. Если по части
    цены не нашлось, себестоимость комплекта не считается вовсе — сложить
    найденное и выдать сумму за цену комплекта значит поставить цену станции
    управления вместо цены насосного агрегата.
    """
    parts = row.parts or ()
    if not parts:
        return Section(
            title="Из чего состоит комплект",
            empty="Позиция поставляется одним изделием — комплект не разбирали.",
        )
    missing = set(row.missing or ())
    return Section(
        title="Из чего состоит комплект",
        table=Table(
            columns=("Составляющая", "Характеристики", "Цена найдена"),
            rows=tuple(
                (
                    str(name),
                    str(spec or "—"),
                    "нет — запросить у поставщика" if name in missing else "да",
                )
                for name, spec in parts
            ),
        ),
        note=(
            "По перечисленному выше цены не нашлось, поэтому себестоимость комплекта не посчитана."
            if missing
            else ""
        ),
    )


def _where_to_buy(row: Any, recount: Any = None) -> Section:
    """Находки на рынке — то, с чем менеджер идёт звонить.

    Строка отмечена, если по ней и посчитана себестоимость: без отметки
    непонятно, откуда взялась цифра, и человек пересчитывает её на глаз.

    Строку можно выбрать. Ядро берёт самую дешёвую из подходящих, и это
    правильное умолчание, но не всегда правильный ответ: «подходит» —
    суждение модели, поставщик может быть незнакомым, а срок неподъёмным.
    Выбрал другого — сразу видно, во что это обходится.
    """
    from platform_api.modules.tender.worklist import case_sourcing, finding_key

    market = row.market or ()
    if not market:
        return Section(
            title="Где купить",
            empty="Поиск на рынках по этой закупке не запускали.",
            access=Visibility.SOURCING,
        )
    # Ключи находок берутся у тех же объектов, из которых считалась
    # себестоимость: строка книги их уже не помнит, а сопоставлять по названию
    # значило бы перепутать двух поставщиков с одинаковым товаром.
    saved = case_sourcing(row.folder_path or "")
    sourcing = saved[0] if saved is not None else None
    keys: list[str] = []
    if sourcing is not None:
        by_line = {
            (item.position, item.finding.marketplace, item.finding.supplier or ""): finding_key(
                item
            )
            for item in sourcing.opportunities
        }
        keys = [
            by_line.get((line.position, line.marketplace, line.supplier or ""), "")
            for line in market
        ]

    return Section(
        title="Где купить",
        # Развёрнут, хоть и длинный: с ним менеджер идёт звонить, и это
        # единственное, ради чего разбор открывает закупщик.
        table=Table(
            # Ссылка на карточку товара: находка без неё — обещание, а не
            # поставщик, и менеджер идёт искать её заново. Вешается на
            # площадку — она короткая и различает строки, а название товара
            # в них одно и то же.
            link_column=2,
            links=tuple(line.url or "" for line in market),
            picks=tuple(keys),
            chosen=tuple(sorted(recount[2])) if recount is not None else (),
            # Доставка, срок и минимальная партия убраны намеренно. В книге им
            # место — там лист широкий, — а в панели они съедали треть ширины
            # ради «1 шт» и «20 дн.», одинаковых почти во всех строках. Место
            # отдано графе «тот ли товар»: в ней объяснение, почему находку
            # нельзя брать, и читают её целиком, а не сравнивают числа.
            #
            # Цифры не потеряны: доставка входит в себестоимость и разложена в
            # разделе «как считали», а срок и партию спрашивают у поставщика,
            # когда до него дозвонятся.
            columns=(
                "Позиция",
                "Страна",
                "Площадка",
                "Поставщик",
                "Цена, ₸",
                "Тот ли товар",
            ),
            rows=tuple(
                (
                    line.position,
                    line.country,
                    line.marketplace,
                    line.supplier or "—",
                    _plain(line.price),
                    "да" if line.matches_spec else f"нет: {line.note or 'не по требованиям'}",
                )
                for line in market
            ),
            aligns=("left", "left", "left", "left", "right", "left"),
        ),
        note=(
            "Отмеченная строка — та, по которой посчитана себестоимость. Ядро "
            "берёт самую дешёвую из подходящих; выберите другую, и деньги "
            "пересчитаются под неё."
        ),
        access=Visibility.SOURCING,
    )


def _cost_lines(row: Any, recount: Any = None) -> Section:
    """Себестоимость построчно. Цифра без разбора непроверяема."""
    lines = (recount[1] if recount is not None and recount[1] else None) or row.cost_lines or ()
    if not lines:
        return Section(
            title="Как считали себестоимость",
            empty="Себестоимость не считали: рынок по этой закупке не искали.",
            access=Visibility.MONEY,
        )
    return Section(
        title="Как считали себестоимость",
        table=Table(
            columns=("Статья", "Сумма, ₸", "Обоснование"),
            rows=tuple((str(name), _plain(amount), str(why or "")) for name, amount, why in lines),
            aligns=("left", "right", "left"),
        ),
        access=Visibility.MONEY,
    )


def _quotes(row: Any) -> Section:
    """Предложения конкурентов: цена производителя и цена перекупщика
    означают разное, и без графы «роль» сравнивать их можно только на глаз."""
    quotes = row.quotes or ()
    if not quotes:
        return Section(
            title="Предложения конкурентов",
            empty="КП по этой закупке не собраны — цену ставим от рынка.",
        )
    return Section(
        title="Предложения конкурентов",
        # Свёрнут: в папке бывает два десятка КП, и развёрнутыми они отодвигают
        # деньги за нижний край. Открывают их, когда уже решили участвовать и
        # ставят цену, — а к этому моменту разбор пролистан целиком.
        collapsed=True,
        table=Table(
            columns=("Поставщик", "Документ", "Цена, ₸", "Замечание", "Роль"),
            rows=tuple(
                (
                    str(supplier or "—"),
                    str(document or "—"),
                    _plain(price),
                    str(note or ""),
                    str(status or ""),
                )
                for supplier, document, price, note, status in quotes
            ),
            aligns=("left", "left", "right", "left", "left"),
        ),
    )


def _before_submit(row: Any) -> Section:
    """Разбор модели, разложенный на блоки.

    Разбирается той же функцией, что и в книге: свой разбор одного и того же
    текста однажды разошёлся бы с ним и потерял бы блок.
    """
    from tender_analyze.export.detail import split_sections

    if not row.review:
        return Section(title="На что смотреть перед подачей", empty="Разбора модели нет.")

    blocks = split_sections(row.review)
    if not blocks:
        return Section(
            title="На что смотреть перед подачей",
            fields=(Field(label="", text=row.review),),
            access=Visibility.MONEY,
        )
    return Section(
        title="На что смотреть перед подачей",
        fields=tuple(text_field(head, body) for head, body in blocks),
        # Свёрнут: это разбор модели на девять блоков — страница текста, и
        # читают её перед самой подачей, а не когда решают, браться ли вообще.
        collapsed=True,
        access=Visibility.MONEY,
    )


def _files(row: Any) -> Section:
    """Документы закупки — то, что лежит в её папке.

    Разбор отвечает на «откуда цифра», но последний вопрос перед подачей
    всегда один: «покажи само ТЗ». До сих пор за ним шли в папку на диске, то
    есть выходили из платформы — и обратно к строке возвращались вручную.

    Файлы отдаются платформой, а не копируются в неё: копия разошлась бы с
    папкой в тот день, когда заказчик пришлёт исправленное ТЗ, и разбор
    показывал бы старое.
    """
    from platform_api.modules.tender.worklist import case_files, row_id_of_folder

    files = case_files(row.folder_path or "")
    if not files:
        return Section(
            title="Документы закупки",
            empty="Файлы этой закупки в базе не числятся — папку не разбирали.",
        )

    item_id = row_id_of_folder(row)
    reachable = [item for item in files if item.available]
    fields = tuple(
        Field(
            label=item.kind or "файл",
            text=item.name,
            link=(f"/api/tender/item/{item_id}/file/{item.sha256}" if item.available else None),
            note=_size(item.size_bytes) if item.available else "нет на диске",
            tone="" if item.available else "warning",
        )
        for item in files
    )
    return Section(
        title="Документы закупки",
        fields=fields,
        # Свёрнут: файлов в папке бывает три десятка, и развёрнутыми они
        # отодвигают всё остальное. Открывают их последним движением — когда
        # решение принято и надо свериться с самим ТЗ.
        collapsed=True,
        note=_missing_note(files, reachable),
    )


def _missing_note(files: Any, reachable: Any) -> str:
    """Почему файлов не видно — с путём, по которому их искали.

    «Нет на диске» без пути отвечает на вопрос «что случилось», но не на
    «что чинить». А чинить тут одно из трёх: архив не подключён томом,
    подключён не туда (пути в базе абсолютные и записаны той машиной, где шёл
    разбор) или закрыт правами. Третье выглядит точно так же, как первые два,
    и различается одной попыткой прочитать папку.
    """
    if len(reachable) == len(files):
        return ""
    where = Path(str(files[0].path.parent)) if files else Path()
    if _forbidden(where):
        return (
            f"Файлы на месте, но платформе закрыт доступ к «{where}». Она"
            " работает под своим пользователем, а архив приехал с правами"
            " прежней машины. Открыть на чтение:"
            " sudo chmod -R a+rX <каталог архива>."
        )
    if reachable:
        return (
            f"Часть файлов платформе не видна. Искали в «{where}» — проверьте,"
            " что все они доехали: имена длиннее 255 байт файловая система"
            " Linux не принимает."
        )
    return (
        f"Ни одного файла не видно. Искали в «{where}»: либо архив не подключён"
        " к платформе томом (TENDER_ARCHIVE в .env), либо подключён по другому"
        " пути — в базе ядра пути абсолютные, и записала их та машина, где шёл"
        " разбор. Названия видны и без архива: по ним понятно, что в папке есть."
    )


def _forbidden(where: Path) -> bool:
    """Закрыта ли папка закупки правами.

    Одна попытка на весь раздел, и только когда файлов и так недосчитались:
    на исправном архиве этот вопрос не задаётся вовсе.
    """
    try:
        where.is_dir()
    except PermissionError:
        return True
    except OSError:
        return False
    return False


def _size(value: int) -> str:
    if value >= 1024 * 1024:
        return f"{value / 1024 / 1024:.1f} МБ"
    return f"{max(value, 0) / 1024:.0f} КБ"


def _plain(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, Decimal | int | float):
        return f"{value:,.0f}".replace(",", " ")
    return str(value)


__all__ = ["build_detail"]
