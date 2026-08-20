"""Отбор закупок: то же, что лист «Отбор» в книге тендерного ядра.

Раньше раздел начинался с загрузки папки: заведи закупку, выбери каталог,
дождись разбора. Но разбор к этому моменту уже сделан — тендерщик гоняет
`tender-analyze` у себя, и в базе ядра лежат и документы, и решения по
закупкам, и находки на рынках. Показывать пустой список и просить загрузить
то, что уже разобрано, — значит заставлять делать работу дважды.

Поэтому закупки берутся из базы ядра. Каталоги на диске для этого не нужны:
корни разобранного ядро помнит само (`documents.roots()`), а всё остальное —
паспорта документов, решения, находки — лежит рядом в тех же таблицах.

Считать здесь нечего. Строка собирается тем же `build_rows`, вердикт ставит
тот же `rank`, значения раскладывает тот же `row_values` — то есть ровно то,
из чего пишется книга. Второй способ посчитать заработок разошёлся бы с
первым, и выяснилось бы это на закупке, где ошибка стоит дороже всего.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from platform_api.logging import get_logger

if TYPE_CHECKING:
    from tender_analyze.application.hunt import RankedRow

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Worklist:
    """Что показывать в отборе."""

    rows: tuple[RankedRow, ...]
    total: int
    expired: int
    verdicts: dict[str, int]
    margin_total: Decimal | None
    focused: int
    priced: int
    analyzed: bool


def worklist() -> Worklist:
    """Отбор целиком — без обращений к сети и без списаний.

    Разбор документов и поиск на рынках уже оплачены: здесь только читается
    то, что они оставили в базе.
    """
    ranked = _ranked()
    priced = sum(1 for item in ranked if item.row.cost is not None)
    return Worklist(
        rows=tuple(ranked),
        total=len(ranked),
        # У тендерной закупки нет срока приёма в данных: дата в строке — это
        # дата самой закупки из заключения, а не «до какого числа подать».
        # Прятать по ней нельзя, иначе исчезнет всё, что разобрано в прошлом
        # месяце и до сих пор в работе.
        expired=0,
        verdicts=_verdicts(ranked),
        margin_total=_margin_total(ranked),
        focused=sum(1 for item in ranked if in_focus(item)),
        priced=priced,
        analyzed=bool(ranked),
    )


def detail(item_id: str, pick: str = "") -> Any:
    """Разбор одной строки отбора. `None` — такой строки нет.

    `pick` — находка, по которой считать себестоимость вместо выбранной по
    умолчанию. Ядро берёт самую дешёвую из подходящих, и это правильное
    умолчание, но не всегда правильный ответ: поставщик может быть незнакомым,
    срок неподъёмным, а «подходит» — суждением модели, с которым тендерщик не
    согласен. Тогда он выбирает сам и сразу видит, во что это обходится.
    """
    from platform_api.modules.tender.detail import build_detail

    found = next((item for item in _ranked() if row_id(item) == item_id), None)
    return None if found is None else build_detail(found, pick)


def recalculate(row: Any, pick: str) -> Any:
    """Себестоимость по выбранной находке — считает ядро, не платформа.

    `None`, когда выбирать не из чего или выбор не найден: тогда разбор
    показывает то, что посчитано по умолчанию.

    Возвращает сумму, расшифровку построчно и ключ выбранной находки — тем же
    кодом, которым книга считает свою. Свой расчёт здесь разошёлся бы с
    книгой на первой же закупке, и выяснилось бы это при сверке.
    """
    from tender_analyze.application.sheet_builder import cost_basis, default_choice

    saved = case_sourcing(row.folder_path or "")
    if saved is None:
        return None
    sourcing, positions = saved
    if not sourcing.opportunities:
        return None

    chosen = default_choice(sourcing.opportunities, positions)
    picked = next(
        (item for item in sourcing.opportunities if finding_key(item) == pick),
        None,
    )
    if picked is not None:
        # Заменяем находку только по её позиции: остальные позиции комплекта
        # остаются на своём выборе, иначе один щелчок обнулял бы весь расчёт.
        chosen = {**chosen, picked.position: picked}
        if positions == 1:
            chosen = {picked.position: picked}

    total, lines = cost_basis(chosen, row.quantity, positions)
    return total, lines, {finding_key(item) for item in chosen.values()}


def finding_key(item: Any) -> str:
    """Устойчивое имя находки.

    Не номер в списке: список пересобирается вместе с отбором, и ссылка на
    «третью строку» после нового поиска показала бы чужого поставщика.
    """
    finding = item.finding
    raw = f"{item.position}|{finding.marketplace}|{finding.supplier or ''}|{finding.price_kzt}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def export_workbook() -> Path:
    """Книга отбора — та же, что пишет `tender-analyze hunt`.

    Пишется тем же `write_ranked` и из тех же строк, что показаны на экране:
    своя сборка книги разошлась бы с книгой ядра на первой же новой колонке, а
    заметил бы это тот, кто открыл файл и не нашёл в нём того, что видел.

    Файл кладётся во временный каталог: он нужен ровно на время скачивания, а
    складывать выгрузки рядом с базой значит однажды забить диск книгами,
    которые никто не откроет второй раз.
    """
    import tempfile

    from tender_analyze.export.ranked import write_ranked

    target = Path(tempfile.mkdtemp(prefix="otbor-")) / "Отбор закупок.xlsx"
    return write_ranked(_ranked(), target)


def columns() -> Sequence[Any]:
    """Колонки листа «Отбор» — заголовки, ширины и форматы из книги."""
    from platform_api.modules.tender.columns import ranked_columns

    return ranked_columns()


def sheet_title() -> str:
    return "Отбор"


def row_id(item: RankedRow) -> str:
    """Устойчивое имя строки.

    Не номер: он съезжает от каждой пересортировки и от нового разбора, а
    ссылку на разбор пересылают коллеге. Не путь к папке: строк на папку
    несколько — по одной на позицию. Берём то, что строку и определяет:
    папка, название позиции и код ЕНС.
    """
    return row_id_of_folder(item.row)


def row_id_of_folder(row: Any) -> str:
    """То же имя строки, но по самой строке, а не по оценённой закупке.

    Нужно разбору: он собирает ссылки на файлы, а вердикт для этого ни при
    чём. Считается тем же способом — иначе ссылка вела бы в никуда.
    """
    key = f"{row.folder_path}|{row.title}|{row.ens_code}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def in_focus(item: RankedRow) -> bool:
    """Есть ли с закупкой что делать.

    «Мимо» и «Нет данных» прячутся: по первым решение принято, по вторым
    решать не на чем, а верх списка они занимают. По кнопке «Все строки»
    возвращаются — иногда надо посмотреть, почему закупка отсеялась.
    """
    return item.verdict.label not in {"Мимо", "Нет данных"}


_VERDICTS: tuple[tuple[str, str, str], ...] = (
    ("Брать", "good", "маржа выше порога, требования выполнимы"),
    ("Смотреть", "warning", "маржа на грани — стоит разобраться"),
    ("Проверить", "warning", "числа заказчика не сошлись, марже верить нельзя"),
    ("Считать вручную", "info", "рынок не дал ставок: считать от людей и техники"),
    ("Нет данных", "", "себестоимость не считали — сравнивать не с чем"),
    ("Мимо", "critical", "не проходим по требованиям или невыгодно"),
)
"""Вердикты ядра, их цвет и что каждый значит.

