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
import unicodedata
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


def detail(
    item_id: str,
    pick: str = "",
    *,
    members: frozenset[tuple[str, str]] | None = None,
    money: bool = True,
) -> Any:
    """Разбор одной строки отбора. `None` — такой строки нет.

    `pick` — находка, по которой считать себестоимость вместо выбранной по
    умолчанию. Ядро берёт самую дешёвую из подходящих, и это правильное
    умолчание, но не всегда правильный ответ: поставщик может быть незнакомым,
    срок неподъёмным, а «подходит» — суждением модели, с которым тендерщик не
    согласен. Тогда он выбирает сам и сразу видит, во что это обходится.

    Вместе с разбором собирается лот. `members` — состав, утверждённый
    человеком; пусто — лота ещё нет, и вместо него показываются остальные
    позиции той же папки. Показываются всегда, а не только после объединения:
    заработок по одной позиции ничего не значит, пока не видно остальных,
    которые придётся поставить вместе с ней.
    """
    from platform_api.modules.tender.detail import build_detail
    from platform_api.modules.tender.lots import collect

    rows = _ranked()
    found = next((item for item in rows if row_id(item) == item_id), None)
    if found is None:
        return None
    # `replace`, а не присваивание: разбор неизменяем, и это правильно —
    # его собирают один раз и раздают.
    from dataclasses import replace

    return replace(
        build_detail(found, pick),
        lot=collect(rows, found, members=members, money=money),
    )


def position_of(item_id: str) -> tuple[str, str] | None:
    """Позиция строки: папка и название. `None` — строки нет.

    Ими лот и хранится. Идентификатор строки для этого не годится: он
    считается от них же и меняется с каждым новым разбором — лот распался бы
    на пустые ссылки после первого же прогона ядра.
    """
    found = next((item for item in _ranked() if row_id(item) == item_id), None)
    return None if found is None else (found.row.folder_path or "", found.row.title)


def titles_in(folder: str) -> tuple[str, ...]:
    """Названия позиций этой папки — то, что разбор предлагает как лот."""
    return tuple(item.row.title for item in _ranked() if (item.row.folder_path or "") == folder)


