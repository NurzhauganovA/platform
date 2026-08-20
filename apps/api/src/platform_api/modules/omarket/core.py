"""Единственная точка, где платформа обращается к ядру OMarket.

Всё остальное в модуле ходит через неё. Когда ядро изменит имя класса или
сигнатуру, это выяснится здесь, а не россыпью по обработчикам запросов.

Ядро настраивается своим `.env` с префиксом `OMARKET__` и своей базой — оно
самостоятельный проект, а не часть платформы.

**Чтение не стоит денег и не ходит в сеть.** Оценки лежат в базе готовыми:
их посчитал прошлый прогон. Страница только достаёт их и складывает с
предзаказами — так же, как это делает лист «Фокус» книги Excel.

**Вход по ЭЦП остаётся в терминале, и это не недоделка.** Площадка требует
подписи ключом в окне настоящего браузера, а безоконный режим отсекает ещё до
формы входа. Ключ лежит у человека, а не на сервере, и переносить туда
подпись значило бы переносить туда и ключ. Платформа работает с сессией,
снятой при `omarket login`, и честно говорит, когда та кончилась.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from platform_api.modules.detail import (
    Detail,
    Field,
    Section,
    Table,
    date_field,
    money_field,
    percent_field,
    text_field,
)
from platform_api.modules.table import Visibility, is_past, to_utc

if TYPE_CHECKING:
    from omarket.config import Settings
    from omarket.export.reports import FocusRow

    from platform_api.modules.table import Column


@lru_cache(maxsize=1)
def core_settings() -> Settings:
    """Настройки ядра OMarket."""
    from omarket.config import get_settings

    return get_settings()


def focus_columns() -> Sequence[Column]:
    """Колонки рабочего списка — те же, что в листе «Фокус (что смотреть)».

    Берутся из самого проекта, а не описываются здесь заново: человек смотрит
    на экран и в выгруженный файл, и колонки в них обязаны совпадать.
    """
    from omarket.export.reports import FOCUS_COLUMNS

    return FOCUS_COLUMNS


def sheet_title() -> str:
    from omarket.export.reports import SHEET_TITLES

    return str(SHEET_TITLES["focus"])


@dataclass(frozen=True, slots=True)
class Worklist:
    """Что показывать в рабочем списке."""

    rows: tuple[FocusRow, ...]
    total: int
    expired: int
    """Сколько предзаказов с истёкшим приёмом. Из базы они не удаляются — это
    история, и по ней видно, что мы пропустили, — но в рабочем списке их нет."""

    verdicts: dict[str, int]
    margin_total: Decimal | None

    focused: int
    """Сколько строк попадает в отбор — с чем действительно можно работать."""

    priced: int
    """По скольким предзаказам себестоимость вообще известна. Остальные — это
    не «невыгодно», а «не с чем сравнивать», и путать их нельзя."""

    analyzed: bool
    """Считали ли вообще. Пустой список без этого признака выглядит как «нет
    предзаказов», хотя на деле их просто ещё не оценивали."""


def in_focus(row: Any) -> bool:
    """Есть ли с предзаказом что делать.

    Закрытые по признакам площадки (ОТП, ООИ, только дистрибьюторы) и заведомо
    невыгодные — нет: с ними ничего сделать нельзя, а верх списка они занимают.
    """
    return _actionable(row)


def worklist() -> Worklist:
    """Рабочий список предзаказов в том же порядке, что и лист «Фокус».

    Сортировка берётся у проекта: сначала по вердикту, внутри — по ближайшему
    сроку. Так сверху оказывается то, чем стоит заняться сегодня, и так же
    выглядит выгруженный файл.
    """
    from omarket.domain.enums import PreorderStatus
    from omarket.export.reports import FocusRow

    container = _container()
    try:
        with container.unit_of_work() as uow:
            analyses = uow.analyses.by_platform_id()
            rows = [
                FocusRow(preorder=item, analysis=analyses.get(item.platform_id))
                for item in uow.preorders.iter_by_status(PreorderStatus.ACTUAL)
            ]
            # Оценки — строки ORM, а выход из единицы работы делает откат и
            # обесценивает их: у отвязанной строки любое поле превращается в
            # обращение к закрытой сессии. Отцепляем заранее — прочитанное
            # при этом остаётся при них, а читать нам только и нужно.
            uow.session.expunge_all()
    finally:
        container.dispose()

    rows.sort(key=_focus_order())

    # Счётчики считаются по действующим, а не по всему, что лежит в базе:
    # «всего 381» при трёхстах восьмидесяти истёкших — неправда о том,
    # сколько работы на самом деле.
    live = [row for row in rows if not is_expired(row)]
    margins = [
        row.analysis.margin_total
        for row in live
        if row.analysis is not None
        and row.analysis.margin_total is not None
        and row.analysis.margin_total > 0
    ]
    return Worklist(
        rows=tuple(rows),
        total=len(live),
        expired=len(rows) - len(live),
        verdicts=_verdicts(live),
        margin_total=sum(margins, Decimal(0)) if margins else None,
        focused=sum(1 for row in rows if _actionable(row)),
        priced=sum(1 for row in live if row.analysis and row.analysis.cost_price is not None),
        analyzed=bool(analyses),
    )


def export_workbook() -> Path:
    """Собирает книгу Excel — ту же, что делает `omarket export`."""
    from omarket.application.export import ExportService

    container = _container()
    try:
        return ExportService(container).export_workbook()
    finally:
        container.dispose()


def readiness() -> dict[str, Any]:
    """Что настроено, а что нет."""
    settings = core_settings()
    problems: list[str] = []

    preorders = _count_preorders()
    if preorders is None:
        problems.append("База OMarket недоступна — выполните `omarket init-db`")
    elif preorders == 0:
        problems.append("В базе нет предзаказов — нажмите «Обновить данные»")

    session = settings.auth.session_file.exists()
    if not session:
        problems.append(
            "Нет сессии кабинета. Вход идёт по ЭЦП в окне браузера, "
            "поэтому выполняется на своей машине: `omarket login`"
        )
    if not settings.gemini.is_configured:
        problems.append("Не задан GEMINI_API_KEY — себестоимость будет только по складу Marten")
    if not settings.ourstore.is_configured:
        problems.append("Не задан склад Marten: OMARKET__OURSTORE__EMAIL и PASSWORD")

    # Файловая база — для платформы неисправность, а не выбор. К ней
    # одновременно ходят почасовые прогоны и открытые страницы, а пишущий в
    # SQLite блокирует файл целиком. Молчать об этом нельзя: сломается оно не
    # сразу, а в первый час, когда работают все.
    if settings.db.is_sqlite:
        problems.append(
            "Ядро работает с файлом SQLite, а не с общей базой — задайте OMARKET__DB__URL"
        )

    return {
        "ok": not problems,
        "core_version": core_version(),
        "database": _database(settings),
        "preorders": preorders or 0,
        "session": session,
        "market_search": settings.sourcing.enabled and settings.gemini.is_configured,
        "market_model": settings.sourcing.model,
        "warehouse": settings.ourstore.is_configured,
        "problems": tuple(problems),
    }


def has_session() -> bool:
    """Жива ли сессия кабинета. Без неё выгрузка невозможна."""
    return core_settings().auth.session_file.exists()


def _database(settings: Any) -> str:
    """С какой базой работает ядро — словами, на страницу готовности.

    Не украшение: URL задаётся окружением, и забытая переменная не ломает
    ничего заметного — модуль просто продолжает писать в старый файл SQLite
    рядом с проектом. Обнаруживается это через неделю по тому, что свежих
    закупов нет, хотя прогоны отработали.
    """
    return "SQLite (файл)" if settings.db.is_sqlite else "PostgreSQL"


_TONES = {
    "promising": "good",
    "marginal": "warning",
    "unknown": "info",
    "unprofitable": "critical",
    "blocked": "",
}
"""Как подсвечена строка. Те же четыре состояния, что заливают строки в книге:
глаз ищет зелёное, а не читает двести строк подряд. Вердикт при этом стоит
словами первой колонкой — цвет сам по себе смысла не несёт."""


def legend() -> tuple[tuple[str, str, str], ...]:
    """Что означает цвет строки: тон, слово и пояснение.

    Слова берутся из книги того же проекта, а не пишутся здесь заново: человек
    сверяет экран с выгруженным файлом, и «на грани» против «проверить» в двух
    местах — это вопрос, на который потом отвечать.
    """
    from omarket.domain.enums import Verdict
    from omarket.export.reports import verdict_text

    hints = {
        "good": "маржа выше порога — этим стоит заняться",
        "warning": "маржа на грани или совпадение сомнительно",
        "info": "себестоимость не нашлась — сравнивать не с чем",
        "critical": "дороже выручки или круг поставщиков закрыт",
    }
    # Порядок — по тяжести, а не по перечислению: легенду читают сверху вниз,
    # и «не участвовать» между «участвовать» и «разобрать» сбивает.
    by_tone = {tone: verdict for verdict in Verdict if (tone := _TONES.get(verdict.value, ""))}
    seen: list[tuple[str, str, str]] = []
    for tone in ("good", "warning", "info", "critical"):
        verdict = by_tone.get(tone)
        if verdict is None:
            continue
        seen.append((tone, verdict_text(verdict), hints[tone]))
    return tuple(seen)


def tone_of(row: Any) -> str:
    """Подсветка строки по её вердикту."""
    verdict = _verdict_of(row)
    return _TONES.get(verdict, "")


def row_id(row: Any) -> str:
    """Чем открыть разбор этой строки."""
    return str(row.preorder.platform_id)


def row_deadline(row: Any) -> str | None:
    """Когда закрывается приём предложений."""
    value = to_utc(row.preorder.deadline_at)
    return value.isoformat() if value is not None else None


def _verdict_of(row: Any) -> str:
    """Вердикт строки отбора. Без оценки — «ещё не считали», а это не то же
    самое, что «невыгодно»."""
    return str(row.analysis.verdict) if row.analysis is not None else "unknown"


def core_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("omarket-analytics")
    except PackageNotFoundError:  # pragma: no cover — пакет всегда установлен
        return "неизвестна"


# ---------------------------------------------------------------------------


def _container() -> Any:
    from omarket.application.container import Container

    return Container(core_settings())


def _focus_order() -> Any:
    """Сортировка листа «Фокус» — берём у проекта, а не пишем свою.

    Своя разошлась бы с книгой на первой же смене порогов, и человек увидел бы
    на экране один порядок строк, а в файле другой.
    """
    from omarket.application.export import focus_order

    return focus_order


def is_ours(row: FocusRow) -> bool:
    """Участвуем ли мы в этом предзаказе.

    Площадка сообщает это прямо: подано ли наше предложение, какое у него
    место и не выиграли ли мы.
    """
    preorder = row.preorder
    return bool(preorder.has_our_offer or preorder.is_winner or preorder.our_place)


def is_expired(row: FocusRow) -> bool:
    """Приём закончился, и мы в этом предзаказе не участвуем.

    Своё не прячем, даже когда срок вышел: по нему ждут результата.
    """
    return is_past(row.preorder.deadline_at) and not is_ours(row)


def _actionable(row: FocusRow) -> bool:
    """Есть ли смысл показывать строку в рабочем списке.

    Три причины убрать. Закрытые по признакам площадки (ОТП, ООИ, только
    дистрибьюторы) — участвовать нельзя. Заведомо невыгодные — не в чем.
    Истёкшие — поздно. Все они остаются в базе: это история, и по ней видно,
    что мы пропустили и почему. По кнопке «Все строки» они возвращаются.
    """
    from omarket.domain.enums import Verdict

    if is_expired(row):
        return False
    if row.analysis is None:
        return True
    return Verdict(row.analysis.verdict) not in {Verdict.BLOCKED, Verdict.UNPROFITABLE}


def _verdicts(rows: Sequence[FocusRow]) -> dict[str, int]:
    # Ключ — тон, а не значение перечисления. Счётчиками пользуется браузер, а
    # он думает тонами: ими покрашены строки и по ним же собрана легенда.
    # Отдай сюда `promising`, и в разделе, где вердикты называются иначе,
    # плитка «стоит участвовать» молча показала бы ноль.
    counts: dict[str, int] = {}
    for row in rows:
        tone = tone_of(row)
        counts[tone] = counts.get(tone, 0) + 1
    return counts


def _count_preorders() -> int | None:
    """Сколько актуальных предзаказов в базе. `None` — базы ещё нет."""
    from omarket.domain.enums import PreorderStatus

    container = _container()
    try:
        with container.unit_of_work() as uow:
            return sum(1 for _ in uow.preorders.iter_by_status(PreorderStatus.ACTUAL))
    except Exception:
        return None
    finally:
        container.dispose()


__all__ = [
    "Worklist",
    "core_settings",
    "core_version",
    "detail",
    "export_workbook",
    "focus_columns",
    "has_session",
    "in_focus",
    "is_expired",
    "is_ours",
    "legend",
    "readiness",
    "row_deadline",
    "row_id",
    "sheet_title",
    "tone_of",
    "worklist",
]


def detail(platform_id: str) -> Detail | None:
    """Разбор одного предзаказа. `None` — такого в базе нет.

    Порядок разделов тот же, что на листе разбора в книге: решение, деньги,
    что нашлось у нас, конкуренты, на что смотреть перед подачей. Человек
    читает одно и то же в двух местах, и переставлять разделы местами значит
    заставлять его искать заново.

    Ничего не считает. Замечания перед подачей берутся у самого проекта
    (`submission_notes`) — собери их здесь заново, и однажды книга
    предупредит о повторной закупке, а экран промолчит.
    """
    from omarket.export.detail import DetailData, submission_notes

    container = _container()
    try:
        with container.unit_of_work() as uow:
            preorder = uow.preorders.find(platform_id)
            if preorder is None:
                return None
            analysis = uow.analyses.by_platform_id().get(platform_id)
            offers = tuple(uow.preorders.offers_for(platform_id))
            uow.session.expunge_all()
    finally:
        container.dispose()

    data = DetailData(preorder=preorder, analysis=analysis, offers=offers)
    settings = core_settings().analysis

    return Detail(
        id=platform_id,
        title=preorder.title or f"Предзаказ {platform_id}",
        subtitle=preorder.customer_name or preorder.category or "",
        verdict=_verdict_text(analysis),
        tone=_TONES.get(analysis.verdict if analysis else "unknown", ""),
        url=preorder.url,
        sections=(
            _about(preorder),
            _decision(analysis),
            _money(preorder, analysis, settings),
            _sourcing(analysis),
            _competitors(offers, settings),
            _before_submit(submission_notes(data)),
        ),
    )


def _about(preorder: Any) -> Section:
    from omarket.analysis.margin import format_quantity

    return Section(
        title="Предзаказ",
        fields=(
            text_field("Заказчик", preorder.customer_name),
            text_field("БИН", preorder.customer_bin),
            text_field("Количество", format_quantity(preorder.quantity)),
            text_field("Единица", preorder.unit),
            text_field("Место поставки", preorder.delivery_place),
            text_field("Категория", preorder.category),
            text_field("Код ТРУ", preorder.tru_code),
            date_field("Срок подачи", preorder.deadline_at),
        ),
    )


def _decision(analysis: Any) -> Section:
    if analysis is None:
        return Section(
            title="Решение",
            empty="Себестоимость ещё не считали — нажмите «Пересчитать».",
        )
    return Section(
        title="Решение",
        fields=(
            text_field("Вердикт", _verdict_text(analysis), tone=_TONES.get(analysis.verdict, "")),
            text_field("Почему", analysis.reason),
        ),
        access=Visibility.MONEY,
    )


def _money(preorder: Any, analysis: Any, settings: Any) -> Section:
    """Четыре числа, и путать их нельзя: цена, выручка, закуп, себестоимость.

    Комиссия площадки — прямой вычет из того, что до нас дойдёт. Пока карточку
    не читали, она неизвестна, и об этом сказано прямо: иначе непрочитанная
    карточка молча улучшала бы маржу.
    """
    commission = (
        text_field("Комиссия площадки", f"{preorder.commission_percent:g} %")
        if preorder.commission_percent is not None
        else text_field(
            "Комиссия площадки",
            "не известна",
            tone="warning",
            note="карточку ещё не читали — маржа может быть завышена на её величину",
        )
    )
    fields = [
        money_field("Цена предзаказа", preorder.unit_price),
        commission,
        money_field("Выручка с единицы", analysis.revenue_price if analysis else None),
        money_field("Цена закупа", analysis.purchase_price if analysis else None),
        text_field("Накладные", f"{settings.overhead_percent:g} %"),
        money_field("Себестоимость", analysis.cost_price if analysis else None),
        text_field("Расчёт", analysis.cost_breakdown if analysis else None),
        text_field("Источник цены", analysis.cost_label if analysis else None),
        percent_field(
            "Маржа",
            analysis.margin_ratio if analysis else None,
            tone=_margin_tone(analysis),
        ),
        money_field("Заработок всего", analysis.margin_total if analysis else None),
    ]
    return Section(title="Деньги", fields=tuple(fields), access=Visibility.MONEY)


def _sourcing(analysis: Any) -> Section:
    from omarket.analysis.margin import format_quantity

    if analysis is None or not analysis.match_title:
        return Section(
            title="Где взять",
            empty="Совпадения не нашлось: ни на складе, ни у поставщиков, ни на рынке.",
            access=Visibility.SOURCING,
        )
    score = analysis.match_score
    return Section(
        title="Где взять",
        fields=(
            text_field("Позиция", analysis.match_title, link=analysis.match_url),
            text_field("Артикул", analysis.match_sku),
            percent_field(
                "Уверенность совпадения",
                score,
                tone="warning" if score is not None and score < 0.6 else "",
                note=(
                    "связка строится по названию, а не по жёсткому ключу — "
                    "слабое совпадение даёт красивую, но выдуманную маржу"
                )
                if score is not None and score < 0.6
                else "",
            ),
            text_field("На складе", format_quantity(analysis.stock_qty)),
            text_field("Лучший поставщик", analysis.supplier_name),
            money_field("Цена поставщика", analysis.supplier_price),
            text_field("Где купить", analysis.finding_label, link=analysis.finding_url),
        ),
        access=Visibility.SOURCING,
    )


def _competitors(offers: Any, settings: Any) -> Section:
    if not offers:
        return Section(
            title="Конкуренты",
            empty=("Предложений пока нет. Это либо свежий предзаказ, либо карточку ещё не читали."),
        )
    rows = tuple(
        (
            str(offer.place),
            offer.supplier_name or "—",
            _plain(offer.price),
            _plain(offer.price_vat),
            _plain(offer.total_sum),
            ", ".join(
                mark
                for mark in ("наше" if offer.is_ours else "", "демпинг" if offer.is_dumping else "")
                if mark
            ),
        )
        for offer in offers
    )
    prices = [offer.price_vat for offer in offers if offer.price_vat]
    note = ""
    if len(prices) >= 2:
        low, high = min(prices), max(prices)
        note = f"Разброс: от {_plain(low)} до {_plain(high)} ₸."
        if low > 0 and high / low >= settings.wide_market_ratio:
            note += (
                f" Предложения разошлись более чем в {settings.wide_market_ratio:g} раза —"
                " это уже не разница цен, а разные товары под одним названием."
            )
    return Section(
        title="Конкуренты",
        # Свёрнут: в предзаказе бывает три десятка предложений, и развёрнутыми
        # они отодвигают деньги за нижний край. Открывают их, когда уже решили
        # участвовать и ставят цену.
        collapsed=True,
        table=Table(
            columns=("Место", "Поставщик", "Цена за ед.", "Цена с НДС", "Сумма", "Отметки"),
            rows=rows,
            aligns=("left", "left", "right", "right", "right", "left"),
        ),
        note=note,
    )


def _before_submit(notes: Any) -> Section:
    if not notes:
        return Section(title="Перед подачей", empty="Ничего настораживающего не видно.")
    return Section(
        title="Перед подачей",
        fields=tuple(Field(label="", text=note.text, tone=note.tone) for note in notes),
    )


def _verdict_text(analysis: Any) -> str:
    if analysis is None:
        return "не оценивалось"
    from omarket.domain.enums import Verdict
    from omarket.export.reports import verdict_text

    return str(verdict_text(Verdict(analysis.verdict)))


def _margin_tone(analysis: Any) -> str:
    if analysis is None or analysis.margin_ratio is None:
        return ""
    return "good" if analysis.margin_ratio > 0 else "critical"


def _plain(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f}".replace(",", " ")