Цвета те же, что заливают строки в книге отбора: строку читают боковым зрением
при прокрутке трёхсот закупок, и цвет — единственное, что на такой скорости
различимо. Слово при этом стоит рядом всегда.

Список один на цвет строки и на легенду. Держи их порознь — и однажды в
легенде останется вердикт, который ядро больше не выставляет, либо появится
цвет, которому в ней нет объяснения.

«Смотреть» и «Проверить» делят жёлтый намеренно: действие по ним одно —
посмотреть внимательнее, — а чем именно закупка подозрительна, написано в
разборе. Пятого цвета в палитре нет, и вводить его ради оттенка одного и того
же действия значит сделать таблицу нечитаемой боковым зрением.
"""

_TONES = {label: tone for label, tone, _ in _VERDICTS}


def tone_of(item: RankedRow) -> str:
    label = item.verdict.label
    if label not in _TONES:
        # Ядро завело новый вердикт, а здесь о нём не знают. Серая строка без
        # объяснения — не худший исход, но знать об этом надо: цвет у неё
        # пропадёт, и в легенде её не будет.
        logger.warning("Незнакомый вердикт ядра", label=label)
    return _TONES.get(label, "")


def row_deadline(_item: RankedRow) -> str | None:
    """Срока приёма у тендерной закупки в данных нет: дата в строке — это дата
    закупки из заключения, а не «до какого числа подать»."""
    return None


def legend() -> tuple[tuple[str, str, str], ...]:
    """Что означает цвет строки: тон, слово и пояснение.

    Собирается из тех же вердиктов, которыми красятся строки. Два вердикта на
    один цвет сходятся в одну запись: по цвету в браузере идёт и отбор, и
    два одинаково-жёлтых значка человек нажимал бы наугад.
    """
    order: list[str] = []
    labels: dict[str, list[str]] = {}
    hints: dict[str, list[str]] = {}
    for label, tone, hint in _VERDICTS:
        if tone not in labels:
            order.append(tone)
            labels[tone], hints[tone] = [], []
        labels[tone].append(label)
        hints[tone].append(hint)
    return tuple((tone, " / ".join(labels[tone]), "; ".join(hints[tone])) for tone in order)


# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CaseFile:
    """Файл закупки — то, что лежит в её папке у тендерщика.

    Путь абсолютный и держится здесь, а не уходит наружу: по нему платформа
    отдаёт содержимое, а знать, где на чужой машине лежит архив, браузеру
    незачем.
    """

    sha256: str
    name: str
    kind: str
    size_bytes: int
    path: Path

    @property
    def available(self) -> bool:
        """Дотягивается ли платформа до файла.

        Архив лежит на машине тендерщика, и в контейнер он попадает томом.
        Не подключили — список файлов всё равно виден: знать, что в папке есть
        ТЗ, полезно и без возможности его открыть.
        """
        try:
            return self.path.is_file()
        except OSError:  # pragma: no cover — путь с недопустимыми знаками
            return False


_CACHE: dict[str, Any] = {"stamp": None, "rows": (), "files": {}, "found": {}}
"""Собранный отбор и отпечаток базы, по которому он собран.

