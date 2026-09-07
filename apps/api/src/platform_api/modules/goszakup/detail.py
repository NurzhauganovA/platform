"""Разбор одного лота: что покупают и что ещё в этом объявлении.

Строится из двух источников. Сам лот берётся из базы — он там уже лежит,
запросов не стоит. Соседние лоты объявления читаются с портала **при
открытии**: под наши коды из объявления подходит одна позиция из четырёх, а
закупка идёт целиком, и человеку видно должно быть всё.

Читаются, но не хранятся. Чужие позиции меняются вместе с объявлением, а
смотрят их один раз — при решении, браться ли. Класть их в базу значило бы
растить её тем, что устаревает быстрее, чем понадобится второй раз.

Портал недоступен — разбор всё равно открывается: своя часть в нём есть, а
про соседей честно сказано, что не дозвонились. Пустой экран из-за чужого
сервера хуже неполного.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from platform_api.logging import get_logger
from platform_api.modules.goszakup import core
from platform_api.modules.schemas import (
    DetailField,
    DetailOut,
    DetailSection,
    DetailTable,
    TakeOut,
)

logger = get_logger(__name__)

ANNOUNCE_LOTS = "announce_lots"
"""Ключ раздела с лотами объявления. Карточка лота показывает его у себя."""


def build(lot: Any, *, code: str = "", facts: bool = False) -> DetailOut:
    """Собирает разбор лота.

    Устойчивый код приходит снаружи, а не считается здесь: он живёт в базе
    платформы, а этот файл видит только базу площадки. Пустой код означает,
    что карточку по этой строке завести нечем.

    `facts` — только сроки и что покупают, без спецификации и соседних лотов.
    Так карточка лота открывает «Данные закупки»: спецификация у неё своя, во
    вкладке разбора. Дело не в двух лишних разделах, а в походе на портал за
    соседями: он занимает до минуты, и панель, которая показывает восемь полей
    из базы, минуту крутила колесо ради того, что в ней не нарисуется.
    """
    if facts:
        return DetailOut(
            id=core.row_id(lot),
            title=lot.name or lot.purchase_number,
            subtitle=lot.customer,
            verdict=_verdict(lot),
            tone=core.tone_of(lot),
            url=_where(lot),
            sections=[_about(lot), _what(lot)],
        )

    neighbours, trouble = _announce_neighbours(lot)

    return DetailOut(
        id=core.row_id(lot),
        title=lot.name or lot.purchase_number,
        subtitle=lot.customer,
        verdict=_verdict(lot),
        tone=core.tone_of(lot),
        url=_where(lot),
        remark_key=lot.lot_number,
        take=_take(lot, code) if code else None,
        sections=[
            _about(lot),
            _what(lot),
            _spec(lot),
            _neighbours(lot, neighbours, trouble),
        ],
    )


def _where(lot: Any) -> str:
    """Куда ведёт кнопка «Открыть на площадке».

    Ссылку снимает выгрузка и кладёт рядом с лотом. Собирать её здесь значило
    бы держать догадку о том, как у портала устроены адреса: переезд на единый
    сменил и вид ссылки, и внутренние номера, а заметно это стало только по
    жалобе — кнопка вела в поиск по номеру закупки, общему у всех лотов
    объявления, и человек попадал в список вместо своего лота.

    У записей, выгруженных до переезда, ссылки нет: их номеров на новом
    портале не существует. Им остаётся поиск — но по номеру лота, а он
    единственный.
    """
    from goszakup.infrastructure.portal import api

    if lot.url:
        return str(lot.url)
    query = lot.lot_number or lot.purchase_number
    return str(api.SEARCH_PAGE.format(query=query))


def _take(lot: Any, code: str) -> TakeOut:
    """Чем заводить карточку.

    Ключ — номер лота, а не номер закупки: у объявления с четырьмя лотами
    номер закупки один на всех, и карточка завелась бы одна на четыре разных
    товара.

    Код — устойчивый «GZ000171», а не номер закупки. По коду лот зовут вслух и
    ищут в списке; номер закупки на этом месте означал бы, что четыре лота
    одного объявления в списке работ неразличимы.
    """
    return TakeOut(
        module="goszakup",
        row_id=lot.lot_number,
        code=code,
        source_number=lot.purchase_number,
        title=lot.name or lot.enstru_name or lot.purchase_number,
        customer=lot.customer,
        amount=_float(lot.amount),
        enstru_code=lot.enstru_code,
        category=lot.enstru_name,
        deadline=_aware_iso(lot.end_date),
    )


def _aware_iso(value: Any) -> str | None:
    """Дата в тексте с зоной. Наивная уехала бы на пять часов при разборе."""
    if value is None:
        return None
    moment = core._aware(value)
    return str(moment.isoformat()) if moment is not None else None


def _verdict(lot: Any) -> str:
    """Словами то же, что цветом строки: успеваем ли подать."""
    from datetime import UTC, datetime

    left = core._left_seconds(lot, datetime.now(UTC))
    if left is None:
        return "Срок не указан"
    if left <= 0:
        return "Приём закрыт"
    if left < 86_400:
        return "Горит: меньше суток"
    return "Приём идёт"


def _about(lot: Any) -> DetailSection:
    """Сроки и состояние — то, по чему решают, успеваем ли."""
    return DetailSection(
        title="Объявление",
        fields=[
            DetailField(label="Номер закупки", text=lot.purchase_number),
            DetailField(label="Номер лота", text=lot.lot_number),
            DetailField(label="Способ закупки", text=lot.method),
            DetailField(label="Статус лота", text=lot.status),
            DetailField(
                label="Приём до",
                text=_moment(lot.end_date),
                format="datetime",
                tone=core.tone_of(lot),
            ),
            DetailField(label="Осталось", text=_left(lot)),
            DetailField(
                label="Подано заявок",
                number=float(lot.applications) if lot.applications is not None else None,
                format="number",
                note="Столько конкурентов уже видно" if lot.applications else "",
            ),
            DetailField(label="Опубликовано", text=_moment(lot.published_at), format="datetime"),
        ],
    )


def _what(lot: Any) -> DetailSection:
    """Что именно покупают. Здесь же — предел цены заказчика.

    Плановая сумма не наша тайна: её видит любой участник на портале. Прятать
    её значило бы прятать то, что открыто всем, а решают именно по ней.
    """
    return DetailSection(
        title="Что покупают",
        fields=[
            DetailField(label="Наименование", text=lot.name),
            DetailField(label="Код ЕНС ТРУ", text=lot.enstru_code),
            DetailField(label="Наименование ТРУ", text=lot.enstru_name),
            DetailField(label="Краткая характеристика", text=lot.brief),
            DetailField(
                label="Дополнительная характеристика",
                text=lot.extra,
                note="Здесь заказчик пишет, что именно ему нужно"
                if len(lot.extra or "") > 120
                else "",
            ),
            DetailField(
                label="Количество",
                text=f"{_amount(lot.count)} {lot.unit}".strip(),
            ),
            DetailField(label="Цена за единицу", number=_float(lot.unit_price), format="money"),
            DetailField(label="Плановая сумма", number=_float(lot.amount), format="money"),
            DetailField(
                label="Аванс",
                text=f"{_amount(lot.prepayment_percent)}%"
                if lot.prepayment_percent is not None
                else "",
            ),
            DetailField(label="Место поставки", text=lot.kato),
            DetailField(label="Срок поставки", text=lot.delivery_term),
            DetailField(label="Условия ИНКОТЕРМС", text=lot.incoterms),
        ],
    )


def _spec(lot: Any) -> DetailSection:
    """Техническая спецификация лота — то, по чему закупают.

    Стоит отдельным разделом, а не строкой в характеристиках: у большинства
    лотов «дополнительная характеристика» — одна строка вроде «Ноутбук», а в
    приложенном файле шесть тысяч знаков требований. Одно поле на то и другое
    означало бы, что настоящее описание видно только через прокрутку внутри
    ячейки.

    Свёрнута: читают её один раз, когда решают браться, а на экране она
    заслоняет сроки и цену, ради которых разбор чаще всего и открывают.
    """
    text = (lot.spec_text or "").strip()
    if not text:
        return DetailSection(
            title="Техническая спецификация",
            empty=(
                "К этому объявлению спецификация не приложена. "
                "Смотрите дополнительную характеристику выше — другого описания портал не даёт"
            ),
        )

    # Ссылка на нас, а не на портал. Портальная ведёт на соседний хост, живёт
    # вместе с его выкладками и отдаёт файл с именем вида `file_1837462.docx`
    # — по такому имени в папке «Загрузки» ничего не найти.
    файл = f"/api/goszakup/item/{lot.lot_number}/spec" if lot.spec_url else None
    return DetailSection(
        title="Техническая спецификация",
        note=f"Из файла {lot.spec_name}" if lot.spec_name else "",
        collapsed=True,
        fields=[
            DetailField(
                label="Документ",
                text=lot.spec_name or "Скачать файл",
                link=файл,
                note="Тот самый файл с портала — его отправляют технологу и прикладывают к заявке"
                if файл
                else "",
            ),
            DetailField(label="", text=text),
        ],
    )


def _neighbours(lot: Any, found: tuple[_Neighbour, ...], trouble: str) -> DetailSection:
    """Все лоты объявления, наш отмечен.

    Торги идут по объявлению целиком, и соседние лоты — это и конкуренты за
    то же внимание заказчика, и повод взять закупку целиком, если остальное
    мы тоже возим.
    """
    if not found:
        return DetailSection(
            key=ANNOUNCE_LOTS,
            title="Лоты объявления",
            empty=trouble or "Портал не показал таблицу лотов этого объявления",
        )

    ours = (lot.lot_number or "").strip()
    mine = sum(1 for item in found if item.ours)
    return DetailSection(
        key=ANNOUNCE_LOTS,
        title="Лоты объявления",
        note=_note(len(found), mine),
        table=DetailTable(
            columns=["", "Номер лота", "Наименование", "Кол-во", "Сумма, ₸", "Статус"],
            aligns=["left", "left", "left", "right", "right", "left"],
            rows=[
                [
                    "▸" if item.number == ours else "",
                    item.number,
                    _both(item.name, item.extra),
                    f"{_amount(item.count)} {item.unit}".strip(),
                    _money(item.amount),
                    item.status,
                ]
                for item in found
            ],
        ),
        collapsed=len(found) > 6,
    )


def _note(total: int, mine: int) -> str:
    """Подпись под таблицей: сколько лотов и сколько из них наши.

    Разница важна: наш лот лежит в рабочем списке, и его можно взять в работу;
    чужой на портале есть, а у нас его нет — под наши коды ЕНС ТРУ он не
    подошёл. Одно число на оба случая оставляло бы человека гадать, почему
    половины строк он в списке не находит.
    """
    if total == 1:
        return "В объявлении один лот — наш."
    if mine == total:
        return f"Всего {total}, все под нашими кодами ЕНС ТРУ; наш отмечен."
    if mine <= 1:
        return (
            f"Всего {total}; наш отмечен. Остальные под наши коды ЕНС ТРУ не подошли — "
            "в рабочем списке их нет, но закупка идёт по объявлению целиком."
        )
    return (
        f"Всего {total}, из них под нашими кодами {mine}; открытый отмечен. "
        "Закупка идёт по объявлению целиком."
    )


@dataclass(frozen=True, slots=True)
class _Neighbour:
    """Лот объявления для таблицы, откуда бы он ни пришёл."""

    number: str
    name: str
    extra: str
    count: Decimal | None
    unit: str
    amount: Decimal | None
    status: str
    ours: bool
    """Есть в нашей базе — то есть подошёл под наши коды ЕНС ТРУ."""


def _announce_neighbours(lot: Any) -> tuple[tuple[_Neighbour, ...], str]:
    """Соседние лоты объявления: сначала наши, затем чужие с портала.

    Основа — своя база, а не портал. В списке лоты одного объявления уже
    стоят рядом и сворачиваются в одну строку: связь известна нам самим, по
    `announce_id`. Портал же на объявления, выгруженные до его переезда,
    отвечает 404 — их внутренние номера сменились. Получалось, что в списке
    человек видит два лота, открывает карточку и не находит ни одного.

    Портал по-прежнему опрашивается, но ради другого: под наши коды из
    объявления подходит одна позиция из четырёх, а торги идут по объявлению
    целиком, и остальные три — это и конкуренты за внимание заказчика, и
    повод взять закупку целиком. Не ответил — раздел остаётся с нашими, а не
    пустым.
    """
    ours = _from_base(lot.announce_id)
    found, trouble = _from_portal(lot.announce_id)

    by_number = {item.number: item for item in ours}
    for item in found:
        # Портал свежее нашей выгрузки, но признак «наш» знаем только мы.
        by_number[item.number] = replace(item, ours=item.number in by_number)

    merged = tuple(sorted(by_number.values(), key=lambda item: item.number))
    if not merged:
        return (), trouble
    # Своё есть — про недоступный портал сообщать нечего: раздел не пуст, а
    # неполон, и об этом говорит подпись под таблицей.
    return merged, ""


def _from_base(announce_id: int) -> tuple[_Neighbour, ...]:
    """Лоты объявления из нашей базы. Запросов к порталу не стоит."""
    from goszakup.infrastructure.db.models import LotRecord
    from sqlalchemy import select

    with core.session() as db:
        rows = (
            db.execute(select(LotRecord).where(LotRecord.announce_id == announce_id))
            .scalars()
            .all()
        )
    return tuple(
        _Neighbour(
            number=row.lot_number or "",
            name=row.name or "",
            extra=row.extra or "",
            count=row.count,
            unit=row.unit or "",
            amount=row.amount,
            status=row.status or "",
            ours=True,
        )
        for row in rows
    )


def _from_portal(announce_id: int) -> tuple[tuple[_Neighbour, ...], str]:
    """Читает лоты объявления с портала. Возвращает их и причину неудачи.

    Через открытое API, а не разбором страницы: страниц у портала больше нет.
    Прежний разбор молча получал страницу входа и показывал раздел пустым —
    выглядело это как «в объявлении один лот», то есть как правда.
    """
    from goszakup.infrastructure.http import PortalClient
    from goszakup.infrastructure.portal import api

    try:
        with PortalClient(core.core_settings().http) as client:
            raw = api.parse_announce_lots(
                client.get_json(api.ANNOUNCE_LOTS_URL.format(announce_id=announce_id))
            )
    except Exception as exc:
        logger.warning("goszakup.announce.unreachable", announce=announce_id, error=str(exc))
        # 404 — это не молчание портала, а ответ: такого объявления у него
        # нет. Так отвечают объявления, выгруженные с прежнего портала: при
        # переезде им сменили внутренние номера. Одна фраза на оба случая
        # отправляла бы человека проверять связь там, где связь ни при чём.
        if "404" in str(exc):
            return (), (
                "Это объявление заведено на прежнем портале, и на новом его карточки нет. "
                "Соседние лоты появятся после обновления списка кнопкой «Обновить данные»"
            )
        return (), "Портал сейчас не отвечает — соседние лоты объявления показать не смогли"
    return (
        tuple(
            _Neighbour(
                number=item.number,
                name=item.name,
                extra=item.extra,
                count=item.count,
                unit=item.unit,
                amount=item.amount,
                status=item.status,
                ours=False,
            )
            for item in raw
        ),
        "",
    )


def _both(name: str, extra: str) -> str:
    """Наименование с уточнением: лоты объявления часто зовутся одинаково.

    «Колодка тормозная» стоит дважды, и различает их только дополнительная
    характеристика — передние они или задние.
    """
    if not extra or extra.strip() == name.strip():
        return name
    if not name.strip():
        # Название у лота бывает пустым: карточку на портале не заполнили. Без
        # этой проверки строка начиналась с « · » — выглядело как потерянное
        # при показе слово, а не как незаполненное на портале поле.
        return extra[:80]
    return f"{name} · {extra[:80]}"


def _moment(value: Any) -> str:
    """Момент времени — строкой с меткой пояса, а не готовым текстом.

    Раньше здесь стоял `strftime`, и час уходил как есть: время у портала в
    UTC, и на экране «Приём до» показывало 09:00, тогда как приём шёл до 14:00
    по Алматы. Рядом «Осталось» считалось верно, и два числа в одной карточке
    противоречили друг другу — а человек по ним решает, успевает он подать
    или нет.

    Приводит к местному времени браузер: у него для этого есть `TZ` раздела, и
    делать это в двух местах значит однажды разойтись.
    """
    from platform_api.modules.table import to_utc

    if value is None:
        return ""
    return (to_utc(value) or value).isoformat()


def _left(lot: Any) -> str:
    from goszakup.export.sheet import left

    return left(lot)


def _amount(value: Decimal | None) -> str:
    if value is None:
        return ""
    whole = value.to_integral_value()
    return f"{whole:f}" if value == whole else f"{value.normalize():f}"


def _money(value: Decimal | None) -> str:
    return f"{value:,.2f}".replace(",", " ") if value is not None else ""


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
