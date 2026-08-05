"""Эндпоинты тендерного модуля."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select

from platform_api.auth.dependencies import CurrentUser, Db, requires_money, requires_sourcing
from platform_api.config import Settings
from platform_api.db.models import StoredFile
from platform_api.jobs import JobService
from platform_api.jobs.worker import enqueue_sync
from platform_api.modules.tender import core
from platform_api.modules.tender.cases import router as cases_router
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


@router.get("/health", summary="Готовность модуля к разбору")
def get_health() -> ModuleHealth:
    """Всё ли настроено для платного разбора.

    Спрашивается до загрузки папки: разбор идёт минутами и падает на первом же
    файле, если нет доступа к модели, — а человек к этому моменту уже ждёт.
    """
    return ModuleHealth.model_validate(check_health())


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
