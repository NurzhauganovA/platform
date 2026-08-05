"""Закупки: заведение, состав, разбор.

Порядок работы повторяет то, как тендерщик работает папками. Заводится
закупка, в неё складываются файлы выбранной папки, потом она разбирается.
Отличие от диска одно: состав закупки известен платформе, поэтому повторную
загрузку тех же документов она берёт на себя.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from platform_api.auth.dependencies import CurrentUser, Db, requires_money, requires_sourcing
from platform_api.config import Settings
from platform_api.db.models import StoredFile
from platform_api.jobs import JobService
from platform_api.jobs.worker import enqueue_sync
from platform_api.logging import get_logger
from platform_api.modules.tender.models import CaseFileRow, CaseStatus, TenderCaseRow

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


__all__ = ["router"]
