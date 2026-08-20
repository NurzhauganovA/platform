"""Единственная точка, где платформа обращается к ядру SKStore.

Всё остальное в модуле ходит через неё. Смысл в том, чтобы связь с чужим
пакетом была видна целиком в одном файле: когда ядро изменит имя класса или
сигнатуру, это выяснится здесь, а не россыпью по обработчикам запросов.

Ядро настраивается своим `.env` с префиксом `SKSTORE__` и своей базой — оно
самостоятельный проект, а не часть платформы. Платформа его настройки не
подменяет и не пересказывает.

**Чтение не стоит денег.** Открытая страница пересобирает вердикты из того,
что уже лежит в базе: сохранённых совпадений с Marten, находок на рынке и
ответов модели. Ни одного обращения наружу при этом не происходит — иначе
обновление страницы списывало бы деньги, а F5 в отделе нажимают часто.
Платные шаги живут в задачах и запускаются кнопкой.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from platform_api.modules.detail import (
    Detail,
    Section,
    date_field,
    money_field,
    percent_field,
    text_field,
)
from platform_api.modules.table import Visibility, is_past, to_utc

if TYPE_CHECKING:
    from skstore.config import Settings
    from skstore.domain.models import BargainAnalysis

    from platform_api.modules.table import Column


@lru_cache(maxsize=1)
def core_settings() -> Settings:
    """Настройки ядра SKStore."""
    from skstore.config import get_settings

    return get_settings()


def focus_columns() -> Sequence[Column]:
    """Колонки рабочего списка — те же, что в листе «Открытые торги (фокус)».

    Берутся из самого проекта, а не описываются здесь заново: человек смотрит
    на экран и в выгруженный файл, и колонки в них обязаны совпадать.
    """
    from skstore.export.reports import FOCUS_COLUMNS

    return FOCUS_COLUMNS


def sheet_title() -> str:
    """Как называется этот лист в книге. Показывается над таблицей, чтобы
    человек знал, с чем сверяться в файле."""
    from skstore.export.reports import SHEET_TITLES

    return str(SHEET_TITLES["focus"])


@dataclass(frozen=True, slots=True)
class Worklist:
    """Что показывать в рабочем списке."""

    rows: tuple[BargainAnalysis, ...]
    total: int
    """Сколько активных закупов всего — до отбора по вердикту."""

    expired: int
    """Сколько закупов с истёкшим приёмом. Из базы они не удаляются — это
    история, по ней считают динамику цен, — но в рабочем списке их нет."""

    verdicts: dict[str, int]
    margin_total: Decimal | None
    """Сколько можно заработать по всем окупающимся строкам."""

    focused: int
    """Сколько строк попадает в отбор — с чем действительно можно работать."""

    priced: int
    """По скольким закупам себестоимость вообще известна. Остальные — это не
    «невыгодно», а «не с чем сравнивать», и путать их нельзя."""


def is_ours(row: Any) -> bool:
    """Участвуем ли мы в этом закупе.

    Кабинет по активным закупам сообщает только победу: признака «заявка
    подана» в его ответе нет. Если он появится, добавлять его надо в маппер
    skstore, а не гадать здесь по сырому ответу.
    """
    return bool(row.bargain.is_winner)


def is_expired(row: Any) -> bool:
    """Приём закончился, и мы в этом закупе не участвуем.

    Своё не прячем, даже когда срок вышел: по нему ждут результата, и убрать
    его с глаз значит потерять то, за чем следят.
    """
    return is_past(row.bargain.deadline_at) and not is_ours(row)


def in_focus(row: Any) -> bool:
    """Есть ли с закупом что делать: выгодный, пограничный или неразобранный.

    Тот же отбор, что на листе «Открытые торги (фокус)», плюс срок. Закуп с
    истёкшим приёмом остаётся в базе — это история, по ней считают динамику
    цен, — но в рабочем списке ему не место: сделать с ним уже нечего, а верх
    списка он занимает. По кнопке «Все строки» он возвращается.
    """
    from skstore.export.reports import is_focus_analysis

    return bool(is_focus_analysis(row)) and not is_expired(row)


def _analyze(only: str | None = None) -> list[Any]:
    """Прогон ядра без обращений к сети и без списаний.

    `only` сужает его до одного закупа. Разбор открывают десятки раз подряд, и
    пересчитывать ради каждого открытия шестьсот строк — это две секунды
    ожидания там, где хватает сотой доли.
    """
    from skstore.application.analysis import AnalysisService
    from skstore.domain.enums import BargainStatus

    container = _container()
    try:
        with container.unit_of_work() as uow:
            return list(
                AnalysisService(container).analyze_within(
                    uow,
                    BargainStatus.ACTIVE,
                    enrich_marten=False,
                    enrich_llm=False,
                    search_market=False,
                    platform_ids=None if only is None else {only},
                )
            )
    finally:
        container.dispose()


def worklist() -> Worklist:
    """Рабочий список закупов — без обращений к сети и без списаний.

    Вердикты пересчитываются по сохранённым данным: так список остаётся живым
    (изменили порог маржи — увидели новый отбор), но бесплатным.

    Транзакция намеренно не фиксируется. Пересчёт по дороге обновляет кэш
    ядра, и в задаче это правильно, а в открытой странице — нет: чтение не
    должно писать в чужую базу.

    Отдаются все закупы, а не только отобранные: отбор делает браузер по
    признаку строки, и переключение «Только нужное / Все» получается
    мгновенным вместо второго прогона на полсекунды.

    Порядок — по появлению на площадке, свежие сверху. Ядро отдаёт их по
    выгоде, и для книги это правильно: её открывают, чтобы выбрать лучшее из
    всего. Экран работает иначе — на него смотрят после «Обновить», и вопрос
    там один: что появилось с прошлого раза. В порядке по выгоде новый закуп
    оказывается посередине шестисот строк, и человек решает, что выгрузка его
    не забрала. По марже список сортируется щелчком по колонке.
    """
    everything = _newest_first(_analyze())
    # Счётчики считаются по действующим, а не по всему, что лежит в базе.
    # «Всего закупов 599» при пятистах истёкших — это неправда о том, сколько
    # работы на самом деле.
    live = [item for item in everything if not is_expired(item)]
    return Worklist(
        rows=tuple(everything),
        total=len(live),
        expired=len(everything) - len(live),
        verdicts=_verdicts(live),
        margin_total=_margin_total(live),
        focused=sum(1 for item in everything if in_focus(item)),
        priced=sum(1 for item in live if item.cost is not None),
    )


def _newest_first(rows: list[Any]) -> list[Any]:
    """Свежие сверху, а без даты — вниз.

    Дата у закупа своя, площадки: не когда мы его выгрузили, а когда он на ней
    появился. По времени выгрузки все закупы одного прогона были бы
    одинаковыми, и порядок внутри него определяла бы очередь страниц.
    """
    oldest = datetime.min.replace(tzinfo=UTC)
    return sorted(
        rows,
        # Номер закупа вторым ключом: две публикации в одну секунду бывают, а
        # список, который переставляется между двумя открытиями страницы,
        # выглядит сломанным.
        key=lambda item: (to_utc(item.bargain.published_at) or oldest, item.bargain.platform_id),
        reverse=True,
    )


def export_workbook() -> Path:
    """Собирает книгу Excel — ту же, что делает `skstore export`.

    Без обогащения, и это существенно: по умолчанию ядро собирает книгу вместе
    с прогоном — ходит на склад и спрашивает модель. Для команды в терминале
    так и задумано, а здесь книгу заказывают кнопкой и ждут файл. Скачивание
    отчёта не должно ни списывать со счёта, ни идти минутами; за свежие числа
    отвечает «Пересчитать». Заодно книга совпадает с тем, что на экране, —
    оба собраны из одних и тех же сохранённых данных.

    Каталог площадки в неё не идёт: он самый тяжёлый лист, а человек, нажавший
    «Выгрузить», ждёт свои закупы, а не двести тридцать тысяч чужих карточек.
    """
    from skstore.application.export import ExportService

    container = _container()
    try:
        return ExportService(container).export_workbook(include_catalog=False, enrich=False)
    finally:
        container.dispose()


def readiness() -> dict[str, Any]:
    """Что настроено, а что нет. Спрашивается до запуска платного прогона."""
    settings = core_settings()
    problems: list[str] = []

    bargains = _count_bargains()
    if bargains is None:
        problems.append("База SKStore недоступна — выполните `skstore init-db`")
    elif bargains == 0:
        problems.append("В базе нет закупов — нажмите «Обновить данные»")

    if not settings.cabinet.is_configured:
        problems.append("Не задан вход в кабинет: SKSTORE__CABINET__LOGIN и PASSWORD")
    if not settings.gemini.is_configured:
        problems.append("Не задан GEMINI_API_KEY — себестоимость будет только по складу Marten")
    if not settings.ourstore.is_configured:
        problems.append("Не задан склад Marten: SKSTORE__OURSTORE__EMAIL и PASSWORD")

    # Файловая база — для платформы неисправность, а не выбор. К ней
    # одновременно ходят почасовые прогоны и открытые страницы, а пишущий в
    # SQLite блокирует файл целиком. Молчать об этом нельзя: сломается оно не
    # сразу, а в первый час, когда работают все.
    if settings.db.is_sqlite:
        problems.append(
            "Ядро работает с файлом SQLite, а не с общей базой — задайте SKSTORE__DB__URL"
        )

    return {
        "ok": not problems,
        "core_version": core_version(),
        "database": _database(settings),
        "bargains": bargains or 0,
        "market_search": settings.sourcing.enabled and settings.gemini.is_configured,
        "market_model": settings.sourcing.model,
        "warehouse": settings.ourstore.is_configured,
        "problems": tuple(problems),
    }


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
    from skstore.domain.enums import Verdict
    from skstore.export.reports import verdict_label

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
        seen.append((tone, verdict_label(verdict), hints[tone]))
    return tuple(seen)


def tone_of(row: Any) -> str:
    """Подсветка строки по её вердикту."""
    verdict = _verdict_of(row)
    return _TONES.get(verdict, "")


def _verdict_of(row: Any) -> str:
    return str(row.verdict.value)


def row_id(row: Any) -> str:
    """Чем открыть разбор этой строки."""
    return str(row.bargain.platform_id)


def row_deadline(row: Any) -> str | None:
    """Когда закрывается приём предложений."""
    value = to_utc(row.bargain.deadline_at)
    return value.isoformat() if value is not None else None


def core_version() -> str:
    """Версия подключённого ядра — чтобы в сводке было видно, что именно
    работает под платформой."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("skstore-analytics")
    except PackageNotFoundError:  # pragma: no cover — пакет всегда установлен
        return "неизвестна"