Сборка идёт девять секунд: сто двадцать три корня, из каждого строится
закупка. Для одного открытия страницы это терпимо, но разбор строки считается
из того же прогона, и открывать его по девять секунд нельзя — за час их
открывают десятки раз.

Кэш сбрасывается не по времени, а по содержимому базы. Срок жизни здесь был бы
хуже обоих вариантов: короткий не спасает, длинный показывает вчерашние числа
после того, как тендерщик прогнал разбор у себя.
"""


def _stamp() -> str:
    """Отпечаток базы ядра: изменился — пересобираем.

    Считается по тому, что влияет на отбор: сколько документов разобрано и
    что лежит в решениях и находках. Отпечатки закупок берутся вместе с
    размером ответа — сам по себе отпечаток не меняется, когда поиск
    перезапускают принудительно по той же закупке.
    """
    from sqlalchemy import text
    from tender_analyze.application.container import Container

    from platform_api.modules.tender.core import core_settings

    container = Container(core_settings())
    try:
        with container.engine.connect() as connection:
            row = connection.execute(
                text(
                    "select"
                    " (select count(*) from analyses),"
                    " (select coalesce(max(created_at)::text, '') from analyses),"
                    " (select coalesce(md5(string_agg("
                    "     fingerprint || length(payload::text)::text, ',' order by id)), '')"
                    "  from case_analyses),"
                    " (select coalesce(md5(string_agg("
                    "     fingerprint || length(payload::text)::text, ',' order by id)), '')"
                    "  from sourcing_results)"
                )
            ).one()
        return "|".join(str(value) for value in row)
    finally:
        container.dispose()


_REBUILD = threading.Lock()
"""Пересобирает отбор кто-то один.

Без замка утро выглядит так: тендерщик прогнал разборы, отдел открывает
раздел, и десять запросов одновременно не находят кэша. Каждый честно
пересобирает те же двести шестьдесят пять строк — десять раз по шесть секунд
процессора вместо одного. Соседние разделы при этом ждут: работа занимает
процессор целиком, а он в контейнере один.

