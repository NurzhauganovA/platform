"""Эндпоинты тендерного модуля."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from platform_api.auth.dependencies import (
    CurrentUser,
    Db,
    requires_money,
    requires_read,
    requires_sourcing,
)
from platform_api.config import Settings
from platform_api.db.models import StoredFile
from platform_api.jobs import JobService
from platform_api.jobs.worker import enqueue_sync
from platform_api.modules import codes, preview
from platform_api.modules.detail import for_role
from platform_api.modules.schemas import (
    ColumnOut,
    DetailOut,
    LegendItem,
    LotMembersIn,
    LotOut,
    PreviewBlockOut,
    PreviewOut,
    PreviewSheetOut,
    RowLotOut,
    RowOut,
    WorklistOut,
)
from platform_api.modules.table import build_table, sees_money
from platform_api.modules.tender import core, lots, worklist
from platform_api.modules.tender.cases import router as cases_router
from platform_api.modules.tender.columns import (
    CODE_PREFIX,
    COMPACT,
    ESSENTIAL,
    POLICY,
    ROLES,
)
from platform_api.modules.tender.comparison import router as comparison_router
from platform_api.modules.tender.health import check as check_health
from platform_api.modules.tender.schemas import (
    CompanyOut,
    EstimateIn,
    FileLookupOut,
    FileProbe,
    FileVerdict,
    FormatOut,
    ModuleHealth,
    StartedJobOut,
    UploadedFileOut,
    UploadPlan,
)
from platform_api.storage import ChecksumMismatchError, FileStorage, FileTooLargeError

router = APIRouter(prefix="/tender", tags=["Тендеры"])
router.include_router(cases_router)
router.include_router(comparison_router)


@router.get("/health", summary="Готовность модуля к разбору")
def get_health() -> ModuleHealth:
    """Всё ли настроено для платного разбора.

    Спрашивается до загрузки папки: разбор идёт минутами и падает на первом же
    файле, если нет доступа к модели, — а человек к этому моменту уже ждёт.
    """
    return ModuleHealth.model_validate(check_health())


@router.get("/worklist", summary="Отбор закупок")
def get_worklist(
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_read] = None,
) -> WorklistOut:
    """Разобранные закупки так же, как их показывает лист «Отбор».

    Ничего не запускает и не стоит денег: разбор документов, решения модели и
    поиск на рынках тендерщик уже прогнал у себя, а здесь только читается то,
    что они оставили в базе ядра. Иначе обновление страницы списывало бы со
    счёта, а F5 в отделе нажимают часто.

    Колонки, их порядок и значения — из книги того же проекта. Человек сверяет
    экран с выгруженным файлом, и расхождение в них стоит получаса на
    выяснение, кто из двух прав.
    """
    try:
        data = worklist.worklist()
    except Exception as exc:
        # База ядра может быть недоступна или пуста — это не поломка
        # платформы, а состояние, о котором должна сказать сводка готовности.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Данные тендерного разбора недоступны: {exc}",
        ) from exc

    marked = lots.membership(db, identity.organization.id)
    порядок = _grouped(data.rows, marked)
    коды = codes.assign(
        db,
        "tender",
        CODE_PREFIX,
        [worklist.row_id(item) for item in порядок],
    )
    db.commit()

    table = build_table(
        worklist.columns(),
        порядок,
        policy=POLICY,
        role=identity.role,
        tone=worklist.tone_of,
        focus=worklist.in_focus,
        identity=worklist.row_id,
        deadline=worklist.row_deadline,
        mark=worklist.mark_cell,
        essential=ESSENTIAL,
        compact=COMPACT,
        roles=ROLES,
    )
    money = sees_money(identity.role)

    return WorklistOut(
        sheet=worklist.sheet_title(),
        columns=[ColumnOut.model_validate(asdict(item)) for item in table.columns],
        rows=_with_lots(table.rows, порядок, marked, коды, money=money),
        legend=[
            LegendItem(tone=tone, title=title, hint=hint) for tone, title, hint in worklist.legend()
        ],
        # Ни обновления, ни пересчёта: закупки приходят папками с документами,
        # а разбор идёт у тендерщика на машине — там, где эти папки лежат.
        # Книга — единственное, что платформа может отдать сама.
        actions=["export"] if money else [],
        hidden_columns=table.hidden_columns,
        total=data.total,
        shown=data.focused,
        expired=data.expired,
        verdicts=data.verdicts,
        margin_total=(
            float(data.margin_total) if money and data.margin_total is not None else None
        ),
        priced=data.priced,
        analyzed=data.analyzed,
    )


def _grouped(rows: Sequence[Any], marked: dict[tuple[str, str], str]) -> list[Any]:
    """Ставит строки одного лота подряд, на место самой высокой из них.

    Порядок задаёт ядро — по выгоде, — и позиции лота он разбрасывает по всему
    списку: добавленная вручную из чужой папки оказывается через двести строк
    от своих. Связь тогда видна только по значку, а рядом её нет.

    Место лота — там, где стояла его лучшая позиция: лот читают как одну
    строку, и падать вниз из-за слабого участника он не должен. Разъединили —
    порядок ядра вернулся сам, здесь ничего не запоминается.
    """
    свои: dict[str, list[Any]] = {}
    for item in rows:
        имя = marked.get((item.row.folder_path or "", item.row.title))
        if имя is not None:
            свои.setdefault(имя, []).append(item)

    порядок: list[Any] = []
    показанные: set[str] = set()
    for item in rows:
        имя = marked.get((item.row.folder_path or "", item.row.title))
        if имя is None:
            порядок.append(item)
            continue
        if имя in показанные:
            continue
        показанные.add(имя)
        порядок.extend(свои[имя])
    return порядок


def _with_lots(
    rows: Sequence[Any],
    source: Sequence[Any],
    marked: dict[tuple[str, str], str],
    коды: dict[str, str],
    *,
    money: bool,
) -> list[RowOut]:
    """Дописывает строкам отметку лота.

    Отметка не косметическая: у позиции может быть заработок в сорок
    процентов, а у лота, в котором она лежит, — убыток. Видно это должно быть
    в списке, до того как строку откроют, — иначе смысл объединения теряется.

    Считается одним проходом по уже собранному отбору: строк восемьсот, и
    обращение к базе на каждую было бы восемьюстами запросов ради нескольких
    десятков записей.
    """
    итоги: dict[str, tuple[int, Decimal | None, Decimal | None]] = {}
    for item in source:
        имя = marked.get((item.row.folder_path or "", item.row.title))
        if имя is None:
            continue
        было = итоги.get(имя, (0, None, None))
        итоги[имя] = (было[0] + 1, _add(было[1], item.row.total), _add(было[2], item.row.cost))

    готовые: list[RowOut] = []
    for row, item in zip(rows, source, strict=True):
        out = RowOut.model_validate(asdict(row))
        out.code = коды.get(worklist.row_id(item), "")
        имя = marked.get((item.row.folder_path or "", item.row.title))
        итог = итоги.get(имя or "")
        if имя is not None and итог is not None and итог[0] > 1:
            позиций, сумма, себестоимость = итог
            прибыль = (
                сумма - себестоимость
                if money and сумма is not None and себестоимость is not None
                else None
            )
            out.lot = RowLotOut(
                key=имя,
                positions=позиций,
                total=float(сумма) if сумма is not None else None,
                margin_percent=(
                    float((прибыль / сумма * 100).quantize(Decimal("0.1")))
                    if прибыль is not None and сумма
                    else None
                ),
            )
        готовые.append(out)
    return готовые


def _add(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    """Сумма известных значений: ноль и «неизвестно» — разные вещи."""
    if right is None:
        return left
    return right if left is None else left + right


@router.post("/item/{item_id}/lot", summary="Объединить позиции в лот")
def merge_lot(
    item_id: str,
    identity: CurrentUser,
    db: Db,
    body: LotMembersIn | None = None,
    _guard: Annotated[None, requires_read] = None,
) -> LotOut:
    """Собирает лот вокруг этой позиции.

    Без списка — берутся остальные позиции той же папки: разбор их уже связал,
    и в девяти случаях из десяти он прав. Со списком — ровно перечисленные,
    откуда бы они ни были: заказчик раскладывает один лот по двум папкам, и
    никакой признак в документах об этом не говорит.

    Позиция, занятая другим лотом, переезжает в этот. Так и исправляют ошибку:
    увидели, что позиция приписана не туда, и перенесли.

    Доступно всем, кто работает с разделом: это пометка о порядке работы, а не
    деньги.
    """
    anchor = _position_or_404(item_id)
    добавить = (
        [_position_or_404(other) for other in body.positions]
        if body is not None and body.positions
        else _folder_neighbours(anchor)
    )
    if not добавить:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Объединять не с чем: в этой закупке одна позиция",
        )
    lots.gather(db, identity.organization.id, identity.user.id, anchor, добавить)
    db.commit()
    собран = _lot_out(item_id, identity, db)
    if собран is None:  # pragma: no cover — состав только что записан
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Лот собран, но не читается",
        )
    return собран


@router.delete("/item/{item_id}/lot", summary="Разъединить лот")
def split_lot(
    item_id: str,
    identity: CurrentUser,
    db: Db,
    only: str = "",
    _guard: Annotated[None, requires_read] = None,
) -> LotOut | None:
    """Разъединяет лот целиком или убирает из него одну позицию.

    `only` — убрать перечисленную, оставив лот. Так вычёркивают лишнее, не
    пересобирая состав заново.
    """
    _position_or_404(item_id)
    if only:
        lots.detach(db, identity.organization.id, _position_or_404(only))
    else:
        lots.dissolve(db, identity.organization.id, _position_or_404(item_id))
    db.commit()
    return _lot_out(item_id, identity, db, missing_ok=True)


def _position_or_404(item_id: str) -> tuple[str, str]:
    """Позиция строки: папка и название. Ими лот и хранится."""
    found = worklist.position_of(item_id)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Такой закупки нет в отборе",
        )
    return found


def _folder_neighbours(anchor: tuple[str, str]) -> list[tuple[str, str]]:
    """Остальные позиции той же папки — то, что предлагает разбор."""
    folder, title = anchor
    return [(folder, other) for other in worklist.titles_in(folder) if other != title]


def _lot_out(item_id: str, identity: Any, db: Db, *, missing_ok: bool = False) -> LotOut | None:
    found = worklist.detail(
        item_id,
        members=lots.positions_of(db, identity.organization.id, _position_or_404(item_id)),
        money=sees_money(identity.role),
    )
    if found is None or found.lot is None:
        if missing_ok:
            return None
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="В этой закупке одна позиция — объединять нечего",
        )
    return LotOut.model_validate(asdict(found.lot))


@router.get("/item/{item_id}", summary="Разбор одной закупки")
def get_worklist_item(
    item_id: str,
    identity: CurrentUser,
    db: Db,
    pick: str = "",
    _guard: Annotated[None, requires_read] = None,
) -> DetailOut:
    """Откуда взялась цифра: решение, деньги, комплект, где купить, что
    проверить перед подачей.

    Порядок разделов тот же, что на листе разбора в книге. Разделы с деньгами
    не уходят закупщику — так же, как колонки в таблице, и по той же причине:
    спрятать в браузере и отдать в JSON значит отдать.

    `pick` пересчитывает себестоимость по выбранной находке. Ядро берёт самую
    дешёвую из подходящих, и это правильное умолчание, но не всегда правильный
    ответ: «подходит» — суждение модели, поставщик может быть незнакомым, а
    срок неподъёмным. Считает при этом всё равно ядро — тем же кодом, которым
    считается книга.
    """
    money = sees_money(identity.role)
    состав = lots.positions_of(db, identity.organization.id, _position_or_404(item_id))
    try:
        found = worklist.detail(item_id, pick, members=состав, money=money)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Данные недоступны: {exc}",
        ) from exc

    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Такой закупки нет в отборе",
        )
    return DetailOut.model_validate(asdict(for_role(found, identity.role)))


@router.get("/item/{item_id}/file/{sha256}/view", summary="Показать документ в платформе")
def preview_case_file(
    item_id: str,
    sha256: str,
    identity: CurrentUser,
    _guard: Annotated[None, requires_read] = None,
) -> PreviewOut:
    """Разбирает документ на то, чем его показать: абзацы, таблицы, листы.

    Без этого из платформы приходится выходить: в браузере открывается только
    PDF, а «.docx» и «.xlsx» уезжают в загрузки и открываются чужой
    программой. За смену таких выходов десятки — ТЗ смотрят по каждой закупке.

    Файл ищется в пределах своей закупки, той же проверкой, что и при
    скачивании: путь приходит из базы ядра, но между «не может выйти за папку»
    и «проверено, что не вышел» разница в одну строку.
    """
    file = worklist.find_file(item_id, sha256)
    if file is None or not file.available:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Такого документа в этой закупке нет",
        )
    разобран = preview.build(file.path)
    return PreviewOut(
        kind=разобран.kind,
        name=file.name,
        size_bytes=file.size_bytes,
        blocks=[
            PreviewBlockOut(
                kind=block.kind, text=block.text, rows=[list(row) for row in block.rows]
            )
            for block in разобран.blocks
        ],
        sheets=[
            PreviewSheetOut(
                title=sheet.title,
                rows=[list(row) for row in sheet.rows],
                truncated=sheet.truncated,
            )
            for sheet in разобран.sheets
        ],
        truncated=разобран.truncated,
        note=разобран.note,
    )


@router.get("/item/{item_id}/file/{sha256}", summary="Открыть документ закупки")
def get_case_file(
    item_id: str,
    sha256: str,
    identity: CurrentUser,
    _guard: Annotated[None, requires_read] = None,
) -> FileResponse:
    """Отдаёт файл из папки закупки: ТЗ, МЗ, КП.

    Последний вопрос перед подачей всегда «покажи само ТЗ», и до сих пор за
    ним выходили из платформы в папку на диске. Файл читается с места, а не из
    копии: копия разошлась бы с папкой в день, когда заказчик пришлёт
    исправленное ТЗ.

    Файл ищется в пределах своей закупки, а не по всей базе. Взять его по
    одному хэшу значило бы позволить прочитать чужую папку, подставив хэш
    оттуда, — а в чужой папке лежат КП с ценами, которые нам не показывали.

    Открывается во вкладке, а не скачивается: ТЗ смотрят, а не собирают.
    """
    del identity
    try:
        found = worklist.find_file(item_id, sha256)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Данные недоступны: {exc}",
        ) from exc

    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Такого документа в этой закупке нет",
        )
    if not found.available:
        # Не ошибка платформы, а неподключённый архив: сказать это словами
        # полезнее, чем отдать пустой ответ и оставить гадать.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Файл есть в базе, но платформе не виден: архив закупок лежит на "
                "машине тендерщика и подключается томом (TENDER_ARCHIVE в .env)."
            ),
        )

    return FileResponse(
        found.path,
        filename=found.name,
        # `inline` — открыть, а не скачать: за ТЗ идут посмотреть.
        content_disposition_type="inline",
    )


@router.get("/worklist/export", summary="Выгрузить книгу отбора")
def export_worklist(
    identity: CurrentUser,
    _guard: Annotated[None, requires_money] = None,
) -> FileResponse:
    """Отдаёт ту же книгу, что пишет `tender-analyze hunt`.

    Только тендерщику: в книге себестоимость и маржа целиком, и урезать их по
    ролям здесь нечем — файл уходит одним куском и дальше живёт своей жизнью,
    в почте и на флешках.

    Собирается из уже прочитанного отбора, поэтому это секунды и ноль
    списаний: заново разбирать документы ради скачивания незачем.
    """
    del identity
    try:
        path = worklist.export_workbook()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Книга не собралась: {exc}",
        ) from exc

    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=path.name,
    )


@router.get("/companies", summary="Наши компании")
def list_companies() -> list[CompanyOut]:
    """От кого можно отправить коммерческое предложение.

    Незаполненные реквизиты отдаются вместе с профилем: недостающий БИН должен
    всплыть при выборе компании, а не в готовом КП у заказчика.
    """
    directory = core.companies()
    return [
        CompanyOut(
            key=key,
            name=profile.name,
            bin=profile.bin,
            director=profile.director,
            is_default=key == directory.default,
            missing=profile.missing,
            notes=" ".join(profile.notes.split()),
        )
        for key, profile in directory.profiles.items()
    ]


@router.get("/formats", summary="Какие форматы читаются")
def list_formats() -> list[FormatOut]:
    """Состав поддерживаемых форматов — то, по чему браузер заранее видит,
    что из выбранной папки вообще пойдёт в разбор."""
    registry = core.formats()
    result: list[FormatOut] = []
    for extension in _KNOWN_EXTENSIONS:
        probe = core.describe_upload(f"probe{extension}", f"probe{extension}", 0, "0" * 64)
        result.append(
            FormatOut(
                extension=extension,
                supported=registry.supports(probe),
                is_container=registry.is_container(probe),
            )
        )
    return result


@router.post("/upload-plan", summary="Что из выбранной папки нужно загружать")
def plan_upload(
    files: list[FileProbe],
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_sourcing] = None,
) -> UploadPlan:
    """Считает план загрузки до её начала.

    Браузер присылает имена, размеры и хэши — сами файлы остаются на машине.
    В ответ приходит, что грузить: неподдерживаемые форматы отсеиваются, а
    файлы, уже загруженные этой организацией, не передаются повторно.

    «Уже загружен» проверяется по своим файлам, и это принципиально. Если
    отвечать по всему хранилищу, достаточно заявить хэш чужого документа,
    получить «загружать не нужно» — и чужой файл окажется прикреплён к своей
    закупке. Хэш не угадывают, но он попадает в ссылки, логи и выгрузки, а
    тендерные папки ходят между людьми.

    Отдельной пометкой идёт «разбор уже оплачен»: содержимое то же, кэш ядра
    его узнает, и второй раз платить не придётся. На необходимость загрузки
    это не влияет.
    """
    registry = core.formats()
    hashes = [item.sha256.lower() for item in files]

    uploaded = {
        row.sha256
        for row in db.scalars(
            select(StoredFile).where(
                StoredFile.organization_id == identity.organization.id,
                StoredFile.sha256.in_(hashes),
            )
        )
    }
    analyzed = core.known_hashes(hashes)

    verdicts: list[FileVerdict] = []
    upload_bytes = 0
    for item in files:
        digest = item.sha256.lower()
        probe = core.describe_upload(item.name, item.relative_path, item.size_bytes, digest)
        supported = registry.supports(probe) or registry.is_container(probe)
        if not supported:
            verdicts.append(
                FileVerdict(
                    relative_path=item.relative_path,
                    supported=False,
                    reason=f"формат {item.extension or 'без расширения'} пока не читается",
                )
            )
            continue
        if digest in uploaded:
            verdicts.append(
                FileVerdict(
                    relative_path=item.relative_path,
                    supported=True,
                    known=True,
                    analysis_cached=digest in analyzed,
                    reason="уже загружен — передавать повторно не нужно",
                )
            )
            continue
        upload_bytes += item.size_bytes
        verdicts.append(
            FileVerdict(
                relative_path=item.relative_path,
                supported=True,
                analysis_cached=digest in analyzed,
                reason="разбор уже оплачен" if digest in analyzed else "",
            )
        )

    return UploadPlan(
        files=tuple(verdicts),
        total=len(files),
        to_upload=sum(1 for item in verdicts if item.supported and not item.known),
        upload_bytes=upload_bytes,
        skipped_known=sum(1 for item in verdicts if item.known),
        skipped_unsupported=sum(1 for item in verdicts if not item.supported),
        already_analyzed=sum(1 for item in verdicts if item.analysis_cached),
    )


@router.post("/files/lookup", summary="Найти свои файлы по содержимому")
def lookup_files(
    hashes: list[str],
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_sourcing] = None,
) -> list[FileLookupOut]:
    """Отдаёт идентификаторы уже загруженных файлов.

    Без этого экономия плана теряется на самом главном шаге: браузер знает,
    что файл загружать не надо, но чтобы приложить его к закупке, ему нужен
    идентификатор — и он передавал бы содержимое повторно только ради него.

    Ищет строго среди своих: чужой хэш не должен возвращать чужой файл.
    """
    rows = db.scalars(
        select(StoredFile).where(
            StoredFile.organization_id == identity.organization.id,
            StoredFile.sha256.in_([item.lower() for item in hashes]),
        )
    )
    return [FileLookupOut(id=row.id, sha256=row.sha256, size_bytes=row.size_bytes) for row in rows]


@router.post("/files", summary="Загрузить файл", status_code=status.HTTP_201_CREATED)
def upload_file(
    identity: CurrentUser,
    db: Db,
    request: Request,
    sha256: Annotated[str, Form(pattern=r"^[0-9a-fA-F]{64}$")],
    relative_path: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    _guard: Annotated[None, requires_sourcing] = None,
) -> UploadedFileOut:
    """Принимает один файл из выбранной папки.

    Хэш пересчитывается здесь и сверяется с заявленным. Клиент считает его
    сам, чтобы не грузить лишнего, но верить этому значению нельзя: тот, кто
    подменит содержимое под чужой хэш, положит свой файл на место чужого — и
    дальше его получит каждый, кто этот файл запросит.
    """
    storage: FileStorage = request.app.state.storage
    try:
        saved = storage.save(file.file, expected_sha256=sha256)
    except ChecksumMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc

    existing = db.scalars(
        select(StoredFile).where(
            StoredFile.organization_id == identity.organization.id,
            StoredFile.sha256 == saved.sha256,
        )
    ).one_or_none()
    if existing is not None:
        return UploadedFileOut(
            id=existing.id,
            sha256=existing.sha256,
            size_bytes=existing.size_bytes,
            relative_path=relative_path,
            deduplicated=True,
        )

    row = StoredFile(
        organization_id=identity.organization.id,
        sha256=saved.sha256,
        size_bytes=saved.size_bytes,
        content_type=file.content_type or "",
        original_name=(file.filename or "")[:512],
        uploaded_by_id=identity.user.id,
    )
    db.add(row)
    db.flush()
    return UploadedFileOut(
        id=row.id,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        relative_path=relative_path,
        deduplicated=saved.already_existed,
    )


@router.post("/estimate", summary="Оценить стоимость разбора", status_code=status.HTTP_202_ACCEPTED)
def start_estimate(
    payload: EstimateIn,
    identity: CurrentUser,
    db: Db,
    request: Request,
    _guard: Annotated[None, requires_money] = None,
) -> StartedJobOut:
    """Ставит в очередь подсчёт стоимости будущего разбора.

    Оценка бесплатна, но не мгновенна: чтобы понять, сколько страниц придётся
    распознавать, файлы надо прочитать. Поэтому она идёт задачей с прогрессом,
    а не ожиданием в запросе.
    """
    settings: Settings = request.app.state.settings
    service = JobService(db, request.app.state.redis)
    job = service.create(
        organization_id=identity.organization.id,
        created_by_id=identity.user.id,
        module="tender",
        kind="estimate",
        params={
            "file_ids": [str(item) for item in payload.file_ids],
            "with_market": payload.with_market,
        },
        total=len(payload.file_ids) * 2,
    )
    # Фиксируем до постановки в очередь: исполнитель заберёт задачу мгновенно
    # и не найдёт её в базе, если транзакция ещё не закрыта.
    db.commit()
    enqueue_sync(settings, job.id)
    return StartedJobOut(job_id=job.id)


_KNOWN_EXTENSIONS = (
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".txt",
    ".rtf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".zip",
    ".rar",
    ".7z",
    ".msg",
    ".eml",
)
"""Расширения, о которых спрашивают чаще всего.

Список для показа, а не для решения: читается ли файл, определяет реестр
извлекателей ядра, и он же отвечает на `/upload-plan`. Здесь — только то, что
интерфейс показывает человеку до выбора папки."""