# ---------------------------------------------------------------------------


def _container() -> Any:
    from skstore.application.container import Container

    return Container(core_settings())


def _count_bargains() -> int | None:
    """Сколько активных закупов в базе. `None` — базы ещё нет.

    Отсутствие базы не ошибка и не должно превращаться в пятисотый ответ:
    проект только что поставили, и это ровно то, о чём сводка обязана сказать
    человеческими словами.
    """
    from skstore.domain.enums import BargainStatus

    container = _container()
    try:
        with container.unit_of_work() as uow:
            return sum(1 for _ in uow.bargains.iter_by_status(BargainStatus.ACTIVE))
    except Exception:
        return None
    finally:
        container.dispose()


def _verdicts(rows: Sequence[BargainAnalysis]) -> dict[str, int]:
    # Ключ — тон, а не значение перечисления. Счётчиками пользуется браузер, а
    # он думает тонами: ими покрашены строки и по ним же собрана легенда.
    # Отдай сюда `promising`, и в разделе, где вердикты называются иначе,
    # плитка «стоит участвовать» молча показала бы ноль.
    counts: dict[str, int] = {}
    for item in rows:
        tone = tone_of(item)
        counts[tone] = counts.get(tone, 0) + 1
    return counts


def _margin_total(rows: Sequence[BargainAnalysis]) -> Decimal | None:
    """Сумма заработка по строкам, где он положителен.

    Отрицательные не вычитаются: убыточные закупы мы просто не берём, и
    складывать их с прибыльными значило бы показать несуществующий итог.
    """
    values = [item.margin_total for item in rows if item.margin_total and item.margin_total > 0]
    return sum(values, Decimal(0)) if values else None