Замок делает из десяти пересборок одну: первый строит, остальные ждут его и
забирают готовое.
"""


def _ranked() -> list[RankedRow]:
    """Отбор из базы ядра, собранный один раз на состояние базы."""
    try:
        stamp = _stamp()
    except Exception as exc:  # pragma: no cover — база ядра недоступна
        logger.warning("Отпечаток базы не посчитался", error=str(exc))
        stamp = None

    if stamp is not None and _CACHE["stamp"] == stamp:
        return list(_CACHE["rows"])

    with _REBUILD:
        # Пока ждали замок, отбор мог собрать тот, кто зашёл первым.
        if stamp is not None and _CACHE["stamp"] == stamp:
            return list(_CACHE["rows"])

        files: dict[str, tuple[CaseFile, ...]] = {}
        sourcings: dict[str, Any] = {}
        rows = _build(files, sourcings)
        if stamp is not None:
            _CACHE["stamp"] = stamp
            _CACHE["rows"], _CACHE["files"] = tuple(rows), files
            _CACHE["found"] = sourcings
        return rows


def case_sourcing(folder_path: str) -> Any:
    """Находки по закупке и число её позиций — то, из чего считалась
    себестоимость.

    Нужны, чтобы пересчитать её по другому поставщику: тендерщик смотрит
    список и видит, что дешёвая находка не проходит по требованиям, а
    подходящая дороже. Считать при этом должен код ядра, а не браузер.
    """
    _ranked()
    return _CACHE["found"].get(folder_path)


def case_files(folder_path: str) -> tuple[CaseFile, ...]:
    """Файлы закупки: МЗ, ТЗ, КП и всё, что лежит в её папке.

    Собираются попутно со строками — те же документы, из которых закупка и
    построена, — поэтому отдельного обращения к базе не стоят.
    """
    _ranked()
    files: dict[str, tuple[CaseFile, ...]] = _CACHE["files"]
    return files.get(folder_path, ())


def find_file(item_id: str, sha256: str) -> CaseFile | None:
    """Файл закупки по имени строки. `None` — такой строки или файла нет.

    Поиск идёт в пределах своей закупки, а не по всей базе: путь отсюда
    уходит на чтение с диска, и брать его по одному лишь хэшу значило бы
    позволить прочитать чужую папку, подставив хэш из неё.

    Путь при этом проверяется ещё раз, на принадлежность папке закупки. Он
    приходит не от человека, а из базы ядра, — но между «не может выйти за
    папку» и «проверено, что не вышел» разница в одну строку, а цена ошибки
    здесь чтение произвольного файла с диска.
    """
    found = next((item for item in _ranked() if row_id(item) == item_id), None)
    if found is None:
        return None
    where = found.row.folder_path or ""
    file = next((item for item in case_files(where) if item.sha256 == sha256), None)
    if file is None or not _inside(file.path, where):
        return None
    return file


def _inside(path: Path, folder: str) -> bool:
    """Лежит ли файл в папке своей закупки."""
    if not folder:
        return False
    try:
        path.resolve().relative_to(Path(folder).resolve())
    except (OSError, ValueError):
        return False
    return True


def _build(files: dict[str, tuple[CaseFile, ...]], sourcings: dict[str, Any]) -> list[RankedRow]:
    """Строки отбора из базы ядра.

    Обход идёт по корням, и на каждый корень открывается своя единица работы.
    Это не расточительство: решения и находки ядро ключует парой «корень плюс
    папка», и без корня выборка молча не находит ничего — закупка выходит в
    отбор с пустой себестоимостью, при том что поиск по ней давно оплачен.

    Строки собираются по одной закупке за раз, а не всем списком сразу.
    `build_rows` связывает находки с закупкой по имени папки, а внутри корня
    папка закупки — это «.»; на общем списке ключ совпал бы у всех ста
    двадцати трёх корней, и себестоимость насосов встала бы пожарной машине.
    """
    from tender_analyze.application.case_analysis import case_fingerprint
    from tender_analyze.application.cases import CaseBuilder
    from tender_analyze.application.container import Container
    from tender_analyze.application.hunt import folder_label, rank
    from tender_analyze.application.sheet_builder import build_rows, positions_in
    from tender_analyze.application.sourcing import SourcingResult
    from tender_analyze.domain.models import CaseAnalysis, Opportunity

    from platform_api.modules.tender.core import core_settings

    settings = core_settings()
    container = Container(settings)
    builder = CaseBuilder(settings.analysis)
    model = _case_model(settings)
    vat = settings.analysis.vat_rate
    rows: list[Any] = []

    try:
        with container.unit_of_work() as uow:
            roots = uow.documents.roots()

        for root in roots:
            with container.unit_of_work(root) as uow:
                documents = [
                    item for item in uow.documents.list_analyzed(root) if item.insight is not None
                ]
                if not documents:
                    continue
                for case in builder.build(documents):
                    decided = _with_decision(uow, case, model, case_fingerprint, CaseAnalysis)
                    found = _opportunities(uow, case, case_fingerprint, Opportunity)
                    sourcing = (
                        [SourcingResult(case=decided, report=None, opportunities=found)]
                        if found
                        else []
                    )
                    built = _located(
                        build_rows([decided], sourcing, vat_rate=vat), root, case, folder_label
                    )
                    rows.extend(built)
                    if built:
                        where = built[0].folder_path
                        files[where] = _case_files(case)
                        if sourcing:
                            # Позиции считает ядро. Своя такая же функция
                            # сосчитала бы по названиям находок — а модель
                            # называет один и тот же насос двумя способами, и
                            # себестоимость сложилась бы дважды.
                            sourcings[where] = (sourcing[0], positions_in(decided))
    finally:
        container.dispose()

    return rank(rows, min_margin=settings.offer.target_margin_percent)


def _case_files(case: Any) -> tuple[CaseFile, ...]:
    """Документы закупки в порядке их важности для человека.

    Сначала бумаги заказчика — по ним понимают, что покупают и почём он сам
    это оценил, — потом предложения поставщиков, потом всё остальное. В папке
    бывает три десятка файлов, и справка о регистрации не должна стоять выше
    технического задания.
    """
    seen: set[str] = set()
    items: list[CaseFile] = []
    for document in case.documents:
        source = document.source
        if source.sha256 in seen:
            continue
        seen.add(source.sha256)
        insight = document.insight
        items.append(
            CaseFile(
                sha256=source.sha256,
                name=source.name,
                kind=str(insight.kind) if insight is not None and insight.kind else "",
                size_bytes=source.size_bytes,
                path=source.path,
            )
        )
    items.sort(key=lambda item: (_KIND_ORDER.get(item.kind, len(_KIND_ORDER)), item.name))
    return tuple(items)


_KIND_ORDER = {kind: index for index, kind in enumerate(("ТЗ", "МЗ", "КП", "прайс", "договор"))}
"""Порядок видов документов в разборе. Не алфавитный: алфавит поставил бы
договор перед техническим заданием, а открывают в папке первым именно ТЗ."""


def _located(rows: list[Any], root: Any, case: Any, label: Any) -> list[Any]:
    """Проставляет строкам, где лежит закупка.

    Без этого папка пуста, а по ней в отборе строку и находят: имя закупки
    повторяется («Насосы»), и понять, чьи это насосы, можно только по пути.
    Тот же путь опознаёт строку в ссылке на разбор — на пустом поле строки
    из разных папок слиплись бы в одну.
    """
    folder = (root / case.folder).resolve()
    where = label(folder, root)
    for row in rows:
        row.folder = where
        row.folder_path = str(folder)
    return rows


def _case_model(settings: Any) -> str:
    """Какой моделью считалось решение по закупке.

    Нужно, чтобы найти сохранённый разбор: ядро ключует его именем модели —
    решение от Flash и решение от Pro это разные ответы, и подменять одно
    другим нельзя.
    """
    llm = settings.llm
    return str(llm.gemini.case_model if llm.provider == "gemini" else llm.model)


def _with_decision(uow: Any, case: Any, model: str, fingerprint: Any, analysis_model: Any) -> Any:
    """Подшивает к закупке сохранённое решение модели, если оно есть."""
    try:
        stored = uow.cases.get_case_analysis(case.folder, model, fingerprint(case))
    except Exception:  # pragma: no cover — формат решения изменился
        return case
    if stored is None:
        return case
    payload, _notes = stored
    try:
        return case.model_copy(update={"analysis": analysis_model.model_validate(payload)})
    except Exception:  # pragma: no cover
        logger.warning("Решение по закупке не читается", folder=str(case.folder))
        return case


def _opportunities(
    uow: Any, case: Any, fingerprint: Any, opportunity_model: Any
) -> tuple[Any, ...]:
    """Находки прошлого поиска по этой закупке.

    Без них себестоимость остаётся неизвестной, при том что поиск, возможно,
    уже оплачен.
    """
    from pydantic import ValidationError

    payload = uow.cases.get_opportunities(case.folder, fingerprint(case))
    if not payload:
        return ()
    try:
        return tuple(opportunity_model.model_validate(item) for item in payload)
    except ValidationError:
        logger.warning("Сохранённые находки не читаются", folder=str(case.folder))
        return ()


def _verdicts(ranked: Sequence[RankedRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in ranked:
        tone = tone_of(item)
        counts[tone] = counts.get(tone, 0) + 1
    return counts


def _margin_total(ranked: Sequence[RankedRow]) -> Decimal | None:
    """Сумма заработка по строкам, где он положителен.

    Убыточные не вычитаются: такие закупки мы просто не берём, и складывать
    их с прибыльными значило бы показать несуществующий итог.
    """
    values = [
        item.row.total - item.row.cost
        for item in ranked
        if item.row.total is not None
        and item.row.cost is not None
        and item.row.total > item.row.cost
    ]
    return sum(values, Decimal(0)) if values else None


__all__ = [
    "Worklist",
    "case_files",
    "case_sourcing",
    "columns",
    "detail",
    "export_workbook",
    "find_file",
    "finding_key",
    "in_focus",
    "legend",
    "recalculate",
    "row_deadline",
    "row_id",
    "row_id_of_folder",
    "sheet_title",
    "tone_of",
    "worklist",
]
