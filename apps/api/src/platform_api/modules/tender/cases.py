"""Закупки: заведение, состав, разбор.

Порядок работы повторяет то, как тендерщик работает папками. Заводится
закупка, в неё складываются файлы выбранной папки, потом она разбирается.
Отличие от диска одно: состав закупки известен платформе, поэтому повторную
загрузку тех же документов она берёт на себя.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from platform_api.auth.dependencies import CurrentUser, Db, requires_money, requires_sourcing
from platform_api.config import Settings
from platform_api.db.models import StoredFile
from platform_api.jobs import JobService
from platform_api.jobs.worker import enqueue_sync
from platform_api.logging import get_logger
from platform_api.modules.tender.models import CaseFileRow, CaseStatus, TenderCaseRow
from platform_api.modules.tender.workspace import CaseWorkspace

logger = get_logger(__name__)

router = APIRouter(prefix="/cases", tags=["Закупки"])


class CaseIn(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    customer: str = ""
    subject: str = ""
    note: str = ""


class CaseFileIn(BaseModel):
    """Файл, который кладут в закупку.

    Он уже загружен: сюда приходит его идентификатор и место внутри закупки.
    """

    file_id: uuid.UUID
    relative_path: str = Field(min_length=1, max_length=1024)


class CaseFileOut(BaseModel):
    id: uuid.UUID
    relative_path: str
    sha256: str
    size_bytes: int


class CaseOut(BaseModel):
    id: uuid.UUID
    title: str
    customer: str = ""
    subject: str = ""
    status: CaseStatus
    files_count: int = 0
    total_bytes: int = 0
    note: str = ""


class CaseDetailOut(CaseOut):
    files: list[CaseFileOut] = []


def _to_out(case: TenderCaseRow) -> CaseOut:
    return CaseOut(
        id=case.id,
        title=case.title,
        customer=case.customer,
        subject=case.subject,
        status=case.status,
        files_count=len(case.files),
        total_bytes=case.total_bytes,
        note=case.note,
    )


def _require_case(db: Db, case_id: uuid.UUID, identity: CurrentUser) -> TenderCaseRow:
    """Закупка своей организации — или 404.

    Именно 404: по разнице между «нет» и «не ваша» перебирается, какие
    закупки вообще существуют.
    """
    case = db.get(TenderCaseRow, case_id)
    if case is None or case.organization_id != identity.organization.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Закупка не найдена")
    return case


@router.post("", summary="Завести закупку", status_code=status.HTTP_201_CREATED)
def create_case(
    payload: CaseIn,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_sourcing] = None,
) -> CaseOut:
    case = TenderCaseRow(
        organization_id=identity.organization.id,
        created_by_id=identity.user.id,
        title=payload.title.strip(),
        customer=payload.customer.strip(),
        subject=payload.subject.strip(),
        note=payload.note,
    )
    db.add(case)
    db.flush()
    logger.info("Закупка заведена", case_id=str(case.id), title=case.title)
    return _to_out(case)


@router.get("", summary="Список закупок")
def list_cases(
    identity: CurrentUser,
    db: Db,
    limit: int = 100,
    _guard: Annotated[None, requires_sourcing] = None,
) -> list[CaseOut]:
    cases = db.scalars(
        select(TenderCaseRow)
        .where(TenderCaseRow.organization_id == identity.organization.id)
        .order_by(TenderCaseRow.created_at.desc())
        .limit(min(limit, 500))
    )
    return [_to_out(case) for case in cases]


@router.get("/{case_id}", summary="Закупка целиком")
def get_case(
    case_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_sourcing] = None,
) -> CaseDetailOut:
    case = _require_case(db, case_id, identity)
    base = _to_out(case)
    return CaseDetailOut(
        **base.model_dump(),
        files=[
            CaseFileOut(
                id=item.id,
                relative_path=item.relative_path,
                sha256=item.sha256,
                size_bytes=item.size_bytes,
            )
            for item in case.files
        ],
    )


@router.post("/{case_id}/files", summary="Добавить файлы в закупку")
def attach_files(
    case_id: uuid.UUID,
    payload: list[CaseFileIn],
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_sourcing] = None,
) -> CaseDetailOut:
    """Кладёт уже загруженные файлы в закупку.

    Повторное добавление того же места не задваивается: браузер может
    прислать список дважды — при повторе загрузки или при обрыве связи.
    """
    case = _require_case(db, case_id, identity)
    known = {item.relative_path for item in case.files}

    files = {
        row.id: row
        for row in db.scalars(
            select(StoredFile).where(
                StoredFile.organization_id == identity.organization.id,
                StoredFile.id.in_([item.file_id for item in payload]),
            )
        )
    }

    for item in payload:
        stored = files.get(item.file_id)
        if stored is None:
            # Файл чужой организации или несуществующий. Молча пропустить
            # нельзя: человек будет ждать его в разборе.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Файл {item.file_id} не найден среди загруженных",
            )
        if item.relative_path in known:
            continue
        db.add(
            CaseFileRow(
                case_id=case.id,
                file_id=stored.id,
                relative_path=item.relative_path,
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
            )
        )
        known.add(item.relative_path)

    if case.status is CaseStatus.DRAFT and known:
        case.status = CaseStatus.READY
    db.flush()
    db.refresh(case)
    return get_case(case_id, identity, db)


@router.post(
    "/{case_id}/analyze", summary="Разобрать закупку", status_code=status.HTTP_202_ACCEPTED
)
def start_analysis(
    case_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    request: Request,
    force: bool = False,
    _guard: Annotated[None, requires_money] = None,
) -> dict[str, uuid.UUID]:
    """Ставит разбор закупки в очередь.

    Платная команда: каждый документ уходит в модель. То, что уже разобрано,
    берётся из кэша ядра — повторный запуск по той же закупке стоит ноль,
    если состав не менялся.
    """
    case = _require_case(db, case_id, identity)
    if not case.files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="В закупке нет файлов — разбирать нечего",
        )

    settings: Settings = request.app.state.settings
    service = JobService(db, request.app.state.redis)
    job = service.create(
        organization_id=identity.organization.id,
        created_by_id=identity.user.id,
        module="tender",
        kind="analyze",
        params={"case_id": str(case.id), "force": force},
        total=len(case.files),
    )
    case.status = CaseStatus.ANALYZING
    # Фиксируем до постановки в очередь: исполнитель заберёт задачу мгновенно
    # и не найдёт её в базе, если транзакция ещё не закрыта.
    db.commit()
    enqueue_sync(settings, job.id)
    return {"job_id": job.id}


@router.post("/{case_id}/decide", summary="Решить по закупке", status_code=status.HTTP_202_ACCEPTED)
def start_decision(
    case_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    request: Request,
    with_market: bool = False,
    force: bool = False,
    _guard: Annotated[None, requires_money] = None,
) -> dict[str, uuid.UUID]:
    """Ставит в очередь решение: участвовать ли и по какой цене.

    Платная команда и отдельная от разбора: разбор отвечает, что написано в
    бумагах, решение — что нам с этим делать. Повторный запуск по неизменной
    закупке денег не стоит, ядро отдаёт прежний вывод из кэша.

    `with_market` включает поиск на рынках: он оплачивается отдельно от токенов
    и заметно меняет итог, поэтому по умолчанию выключен.
    """
    case = _require_case(db, case_id, identity)
    if case.status not in (CaseStatus.ANALYZED, CaseStatus.ANALYZING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сначала разберите документы закупки",
        )

    settings: Settings = request.app.state.settings
    service = JobService(db, request.app.state.redis)
    job = service.create(
        organization_id=identity.organization.id,
        created_by_id=identity.user.id,
        module="tender",
        kind="decide",
        params={"case_id": str(case.id), "with_market": with_market, "force": force},
        total=1,
    )
    db.commit()
    enqueue_sync(settings, job.id)
    return {"job_id": job.id}


class OfferIn(BaseModel):
    """От чьего имени собирать предложение."""

    companies: list[str] = Field(
        default_factory=list,
        description="Ключи компаний. Пусто — та, что помечена по умолчанию",
    )
    number: str | None = Field(default=None, description="Исходящий номер КП")


@router.post("/{case_id}/sourcing", summary="Найти на рынках", status_code=status.HTTP_202_ACCEPTED)
def start_sourcing(
    case_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    request: Request,
    force: bool = False,
    _guard: Annotated[None, requires_money] = None,
) -> dict[str, uuid.UUID]:
    """Ставит в очередь поиск позиций на рынках пяти стран.

    Платная команда, и дороже прочих: каждый запрос ходит в интернет. Зато
    здесь впервые появляется наша собственная цена — та, по которой мы можем
    купить, — а до неё маржа остаётся догадкой.
    """
    case = _require_case(db, case_id, identity)
    if case.status is not CaseStatus.ANALYZED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сначала разберите документы закупки",
        )
    return {"job_id": _queue(db, request, identity, case, "sourcing", {"force": force}, 1)}


@router.post("/{case_id}/offer", summary="Собрать наше КП", status_code=status.HTTP_202_ACCEPTED)
def start_offer(
    case_id: uuid.UUID,
    payload: OfferIn,
    identity: CurrentUser,
    db: Db,
    request: Request,
    _guard: Annotated[None, requires_money] = None,
) -> dict[str, uuid.UUID]:
    """Собирает КП для заказчика и задание закупщику.

    Денег не стоит: обращения к модели здесь нет, цена считается кодом по уже
    известным величинам — предложениям конкурентов, нашей себестоимости и
    целевой наценке.
    """
    case = _require_case(db, case_id, identity)
    if case.status is not CaseStatus.ANALYZED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сначала разберите документы закупки",
        )
    return {
        "job_id": _queue(
            db,
            request,
            identity,
            case,
            "offer",
            {"companies": payload.companies, "number": payload.number},
            max(1, len(payload.companies)),
        )
    }


@router.get("/{case_id}/documents", summary="Собранные нами документы")
def list_documents(
    case_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    request: Request,
    _guard: Annotated[None, requires_sourcing] = None,
) -> list[dict[str, Any]]:
    """Что лежит в папке «Наш разбор» этой закупки.

    Задание закупщику здесь тоже: закупщик работает именно с ним, и прятать
    от него собственный рабочий файл незачем.
    """
    case = _require_case(db, case_id, identity)
    folder = _results_dir(request, case)
    if not folder.exists():
        return []
    return [
        {
            "name": item.name,
            "size_bytes": item.stat().st_size,
            "kind": "offer" if item.name.startswith("КП") else "worksheet",
        }
        for item in sorted(folder.iterdir())
        if item.is_file()
    ]


@router.get("/{case_id}/documents/{name}", summary="Скачать документ")
def download_document(
    case_id: uuid.UUID,
    name: str,
    identity: CurrentUser,
    db: Db,
    request: Request,
    _guard: Annotated[None, requires_sourcing] = None,
) -> FileResponse:
    """Отдаёт готовый документ.

    Имя приходит из адреса, поэтому проверяется дважды: в нём не должно быть
    ни разделителей пути, ни выхода вверх. `../../.env` в этом поле — первое,
    что пробуют, а рядом с каталогом закупки лежат чужие закупки.
    """
    case = _require_case(db, case_id, identity)
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Недопустимое имя")

    folder = _results_dir(request, case)
    path = (folder / name).resolve()
    if folder.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    return FileResponse(path, filename=name)


def _results_dir(request: Request, case: TenderCaseRow) -> Path:
    from platform_api.modules.tender.core import core_settings

    workspace: CaseWorkspace = request.app.state.workspace
    return workspace.path_for(case.id, case.title) / core_settings().results_dirname


def _queue(
    db: Db,
    request: Request,
    identity: CurrentUser,
    case: TenderCaseRow,
    kind: str,
    params: dict[str, Any],
    total: int,
) -> uuid.UUID:
    """Ставит задачу модуля в очередь и фиксирует её до постановки.

    Фиксация обязательна: исполнитель заберёт задачу мгновенно и не найдёт её
    в базе, если транзакция ещё не закрыта.
    """
    settings: Settings = request.app.state.settings
    service = JobService(db, request.app.state.redis)
    job = service.create(
        organization_id=identity.organization.id,
        created_by_id=identity.user.id,
        module="tender",
        kind=kind,
        params={"case_id": str(case.id), **params},
        total=total,
    )
    db.commit()
    enqueue_sync(settings, job.id)
    return job.id


class ProposedCaseOut(BaseModel):
    """Закупка, которую предлагается выделить из папки."""

    title: str
    subject: str
    customer: str = ""
    files: list[str] = []
    anchors: int = 0
    offers: int = 0


class SplitPlanOut(BaseModel):
    """Что получится, если разделить папку."""

    can_split: bool
    cases: list[ProposedCaseOut] = []
    reason: str = ""


@router.get("/{case_id}/split", summary="Предложение разделить папку")
def preview_split(
    case_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_sourcing] = None,
) -> SplitPlanOut:
    """Смотрит, не лежат ли в папке несколько разных закупок.

    В одной папке тендерщика бывает три десятка маркетинговых заключений —
    бензин, седельный тягач, ошейник для КРС. Пока они считаются одной
    закупкой, сравнивать нечего, и человек видит ноль позиций там, где на
    самом деле два десятка отдельных дел.
    """
    from platform_api.modules.tender.core import build_case_view
    from platform_api.modules.tender.split import propose_split

    case = _require_case(db, case_id, identity)
    view = build_case_view(case)
    if view is None:
        return SplitPlanOut(can_split=False, reason="Закупка ещё не разобрана")

    groups = propose_split(view)
    if not groups:
        return SplitPlanOut(can_split=False, reason="В папке одна закупка")

    return SplitPlanOut(
        can_split=True,
        cases=[
            ProposedCaseOut(
                title=group.title,
                subject=group.subject,
                customer=group.customer,
                files=group.files,
                anchors=group.anchors,
                offers=group.offers,
            )
            for group in groups
        ],
    )


@router.post("/{case_id}/split", summary="Разделить папку на закупки")
def apply_split(
    case_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    request: Request,
    _guard: Annotated[None, requires_sourcing] = None,
) -> list[CaseOut]:
    """Создаёт по закупке на каждый предмет.

    Файлы не копируются: содержимое лежит в хранилище по хэшу, а закупка
    ссылается на него. Исходная папка уходит в архив, но не удаляется — по ней
    видно, откуда всё взялось, и разделение можно перепроверить.
    """
    from platform_api.modules.tender.core import build_case_view
    from platform_api.modules.tender.split import propose_split

    case = _require_case(db, case_id, identity)
    view = build_case_view(case)
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Закупка ещё не разобрана"
        )

    groups = propose_split(view)
    if not groups:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="В папке одна закупка")

    by_path = {item.relative_path: item for item in case.files}
    created: list[TenderCaseRow] = []

    for group in groups:
        child = TenderCaseRow(
            organization_id=identity.organization.id,
            created_by_id=identity.user.id,
            title=group.title[:512],
            customer=(group.customer or case.customer)[:512],
            subject=group.subject,
            status=CaseStatus.READY,
            note=f"Выделена из «{case.title}»",
        )
        db.add(child)
        db.flush()

        for path in group.files:
            source = by_path.get(path)
            if source is None:
                continue
            db.add(
                CaseFileRow(
                    case_id=child.id,
                    file_id=source.file_id,
                    # Внутри своей закупки файл лежит под своим именем: путь
                    # исходной папки к новой закупке отношения не имеет.
                    relative_path=path.rsplit("/", 1)[-1],
                    sha256=source.sha256,
                    size_bytes=source.size_bytes,
                )
            )
        created.append(child)

    case.status = CaseStatus.ARCHIVED
    case.note = f"Разделена на {len(created)} закупок"
    db.flush()

    logger.info("Папка разделена", case_id=str(case.id), created=len(created))
    return [_to_out(item) for item in created]


__all__ = ["router"]