__all__ = [
    "Worklist",
    "core_settings",
    "core_version",
    "detail",
    "export_workbook",
    "focus_columns",
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
    """Разбор одного закупа. `None` — такого среди активных нет.

    Считается тем же кодом, что и рабочий список, но по одному закупу: закуп
    в разборе и закуп в строке обязаны показывать одно и то же, а второй
    способ его посчитать однажды разошёлся бы с первым.

    Порядок разделов общий с OMarket — решение, деньги, где взять, — чтобы
    человек, который ходит в оба раздела, читал их одинаково.
    """
    found = next(iter(_analyze(only=platform_id)), None)
    if found is None:
        return None

    bargain = found.bargain
    return Detail(
        id=platform_id,
        title=bargain.title or f"Закуп {platform_id}",
        subtitle=bargain.customer_name or bargain.tru_name or "",
        verdict=_verdict_text(found),
        tone=tone_of(found),
        url=_bargain_url(bargain),
        sections=(
            _summary(found),
            _about(bargain),
            _decision(found),
            _money(found),
            _sourcing(found),
            _ai(found),
        ),
    )


def _summary(item: Any) -> Section:
    """Итог одной строкой: участвовать или нет — и что этому мешает.

    Разделов в разборе шесть, и каждый отвечает на свой вопрос: откуда цена,
    где взять, что сказала модель. Вопрос, ради которого разбор открывают,
    остаётся при этом несобранным — человек читает шесть разделов и складывает
    ответ в голове. Складывает по-разному в понедельник и в пятницу.

    Ничего нового здесь не решается: вердикт и его причину посчитало ядро, а
    пороги взяты из его же настроек. Собираются только помехи — то, из-за чего
    цифрам нельзя верить как есть, — и они у закупа обычно не одна.
    """
    verdict = _verdict_of(item)
    blockers = _blockers(item)
    fields = [
        text_field("Участвовать", _ANSWERS.get(verdict, "решать не на чем"), tone=tone_of(item)),
        text_field("Почему", item.reason),
    ]
    fields.extend(text_field(label, text, tone=tone) for label, text, tone in blockers)
    fields.append(text_field("Что дальше", _NEXT_STEP.get(verdict, "")))
    return Section(
        title="Итог",
        fields=tuple(field for field in fields if field is not None),
        note=(
            "Вердикт — подсказка, а не решение: код ТРУ объединяет разные по цене "
            "товары, и читать его надо вместе с тем, что мешает."
            if blockers
            else ""
        ),
        access=Visibility.MONEY,
    )


_ANSWERS = {
    "promising": "да — маржа выше порога",
    "marginal": "на грани — считать по своему складу и объёму",
    "unprofitable": "нет — не окупается",
    "unknown": "решать не на чем: себестоимость неизвестна",
    "blocked": "нет — закуп закрыт для нас",
}
"""Ответ словами на тот вердикт, что поставило ядро. Своего решения здесь
нет: разойдись эти два, и книга с экраном показали бы разное."""

_NEXT_STEP = {
    "promising": "проверить требования и подать",
    "marginal": "сравнить со своим складом: при остатке маржа выше",
    "unprofitable": "пропустить, если не появится своя цена",
    "unknown": "нажать «Пересчитать» — поиск на рынках добудет цену",
    "blocked": "ничего",
}


def _blockers(item: Any) -> list[tuple[str, str, str]]:
    """Что мешает верить цифрам: подпись, текст, тон.

    Каждая помеха — уже посчитанный ядром факт, а не новая оценка. Пороги
    берутся из его настроек: свои числа здесь означали бы, что экран считает
    закуп пограничным, а книга — выгодным.
    """
    settings = core_settings().analysis
    found: list[tuple[str, str, str]] = []

    finding = item.finding
    if finding is not None and not finding.matches_spec:
        found.append(
            ("Товар не тот", f"находка не отвечает требованию: {finding.match_note}", "critical")
        )

    match = item.match
    if match is not None and match.score < Decimal("0.6"):
        found.append(
            (
                "Связка со складом слабая",
                f"совпадение по названию {match.score:.0%} — маржа может быть выдуманной",
                "warning",
            )
        )

    market = item.market
    if market is not None and market.offers < settings.reliable_offers:
        found.append(
            (
                "Мало предложений",
                f"по коду ТРУ их {market.offers}, а надёжной медиану"
                f" делает {settings.reliable_offers}",
                "warning",
            )
        )

    if item.cost is None:
        found.append(("Себестоимости нет", "сравнивать не с чем", "warning"))

    if item.llm is None:
        found.append(("Модель не смотрела", "закуп разобран только по своим данным", "info"))

    hours = _hours_left(item.bargain)
    if hours is not None and hours <= 3:
        found.append(
            (
                "Срок",
                "приём закрывается меньше чем через три часа" if hours > 0 else "приём закрыт",
                "critical",
            )
        )
    return found


def _hours_left(bargain: Any) -> float | None:
    """Сколько часов осталось до конца приёма. `None` — срока нет."""
    deadline = to_utc(bargain.deadline_at)
    if deadline is None:
        return None
    return (deadline - datetime.now(UTC)).total_seconds() / 3600


def _about(bargain: Any) -> Section:
    return Section(
        title="Закуп",
        fields=(
            text_field("Номер", bargain.number),
            text_field("Заказчик", bargain.customer_name),
            text_field("БИН", bargain.customer_bin),
            text_field("Количество", _plain(bargain.quantity)),
            text_field("Единица", bargain.unit),
            text_field("Код ТРУ", bargain.tru_code),
            text_field("Наименование ТРУ", bargain.tru_name),
            text_field("Место поставки", bargain.delivery_place),
            date_field("Приём до", bargain.deadline_at),
        ),
    )


def _decision(item: Any) -> Section:
    return Section(
        title="Решение",
        fields=(
            text_field("Вердикт", _verdict_text(item), tone=tone_of(item)),
            text_field("Почему", item.reason),
        ),
        access=Visibility.MONEY,
    )


def _money(item: Any) -> Section:
    """Откуда взялась маржа. Без разбора цифру невозможно проверить, а
    защищать её перед руководителем всё равно придётся."""
    cost = item.cost
    return Section(
        title="Деньги",
        fields=(
            money_field("Цена торга", item.bargain.unit_price),
            money_field("Цена закупа", cost.purchase_price if cost else None),
            money_field("Себестоимость", cost.unit_cost if cost else None),
            text_field("Расчёт", cost.breakdown if cost else None),
            text_field("Откуда цена", cost.label if cost else None),
            percent_field(
                "Маржа",
                item.margin_ratio,
                tone=_margin_tone(item.margin_ratio),
            ),
            money_field("Заработок всего", item.margin_total),
        ),
        access=Visibility.MONEY,
        empty="" if cost else "Себестоимость не нашлась — сравнивать не с чем.",
    )


def _sourcing(item: Any) -> Section:
    """Где взять товар: находка на рынке, свой склад и цены площадки."""
    from skstore.analysis.sourcing import finding_summary

    fields = []
    finding = item.finding
    if finding is not None:
        fields.extend(
            [
                text_field("Найдено на рынке", finding_summary(finding), link=finding.url),
                text_field("Площадка", f"{finding.marketplace} · {finding.country.value}"),
                text_field("Поставщик", finding.supplier),
                text_field("Товар у поставщика", finding.title),
                text_field("Пересчёт цены", finding.rate_note),
                text_field("Доставка", finding.delivery_note),
                text_field("Минимальная партия", finding.min_order),
                text_field(
                    "Тот ли товар",
                    "да" if finding.matches_spec else f"нет: {finding.match_note}",
                    tone="" if finding.matches_spec else "critical",
                ),
                text_field("Контакт", finding.contact),
            ]
        )

    match = item.match
    if match is not None:
        fields.extend(
            [
                text_field("Marten: позиция", match.title, link=match.url),
                money_field("Marten: склад", match.our_price),
                text_field("Marten: остаток", _plain(match.our_qty)),
                money_field("Marten: поставщик", match.supplier_min_price),
                text_field("Marten: у кого", match.supplier_name),
                percent_field(
                    "Уверенность совпадения",
                    match.score,
                    tone="warning" if match.score < 0.6 else "",
                    note=(
                        "связка строится по названию, а не по жёсткому ключу — "
                        "слабое совпадение даёт красивую, но выдуманную маржу"
                    )
                    if match.score < 0.6
                    else "",
                ),
            ]
        )

    market = item.market
    note = ""
    if market is not None:
        fields.extend(
            [
                money_field("Рынок SKStore: медиана", market.median_price),
                money_field("Рынок SKStore: минимум", market.min_price),
                text_field("Предложений по ТРУ", market.offers),
            ]
        )
        note = (
            "Код ТРУ — категория, а не товар: под одним кодом соседствуют вещи "
            "разного класса, и медиану стоит читать вместе с числом предложений."
        )

    if not fields:
        return Section(
            title="Где взять",
            empty="Ни находки на рынке, ни совпадения с Marten.",
            access=Visibility.SOURCING,
        )
    return Section(
        title="Где взять",
        fields=tuple(fields),
        note=note,
        access=Visibility.SOURCING,
    )


def _ai(item: Any) -> Section:
    llm = item.llm
    if llm is None or not (llm.summary or llm.risks or llm.buy_hint):
        return Section(
            title="Что говорит ИИ",
            empty="Модель по этому закупу не вызывалась.",
            access=Visibility.MONEY,
        )
    return Section(
        title="Что говорит ИИ",
        fields=(
            text_field("Вывод", llm.summary),
            text_field("Главный риск", llm.risks, tone="warning" if llm.risks else ""),
            text_field("Проверить до подачи", llm.buy_hint),
            percent_field("Уверенность", llm.confidence),
        ),
        note="Оценка модели, а не расчёт. Читать вместе с колонкой «Откуда цена».",
        access=Visibility.MONEY,
    )


def _verdict_text(item: Any) -> str:
    from skstore.export.reports import verdict_label

    return str(verdict_label(item.verdict))


def _margin_tone(ratio: Any) -> str:
    if ratio is None:
        return ""
    return "good" if ratio > 0 else "critical"


def _bargain_url(bargain: Any) -> str | None:
    from skstore.export.reports import _bargain_link

    return _bargain_link(bargain)


def _plain(value: Any) -> str:
    """Количество без хвоста нулей: площадка отдаёт «30.000000»."""
    if value is None:
        return "—"
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text