def recalculate(row: Any, pick: str) -> Any:
    """Себестоимость по выбранной находке — считает ядро, не платформа.

    `None`, когда выбирать не из чего или выбор не найден: тогда разбор
    показывает то, что посчитано по умолчанию.

    Находки берутся те же, по которым ядро посчитало эту строку, и это
    главное здесь. Строка отбора — это позиция, а находки в базе лежат на всю
    закупку: их там бывает три десятка на сорок две позиции. Пока расчёт шёл
    по всему набору, себестоимость антенны за двести тысяч выходила в
    девяносто семь миллионов — в неё складывались 3D-сканер, каски и
    внедорожник из той же папки.

    Сужает набор и делит бюджет по позициям само ядро: `findings_for` и
    `row.positions` — то же, чем оно строило строку. Свой отбор находок здесь
    разошёлся бы с книгой на первой же закупке.
    """
    from tender_analyze.application.sheet_builder import cost_basis, default_choice

    saved = case_sourcing(row.folder_path or "")
    if saved is None:
        return None
    sourcing, whole = saved
    if not sourcing.opportunities:
        return None

    found, positions = _for_row(row, sourcing, whole)
    if not found.opportunities:
        return None

    chosen = default_choice(found.opportunities, positions)
    picked = next(
        (item for item in found.opportunities if finding_key(item) == pick),
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


def _for_row(row: Any, sourcing: Any, whole: int) -> tuple[Any, int]:
    """Находки этой строки и число позиций, между которыми делится бюджет.

    У строки-позиции — только её находки и единица; у закупки целиком — весь
    набор и число её позиций. Что есть что, говорит само ядро полем
    `position_name`: по числу позиций этого не понять, единица бывает и у
    закупки из одной позиции, а находки у неё не сужаются.

    Ядро старее платформы — считаем по всей закупке, как было. Хуже, чем
    правильный ответ, но лучше пустого разбора: репозитории выкатываются
    порознь, и расходиться они будут ещё не раз.
    """
    from tender_analyze.application.sheet_builder import findings_for

    name = getattr(row, "position_name", "")
    if not name:
        return sourcing, whole or 1
    # Цена заказчика за единицу: по ней ядро отсеивает находки, которые
    # дешевле требуемого в разы, — это не другая модель, а другой класс
    # товара.
    budget = row.total / row.quantity if row.total and row.quantity else None
    return findings_for(sourcing, name, budget), 1


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


def mark_cell(title: str, item: RankedRow) -> str:
    """Отметка на отдельной ячейке строки.

    Пока это одна ячейка — код ЕНС из перечня отечественных товаров. Красится
    он сам, а не строка целиком: заливка строки занята вердиктом, и два смысла
    в один цвет не вложить. Зато красный код замечают — он стоит первой
    колонкой, и его видно, не читая остального.
    """
    return "critical" if title == "ЕНС ТРУ" and is_domestic(item.row) else ""


def is_domestic(row: Any) -> bool:
    """Есть ли по коду ЕНС отечественный производитель.

    Перечень читает ядро — приказ Минпрома, три с половиной тысячи кодов в
    файле Word. Разбирать его здесь значило бы завести второй список, который
    разойдётся с первым в день, когда министерство пришлёт обновление.

    Ядро старее платформы — значит, пометок не будет. Не ошибка: перечень и
    сам по себе необязателен, а раздел, отвечающий «данные недоступны» из-за
    отсутствующей подсказки, хуже раздела без подсказки. Репозитории у
    платформы и ядра разные и выкатываются порознь — разойтись они будут ещё
    не раз.
    """
    from platform_api.modules.tender.core import core_settings

    code = (row.ens_code or "").strip()
    if not code:
        return False
    return code in getattr(core_settings(), "domestic", frozenset())


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

    shared: bool = False
    """Файл лежит в папке, но ни к одной её позиции не привязан.

    Справка о регистрации и договор относятся к закупке целиком, и прятать их
    от строки нельзя. Но и выдавать за документ этой позиции тоже: тендерщик
    откроет его в поисках требований и не найдёт.
    """

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


def case_files(item_id: str) -> tuple[CaseFile, ...]:
    """Документы строки: её МЗ, ТЗ и КП плюс общие бумаги папки.

    Ключ — строка, а не папка. В папке лежат бумаги нескольких потребностей, и
    строка в отборе своя у каждой позиции; на общем ключе все они показывали
    бы одно и то же.

    Собираются попутно со строками — те же документы, из которых закупка и
    построена, — поэтому отдельного обращения к базе не стоят.
    """
    _ranked()
    files: dict[str, tuple[CaseFile, ...]] = _CACHE["files"]
    return files.get(item_id, ())


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
    file = next((item for item in case_files(item_id) if item.sha256 == sha256), None)
    if file is None or not _inside(file.path, where):
        return None
    return file


def _inside(path: Path, folder: str) -> bool:
    """Лежит ли файл в папке своей закупки."""
    if not folder:
        return False
    try:
        inside = Path(_same(str(path.resolve())))
        inside.relative_to(Path(_same(str(Path(folder).resolve()))))
    except (OSError, ValueError):
        return False
    return True


def _same(text: str) -> str:
    """Имя в едином написании — чтобы сравнение не зависело от формы записи.

    Проверку это не ослабляет: приведение однозначно и применяется к обеим
    сторонам, а выйти за папку по-прежнему нечем — ни «..», ни ссылка формой
    записи не притворяются.
    """
    return unicodedata.normalize("NFC", text)


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
    # Каталоги перечитываются заново: сборка идёт, когда в базе что-то
    # изменилось, а вместе с ней меняется обычно и содержимое папок.
    _LISTINGS.clear()

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
                        _attach_files(files, built, case)
                        if sourcing:
                            # Позиции считает ядро. Своя такая же функция
                            # сосчитала бы по названиям находок — а модель
                            # называет один и тот же насос двумя способами, и
                            # себестоимость сложилась бы дважды.
                            sourcings[where] = (sourcing[0], positions_in(decided))
    finally:
        container.dispose()

    return rank(rows, min_margin=settings.offer.target_margin_percent)


def _on_disk(path: Path) -> Path:
    """Путь к файлу так, как его имя записано на диске.

    Одну и ту же русскую букву Unicode позволяет записать двумя способами:
    «й» целиком или «и» со значком краткости. macOS ищет файл нечувствительно
    к этой разнице, ext4 сравнивает байты — и разобранная у тендерщика папка
    на сервере не находится при верном на вид пути.

    Разойтись может любое колено, и в базе одна и та же папка встречается в
    обеих формах: её переписывали разные прогоны. Поэтому чинится не диск, а
    поиск — колено за коленом, и оба написания ведут к одному файлу. Обратное
    невозможно: как папку ни переименуй, вторая половина путей перестанет
    сходиться.

    Путь без расхождений возвращается сразу, не читая ни одного каталога.
    """
    if _reachable(path):
        return path
    here = Path(path.anchor)
    for part in path.parts[1:]:
        step = here / part
        if not _reachable(step):
            found = _listing(here).get(unicodedata.normalize("NFC", part))
            if found is None:
                return path
            step = here / found
        here = step
    return here


def _reachable(path: Path) -> bool:
    """Есть ли что-то по этому пути. Нет прав или имя не по силам — считаем нет."""
    try:
        return path.exists()
    except OSError:
        return False


def _listing(folder: Path) -> dict[str, str]:
    """Содержимое каталога по приведённым именам.

    Запоминается на прогон сборки: в папке закупки три десятка документов, и
    без этого каталог перечитывался бы для каждого из них.
    """
    key = str(folder)
    known = _LISTINGS.get(key)
    if known is None:
        try:
            known = {
                unicodedata.normalize("NFC", item.name): item.name for item in folder.iterdir()
            }
        except OSError:
            known = {}
        _LISTINGS[key] = known
    return known


_LISTINGS: dict[str, dict[str, str]] = {}
"""Прочитанные каталоги. Живёт от сборки до сборки — как и всё остальное в
кэше: пересобирается отбор только когда в базе ядра что-то изменилось."""


def _attach_files(files: dict[str, tuple[CaseFile, ...]], rows: Sequence[Any], case: Any) -> None:
    """Раскладывает документы папки по строкам закупки.

    Папка — граница закупки, но не границы потребности: в ней лежат пять
    служебных записок на пять разных нужд, и строка в отборе своя у каждой
    позиции. Пока файлы висели на папке, все пять строк показывали все пять
    записок — человек открывал документ, читал про чужие насосы и переставал
    верить разбору.

    Кто о чём говорит, знает ядро: позиции оно взяло из документов заказчика
    (`row.sources`), а предложения свело по позициям (`row.quotes`). Здесь
    только раскладка, без своего сопоставления имён — второе такое разошлось
    бы с книгой на первой же закупке.

    Документ, не привязанный ни к одной позиции, — справка, договор, письмо —
    достаётся всем строкам с пометкой: он и правда про закупку целиком.
    """
    from dataclasses import replace

    everything = _case_files(case)
    if len(rows) < 2:
        # Одна строка на папку — делить не с кем, и всё в ней её собственное.
        files[row_id_of_folder(rows[0])] = everything
        return

    if not all(hasattr(row, "sources") for row in rows):
        # Ядро старее платформы: связи «позиция — документ заказчика» в строке
        # ещё нет. Раскладывать по одним предложениям нельзя — строка осталась
        # бы без своего ТЗ, — поэтому возвращаемся к прежнему поведению и
        # честно называем всё общим. Пустой раздел был бы хуже: разбор без
        # документов не сделаешь, а разошедшиеся версии — обычное дело, репозитории
        # у платформы и ядра разные и выкатываются порознь.
        from dataclasses import replace as _replace

        shared = tuple(_replace(item, shared=True) for item in everything)
        for row in rows:
            files[row_id_of_folder(row)] = shared
        return

    # Один проход: у каждой строки свои имена, объединение — то, что вообще
    # к чему-то привязано.
    own: dict[str, set[str]] = {}
    claimed: set[str] = set()
    for row in rows:
        names = {*row.sources, *(document for _supplier, document, *_rest in row.quotes)}
        own[row_id_of_folder(row)] = names
        claimed |= names

    common = tuple(replace(item, shared=True) for item in everything if item.name not in claimed)
    for key, names in own.items():
        files[key] = tuple(item for item in everything if item.name in names) + common


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
                path=_on_disk(source.path),
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
