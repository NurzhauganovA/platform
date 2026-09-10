"""Эндпоинты карточки лота, задач и согласования.

Общие для всех площадок: площадка — поле карточки, а не отдельный набор
обработчиков. Три одинаковых набора означали бы три места, где правила о
переходах расходятся, — а самый дорогой из них необратим.

Что можно нажать, приходит в ответе (`can`). Это не замена проверке прав:
проверка на эндпоинте остаётся, а список нужен, чтобы не рисовать кнопку,
которая ответит отказом.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Annotated, BinaryIO

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from platform_api.auth.dependencies import CurrentUser, Db, require_roles
from platform_api.config import Settings
from platform_api.db.models import (
    ApprovalKind,
    ApprovalState,
    Department,
    Job,
    JobStatus,
    LotCard,
    LotStatus,
    Participation,
    Role,
    TaskState,
    User,
)
from platform_api.errors import SpokenError
from platform_api.jobs.service import JobService
from platform_api.jobs.worker import enqueue_sync
from platform_api.logging import get_logger
from platform_api.modules import ModuleRegistry, cards, sheets
from platform_api.modules.goszakup import start
from platform_api.modules.schemas import StartedJobOut

logger = get_logger(__name__)

router = APIRouter(prefix="/cards", tags=["Лоты в работе"])

# Карточку видят те, кто с лотами работает: у каждого отдела в ней своё, и
# запирать снабжение от лота, который оно же и снабжает, незачем.
#
# Список явный, а не «все вошедшие». Роли прибавляются — бухгалтер, кладовщик,
# — и новая не должна получать доступ к работе с закупками просто потому, что
# её завели. Наблюдателя здесь нет намеренно: он смотрит отчёты, а карточка
# это стол с задачами и подписями.
#
# `Depends` обязателен. Без него FastAPI принимает проверку за обычный
# параметр запроса: она не выполняется, а `_guard` вылезает в схеме API
# отдельным полем. Тем же способом ломается любая проверка прав в проекте.
requires_crm = Depends(
    require_roles(
        Role.MANAGER,
        Role.ANALYST,
        Role.BUYER,
        Role.LAWYER,
        Role.TECHNOLOGIST,
        Role.ASSEMBLER,
        Role.HEAD,
        Role.COMMERCIAL,
    )
)
Guard = Annotated[None, requires_crm]


class SignOut(BaseModel):
    kind: str
    name: str
    state: str
    by: str
    at: str
    note: str
    can_sign: bool


class TalkOut(BaseModel):
    """Обсуждение по лоту, коротко. Пусто — его не заводили."""

    id: str
    stage: str
    stage_name: str
    deadline: str
    left: str
    burning: bool
    overdue: bool
    writing: str = ""
    """Как идёт написание моделью: `queued`, `running`, `ready`, `failed`."""


class CardOut(BaseModel):
    """Карточка лота.

    Суммы числом, а не точным десятичным: точное уходит строкой «8660625.00»,
    и в таблице оно так и стоит — слитно, без разрядов. Копейки здесь
    справочные, решают по ним «крупная закупка или мелкая».
    """

    id: str
    module: str
    row_id: str
    code: str
    source_number: str
    """Номер закупки на площадке. По нему открывают разбор и ищут на портале."""

    title: str
    customer: str
    amount: float | None
    enstru_code: str
    category: str

    status: str
    status_name: str
    step: int
    participation: str
    skip_reason: str

    manager: str
    manager_id: str
    owner: str
    owner_id: str

    deadline: str
    left: str
    burning: bool
    overdue: bool

    approve_by: str
    approve_left: str
    approve_burning: bool
    approve_overdue: bool

    note: str
    won_amount: float | None
    winner: str
    started_at: str
    submitted_at: str
    finished_at: str

    approvals: list[SignOut]
    approved: bool
    open_tasks: int
    done_tasks: int
    can: list[str]
    discussion: TalkOut | None = None


class TaskOut(BaseModel):
    id: str
    card_id: str
    card_code: str
    card_title: str
    department: str
    department_name: str
    title: str
    body: str
    assignee: str
    assignee_id: str
    due_at: str
    left: str
    burning: bool
    overdue: bool
    state: str
    result: str
    created_at: str
    taken_at: str = ""
    done_at: str = ""
    done_by: str = ""
    author: str = ""


class EventOut(BaseModel):
    """Одно действие над лотом."""

    id: str
    at: str
    actor: str
    actor_id: str
    actor_role: str
    """Роль на момент действия. Снабженец, ставший руководителем, подписывал
    за снабжение — в ленте должно остаться так."""

    by_machine: bool
    """Сделано прогоном или моделью. Без этого признака премию получит робот."""

    kind: str
    title: str
    detail: str
    from_status: str
    to_status: str


class WorkerOut(BaseModel):
    """Сколько сделал человек по этому лоту."""

    name: str
    user_id: str
    role: str
    actions: int
    first_at: str
    last_at: str


class StageOut(BaseModel):
    """Сколько лот простоял на этапе и у кого."""

    status: str
    name: str
    seconds: int
    owner: str
    running: bool


class HistoryOut(BaseModel):
    """Лента лота, сводка по людям и время по этапам."""

    events: list[EventOut]
    workers: list[WorkerOut]
    stages: list[StageOut]


class FileOut(BaseModel):
    """Приложенный к лоту файл."""

    id: str
    name: str
    sha256: str
    size_bytes: int
    note: str
    added_by: str
    added_at: str
    folder_id: str = ""
    """В какой папке лежит. Пусто — в корне."""


class UploadedOut(FileOut):
    """Ответ на загрузку: тот же файл плюс то, что стоит сказать про неё.

    Отдельной схемой, а не полем в `FileOut`: список файлов приходит на каждое
    открытие вкладки, и рассказывать в нём про загрузку нечего — поле стояло бы
    пустым у каждой строки. По этим схемам генерируется клиент, и необязательное
    поле, которое никогда не заполнено, читается как «иногда бывает» — его
    начинают проверять там, где проверять нечего.
    """

    notice: str = ""
    """Что произошло с этой загрузкой. Пусто — говорить нечего.

    Полем ответа, а не догадкой браузера: файлы сравниваются по содержимому, и
    знает об этом только сервер."""


class PersonOut(BaseModel):
    """Сотрудник в списке выбора ответственного."""

    id: str
    name: str
    role: str


class OpenIn(BaseModel):
    module: str
    row_id: str
    code: str
    source_number: str = ""
    title: str
    customer: str = ""
    amount: Decimal | None = None
    enstru_code: str = ""
    category: str = ""
    deadline: datetime | None = None


class MoveIn(BaseModel):
    to: LotStatus
    reason: str = ""


class DecideIn(BaseModel):
    participation: Participation
    reason: str = ""


class SignIn(BaseModel):
    kind: ApprovalKind
    state: ApprovalState
    note: str = ""


class AssignIn(BaseModel):
    manager_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    change_manager: bool = False
    change_owner: bool = False
    """Признаки нужны, чтобы отличить «снять ответственного» от «не трогать»:
    и то и другое приходит пустым значением."""


class TaskIn(BaseModel):
    title: str
    body: str = ""
    department: Department | None = None
    assignee_id: uuid.UUID | None = None
    due_at: datetime | None = None


class CloseIn(BaseModel):
    state: TaskState = TaskState.DONE
    result: str = ""


class TakeIn(BaseModel):
    assignee_id: uuid.UUID | None = None
    """Кому. Пусто — себе.

    Срока здесь нет намеренно: его назначает автор задачи при заведении, и
    берущий его не двигает — см. `cards.take_task`.
    """

    release: bool = False
    """Вернуть задачу в очередь отдела.

    Отдельным признаком, а не пустым `assignee_id`: «не указан» и «указан
    пустым» в JSON приходят одинаково, и возврат в очередь молча брал задачу на
    того, кто нажал «Вернуть отделу», — кнопка делала обратное написанному.
    """


class ResultIn(BaseModel):
    """Чем кончилась подача.

    Цена и победитель приходят вместе со статусом: отмечать «проиграли», а
    потом отдельным действием вписывать, кому и за сколько, значит получить
    сотню проигранных лотов без единой цифры — а именно по ним и смотрят, с
    кем соревнуемся.
    """

    won_amount: Decimal | None = None
    winner: str = ""


@router.get("", summary="Лоты в работе")
def get_cards(
    identity: CurrentUser,
    db: Db,
    module: Annotated[str | None, Query(description="Площадка")] = None,
    lot_status: Annotated[LotStatus | None, Query(alias="status")] = None,
    participation: Annotated[Participation | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    enstru_code: Annotated[str | None, Query()] = None,
    amount_from: Annotated[Decimal | None, Query()] = None,
    amount_to: Annotated[Decimal | None, Query()] = None,
    mine: Annotated[bool, Query(description="Где я менеджер или ответственный")] = False,
    unowned: Annotated[bool, Query(description="Ничьи")] = False,
    burning: Annotated[
        bool, Query(description="Только горящие; просроченные сюда не идут")
    ] = False,
    search: Annotated[str, Query()] = "",
    _guard: Guard = None,
) -> list[CardOut]:
    found = cards.listing(
        db,
        organization_id=identity.organization.id,
        role=identity.role,
        user_id=identity.user.id,
        filters=cards.Filters(
            module=module,
            status=lot_status,
            participation=participation,
            category=category,
            enstru_code=enstru_code,
            amount_from=amount_from,
            amount_to=amount_to,
            mine=mine,
            unowned=unowned,
            burning=burning,
            search=search,
        ),
    )
    return [_card_out(item) for item in found]


@router.post("", summary="Взять лот в работу", status_code=status.HTTP_201_CREATED)
def post_card(
    body: OpenIn,
    identity: CurrentUser,
    db: Db,
    request: Request,
    _guard: Guard = None,
) -> CardOut:
    """Заводит карточку по строке рабочего списка.

    Повторное нажатие возвращает ту же карточку: кнопку нажимают дважды, а
    вторая карточка означала бы два ответственных и два набора подписей.

    Следом площадка запускает своё: у госзакупок это обсуждение и разбор
    спецификации. Что именно — решает модуль (`ModuleSpec.on_take`), а не этот
    обработчик: «взять в работу» у площадок значит разное, и знание об этом
    живёт рядом с самой площадкой.
    """
    card = cards.open_card(
        db,
        organization_id=identity.organization.id,
        module=body.module,
        row_id=body.row_id,
        snapshot=cards.Snapshot(
            code=body.code,
            source_number=body.source_number,
            title=body.title,
            customer=body.customer,
            amount=body.amount,
            enstru_code=body.enstru_code,
            category=body.category,
            deadline=body.deadline,
        ),
        by=identity.user.id,
        settings=request.app.state.settings,
    )
    db.commit()
    _autostart(db, card, identity=identity, request=request)
    return _card_out(_one(db, identity, card.id))


def _autostart(db: Db, card: LotCard, *, identity: CurrentUser, request: Request) -> None:
    """Запускает то, что площадка делает сама при взятии лота в работу.

    Задачи ставятся в очередь **после** фиксации: исполнитель забирает их
    мгновенно и не нашёл бы ни задачу, ни обсуждение, если транзакция ещё
    открыта.

    Ошибка здесь не отменяет взятия. Лот взят — это главное; не запустившийся
    разбор человек запустит кнопкой, а откат карточки из-за недоступной модели
    оставил бы его вовсе ни с чем.
    """
    registry: ModuleRegistry = request.app.state.modules
    settings: Settings = request.app.state.settings
    try:
        module = registry.get(card.module)
    except KeyError:
        return
    if module.on_take is None:
        return

    try:
        jobs = module.on_take(
            db,
            card=card,
            user_id=identity.user.id,
            settings=settings,
            redis=request.app.state.redis,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("cards.autostart.failed", code=card.code, error=str(exc))
        return

    for job_id in jobs:
        enqueue_sync(settings, job_id)


@router.get("/people", summary="Кому можно поручить")
def get_people(identity: CurrentUser, db: Db, _guard: Guard = None) -> list[PersonOut]:
    """Сотрудники организации с их ролями.

    Нужен спискам выбора: ответственного назначают руками, и вводить почту
    коллеги по памяти — верный способ поручить не тому.
    """
    from sqlalchemy import select

    from platform_api.db.models import Membership

    rows = db.execute(
        select(User, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.organization_id == identity.organization.id)
        .order_by(User.full_name, User.email)
    ).all()
    return [
        PersonOut(id=str(user.id), name=user.full_name or user.email, role=role.value)
        for user, role in rows
    ]


@router.get("/tasks", summary="Задачи")
def get_tasks(
    identity: CurrentUser,
    db: Db,
    department: Annotated[Department | None, Query()] = None,
    mine: Annotated[bool, Query(description="Только мои")] = False,
    unassigned: Annotated[bool, Query(description="Ничьи в очереди отдела")] = False,
    card_id: Annotated[uuid.UUID | None, Query()] = None,
    task_state: Annotated[
        str,
        Query(
            alias="state",
            description="open, done, cancelled или all — все состояния сразу",
        ),
    ] = "open",
    _guard: Guard = None,
) -> list[TaskOut]:
    """Задачи под отбором.

    `state=all` отдаёт и открытые, и закрытые. Это нужно карточке лота: блок
    отдела показывает «1 из 2» и кто закрыл, а по одним открытым ни того, ни
    другого не собрать. Умолчание при этом осталось прежним — открытые: их
    спрашивают в девяти случаях из десяти, и очередь, которая по умолчанию
    отдаёт всё закрытое за год, бесполезна.
    """
    want = None if task_state == "all" else _task_state(task_state)
    found = cards.tasks(
        db,
        organization_id=identity.organization.id,
        department=department,
        assignee_id=identity.user.id if mine else None,
        unassigned=unassigned,
        card_id=card_id,
        state=want,
    )
    return [TaskOut(**asdict(item)) for item in found]


def _task_state(value: str) -> TaskState:
    """Состояние из строки. Непонятное — это опечатка в запросе, а не «всё».

    Молчаливое «покажу всё» на опечатке отдало бы закупщику закрытые задачи
    там, где он просил открытые, и заметил бы он это не сразу.
    """
    try:
        return TaskState(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Неизвестное состояние задачи: {value}",
        ) from exc


class FolderOut(BaseModel):
    """Папка лота."""

    id: str
    name: str
    files: int


class FolderIn(BaseModel):
    """Как назвать папку."""

    name: str


class MoveFileIn(BaseModel):
    """Куда переложить файл. Пустая папка — в корень."""

    folder_id: str = ""


@router.get("/{card_id}/folders", summary="Папки лота")
def get_folders(
    card_id: uuid.UUID, identity: CurrentUser, db: Db, _guard: Guard = None
) -> list[FolderOut]:
    """Папки с числом файлов в каждой.

    Отдельным списком, а не полем у файлов: пустая папка существует сама по
    себе — её заводят до того, как соберут счета, — и по одним файлам её не
    восстановить.
    """
    try:
        found = cards.folders(db, organization_id=identity.organization.id, card_id=card_id)
    except SpokenError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [FolderOut(**asdict(item)) for item in found]


@router.post("/{card_id}/folders", summary="Завести папку", status_code=201)
def post_folder(
    card_id: uuid.UUID,
    body: FolderIn,
    identity: CurrentUser,
    db: Db,
    _guard: Guard = None,
) -> FolderOut:
    made = _act(
        lambda: cards.make_folder(
            db,
            organization_id=identity.organization.id,
            card_id=card_id,
            name=body.name,
            by=identity.user.id,
        )
    )
    db.commit()
    return FolderOut(id=str(made.id), name=made.name, files=0)


@router.delete("/folders/{folder_id}", summary="Убрать папку")
def delete_folder(
    folder_id: uuid.UUID, identity: CurrentUser, db: Db, _guard: Guard = None
) -> dict[str, int]:
    """Убирает папку, а файлы из неё возвращает в корень.

    Возвращает, сколько вернулось: человек должен убедиться, что счета
    поставщика не ушли вместе с папкой, — достать их обратно можно только по
    хэшу, которого никто не помнит.
    """
    returned = _act(
        lambda: cards.drop_folder(db, organization_id=identity.organization.id, folder_id=folder_id)
    )
    db.commit()
    return {"вернулось_в_корень": returned}


@router.post("/files/{link_id}/folder", summary="Переложить файл")
def post_file_folder(
    link_id: uuid.UUID,
    body: MoveFileIn,
    identity: CurrentUser,
    db: Db,
    _guard: Guard = None,
) -> FileOut:
    moved = _act(
        lambda: cards.move_file(
            db,
            organization_id=identity.organization.id,
            link_id=link_id,
            folder_id=uuid.UUID(body.folder_id) if body.folder_id else None,
        )
    )
    db.commit()
    found = cards.files(db, organization_id=identity.organization.id, card_id=moved.card_id)
    one = next((item for item in found if item.id == str(moved.id)), None)
    if one is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    return FileOut(**asdict(one))


@router.get("/{card_id}/files", summary="Файлы лота")
def get_files(
    card_id: uuid.UUID, identity: CurrentUser, db: Db, _guard: Guard = None
) -> list[FileOut]:
    try:
        found = cards.files(db, organization_id=identity.organization.id, card_id=card_id)
    except SpokenError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [FileOut(**asdict(item)) for item in found]


@router.post("/{card_id}/files", summary="Приложить файл", status_code=201)
async def post_file(
    card_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    request: Request,
    file: Annotated[UploadFile, File()],
    folder_id: Annotated[str, Form()] = "",
    _guard: Guard = None,
) -> UploadedOut:
    """Кладёт файл в хранилище и привязывает к лоту.

    Хэш считается здесь по ходу записи, а не приходит от браузера: файл
    прикладывают с телефона на ходу, считать хэш там нечем, а верить
    присланному значению нельзя — подменивший его положит свой файл на место
    чужого.

    Тот же файл, приложенный дважды, не двоится: хранилище складывает по хэшу
    содержимого, и повторная загрузка того же счёта даёт ту же запись.
    """
    from platform_api.db.models import StoredFile
    from platform_api.storage import ChecksumMismatchError, FileStorage, FileTooLargeError

    storage: FileStorage = request.app.state.storage
    # `_digest` перематывает поток обратно сам — второй перемотки не нужно.
    digest = _digest(file.file)
    try:
        saved = storage.save(file.file, expected_sha256=digest)
    except ChecksumMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc

    stored = db.execute(
        select(StoredFile).where(
            StoredFile.organization_id == identity.organization.id,
            StoredFile.sha256 == saved.sha256,
        )
    ).scalar_one_or_none()
    if stored is None:
        stored = StoredFile(
            organization_id=identity.organization.id,
            uploaded_by_id=identity.user.id,
            original_name=file.filename or saved.sha256[:12],
            sha256=saved.sha256,
            size_bytes=saved.size_bytes,
            content_type=file.content_type or "",
        )
        db.add(stored)
        db.flush()

    done = _act(
        lambda: cards.attach(
            db,
            organization_id=identity.organization.id,
            card_id=card_id,
            file_id=stored.id,
            added_by=identity.user.id,
            folder_id=uuid.UUID(folder_id) if folder_id else None,
        )
    )
    db.commit()

    found = cards.files(db, organization_id=identity.organization.id, card_id=card_id)
    one = next((item for item in found if item.sha256 == saved.sha256), None)
    if one is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    return UploadedOut(**asdict(one), notice=_upload_notice(done, sent=file.filename or ""))


def _upload_notice(done: cards.Attached, *, sent: str) -> str:
    """Что сказать человеку про только что загруженный файл.

    Говорится только про неочевидное. Обычная загрузка проходит молча: файл
    виден в списке, и подпись «файл загружен» под ним ничего не добавляет.

    Сравнивается содержимое, а не имя, и об этом сказано прямо. Разница
    существенная: `Resume.pdf`, положенный в две папки, — один документ, и
    убрать его из первой правильно; два разных документа, названных
    одинаково, останутся двумя, и ни один не пропадёт.
    """
    if not done.known:
        return ""
    said = f"«{done.stored_name}» уже был приложен к лоту — содержимое совпадает побайтно"
    if sent.strip() and sent.strip() != done.stored_name:
        said += f", хотя загружали его под именем «{sent.strip()}»"
    if done.moved:
        came = f"«{done.moved_from}»" if done.moved_from else "общего списка"
        return f"{said}. Перенесли из {came}, второй записи не завели."
    # Не переехал — значит, остался там, где лежал, и в том месте, куда сейчас
    # смотрит человек, не появится. Сказать где — единственный способ не
    # оставить это выглядеть незагрузившимся.
    where = f"в папке «{done.folder}»" if done.folder else "в общем списке"
    return f"{said}. Лежит {where} — там и остался."


@router.get("/{card_id}/files/{sha256}", summary="Скачать файл лота")
def download_file(
    card_id: uuid.UUID,
    sha256: str,
    identity: CurrentUser,
    db: Db,
    request: Request,
    _guard: Guard = None,
) -> StreamingResponse:
    """Отдаёт файл, приложенный к этому лоту.

    Проверяется именно связь с лотом, а не только наличие файла в хранилище:
    хэш угадать нельзя, но он попадает в ссылки и в журнал, а по чужому лоту
    файлов видеть не полагается.
    """
    from platform_api.storage import FileStorage

    found = cards.files(db, organization_id=identity.organization.id, card_id=card_id)
    one = next((item for item in found if item.sha256 == sha256), None)
    if one is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файла нет у лота")

    storage: FileStorage = request.app.state.storage
    try:
        stream = storage.open(sha256)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return StreamingResponse(
        stream,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{one.sha256[:12]}"'},
    )


@router.delete("/files/{link_id}", summary="Убрать файл с лота", status_code=204)
def delete_file(link_id: uuid.UUID, identity: CurrentUser, db: Db, _guard: Guard = None) -> None:
    """Отвязывает файл. Из хранилища он не удаляется: тот же файл может быть
    приложен к соседнему лоту."""
    _act(lambda: cards.detach(db, organization_id=identity.organization.id, link_id=link_id))
    db.commit()


def _digest(stream: BinaryIO) -> str:
    """Хэш содержимого, посчитанный кусками.

    Кусками, а не `read()` целиком: файл прикладывают сканом на пятьдесят
    мегабайт, и целиком в памяти он лежит у каждого, кто грузит одновременно.
    Само хранилище тоже пишет потоком — читать всё в память ради одного числа
    значит свести эту работу на нет.
    """
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    stream.seek(0)
    return digest.hexdigest()


@router.get("/{card_id}", summary="Карточка лота")
def get_card(card_id: uuid.UUID, identity: CurrentUser, db: Db, _guard: Guard = None) -> CardOut:
    return _card_out(_one(db, identity, card_id))


@router.get("/{card_id}/history", summary="Кто работал над лотом")
def get_history(
    card_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    _guard: Guard = None,
) -> HistoryOut:
    """Лента действий по лоту и сводка по людям.

    Ради вопроса «кому платить премию». Из карточки этого не видно: она
    показывает итог, а по итогу премию делить нельзя — у лота, который вёл
    один человек, и у лота, прошедшего через пятерых, итог одинаковый.
    """
    events, workers, stages = _act(
        lambda: cards.history(db, organization_id=identity.organization.id, card_id=card_id)
    )
    return HistoryOut(
        events=[EventOut(**asdict(item)) for item in events],
        workers=[WorkerOut(**asdict(item)) for item in workers],
        stages=[StageOut(**asdict(item)) for item in stages],
    )


@router.post("/{card_id}/move", summary="Перевести на этап")
def post_move(
    card_id: uuid.UUID,
    body: MoveIn,
    request: Request,
    identity: CurrentUser,
    db: Db,
    _guard: Guard = None,
) -> CardOut:
    card = _act(
        lambda: cards.move(
            db,
            organization_id=identity.organization.id,
            card_id=card_id,
            role=identity.role,
            user_id=identity.user.id,
            to=body.to,
            reason=body.reason,
        )
    )
    job_id = _start_discussion(request, db, identity, card, to=body.to)
    db.commit()
    # После фиксации: исполнитель забирает задачу мгновенно и не найдёт
    # ни её, ни обсуждение, если транзакция ещё открыта.
    start.launch(request.app.state.settings, job_id)
    return _card_out(_one(db, identity, card_id))


def _start_discussion(
    request: Request,
    db: Db,
    identity: CurrentUser,
    card: LotCard,
    *,
    to: LotStatus,
) -> uuid.UUID | None:
    """Перевели в «Обсуждение» — заводим его и зовём модель писать.

    Раньше перевод менял только состояние карточки. Человек переводил лот,
    шёл в раздел обсуждений и своего лота там не находил: обсуждение заводила
    отдельная кнопка в разборе строки портала, и её надо было отыскать и
    нажать. Два способа сделать одно и то же, из которых работал один.

    Только для портала. На тендерный отбор обсуждение не распространяется:
    туда закупки приходят папкой по почте, обсуждать их не с кем.

    Ошибка здесь перевод не отменяет. Лот действительно перешёл в обсуждение,
    и откатывать это из-за недоступной базы портала значит врать о состоянии;
    обсуждение потом заводится кнопкой, как и раньше.
    """
    if to is not LotStatus.DISCUSSION or card.module != "goszakup":
        return None
    try:
        made = start.ensure(
            db,
            organization_id=identity.organization.id,
            user_id=identity.user.id,
            lot_number=card.row_id,
            settings=request.app.state.settings,
            redis=request.app.state.redis,
        )
    except Exception as exc:
        logger.warning(
            "Обсуждение по лоту не завелось",
            lot=card.row_id,
            error=str(exc),
        )
        return None
    return made.job_id


@router.post("/{card_id}/decide", summary="Участвуем или нет")
def post_decide(
    card_id: uuid.UUID,
    body: DecideIn,
    identity: CurrentUser,
    db: Db,
    _guard: Guard = None,
) -> CardOut:
    _act(
        lambda: cards.decide(
            db,
            organization_id=identity.organization.id,
            card_id=card_id,
            role=identity.role,
            participation=body.participation,
            reason=body.reason,
            user_id=identity.user.id,
        )
    )
    db.commit()
    return _card_out(_one(db, identity, card_id))


@router.post("/{card_id}/sign", summary="Подписать согласование")
def post_sign(
    card_id: uuid.UUID,
    body: SignIn,
    identity: CurrentUser,
    db: Db,
    _guard: Guard = None,
) -> CardOut:
    _act(
        lambda: cards.sign(
            db,
            organization_id=identity.organization.id,
            card_id=card_id,
            role=identity.role,
            user_id=identity.user.id,
            kind=body.kind,
            state=body.state,
            note=body.note,
        )
    )
    db.commit()
    return _card_out(_one(db, identity, card_id))


@router.post("/{card_id}/result", summary="Записать итоги подачи")
def post_result(
    card_id: uuid.UUID,
    body: ResultIn,
    identity: CurrentUser,
    db: Db,
    _guard: Guard = None,
) -> CardOut:
    """Цена, с которой выиграли, или победитель, если выиграли не мы.

    Записывается у поданного лота. У неподанного «выиграли за» означало бы,
    что итоги есть у закупки, в которой мы не участвовали.
    """
    _act(
        lambda: cards.result(
            db,
            organization_id=identity.organization.id,
            card_id=card_id,
            role=identity.role,
            won_amount=body.won_amount,
            winner=body.winner,
            user_id=identity.user.id,
        )
    )
    db.commit()
    return _card_out(_one(db, identity, card_id))


@router.post("/{card_id}/assign", summary="Назначить людей")
def post_assign(
    card_id: uuid.UUID,
    body: AssignIn,
    identity: CurrentUser,
    db: Db,
    _guard: Guard = None,
) -> CardOut:
    _act(
        lambda: cards.assign(
            db,
            organization_id=identity.organization.id,
            card_id=card_id,
            manager_id=body.manager_id,
            owner_id=body.owner_id,
            change_manager=body.change_manager,
            change_owner=body.change_owner,
            user_id=identity.user.id,
            role=identity.role,
        )
    )
    db.commit()
    return _card_out(_one(db, identity, card_id))


@router.post("/{card_id}/tasks", summary="Завести задачу", status_code=201)
def post_task(
    card_id: uuid.UUID,
    body: TaskIn,
    identity: CurrentUser,
    db: Db,
    request: Request,
    _guard: Guard = None,
) -> TaskOut:
    try:
        task = cards.add_task(
            db,
            organization_id=identity.organization.id,
            card_id=card_id,
            created_by=identity.user.id,
            title=body.title,
            department=body.department,
            body=body.body,
            assignee_id=body.assignee_id,
            due_at=body.due_at,
            settings=request.app.state.settings,
        )
    except SpokenError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return _task_out(db, identity, task.id)


@router.post("/tasks/{task_id}/close", summary="Закрыть задачу")
def post_close(
    task_id: uuid.UUID,
    body: CloseIn,
    identity: CurrentUser,
    db: Db,
    _guard: Guard = None,
) -> TaskOut:
    _act(
        lambda: cards.close_task(
            db,
            organization_id=identity.organization.id,
            task_id=task_id,
            state=body.state,
            result=body.result,
            user_id=identity.user.id,
            role=identity.role,
        )
    )
    db.commit()
    return _task_out(db, identity, task_id)


@router.post("/tasks/{task_id}/take", summary="Взять задачу себе")
def post_take(
    task_id: uuid.UUID,
    body: TakeIn,
    identity: CurrentUser,
    db: Db,
    request: Request,
    _guard: Guard = None,
) -> TaskOut:
    """Взять задачу себе, кому-то или вернуть её в очередь отдела.

    Срок не трогаем: его назвал тот, кто задачу завёл, — он знает, к какому
    часу нужен ответ.
    """
    _act(
        lambda: cards.take_task(
            db,
            organization_id=identity.organization.id,
            task_id=task_id,
            user_id=None if body.release else (body.assignee_id or identity.user.id),
            settings=request.app.state.settings,
        )
    )
    db.commit()
    return _task_out(db, identity, task_id)


class ColumnIn(BaseModel):
    key: str
    title: str
    width: int = 200
    filled_by: str = "hand"


class RowIn(BaseModel):
    key: str
    cells: dict[str, str] = {}


class SheetIn(BaseModel):
    """Таблица целиком. Приходит вся, а не по ячейке.

    Раздельная запись означала бы гонку между «переименовал столбец» и
    «дописал строку», сделанными в одном лоте одновременно двумя людьми.
    """

    columns: list[ColumnIn]
    rows: list[RowIn]


class SheetOut(BaseModel):
    """Разбор спецификации таблицей."""

    columns: list[ColumnIn]
    rows: list[RowIn]
    source_name: str = ""
    model: str = ""
    trouble: str = ""
    built_at: str = ""

    variant: str = "A"
    """Какой это вариант разбора."""

    variants: list[str] = []
    """Какие варианты есть у лота. «A» — всегда."""

    can: list[str] = []
    """Что можно сделать с вариантами: `branch`, `drop`.

    Списком с сервера, а не правилами в браузере: последний вариант удалять
    нельзя, и второй набор этого правила однажды разошёлся бы с первым — а
    человек нажал бы кнопку и получил отказ, уже будучи уверенным."""

    job_id: str = ""
    """Разбор, который идёт прямо сейчас. Пусто — не идёт.

    Отдаётся сервером, а не помнится браузером. Разбор запускается сам при
    взятии лота в работу, а карточку открывают позже и с другой машины: без
    этого поля человек видел бы пустую таблицу без объяснений, а прогон в это
    время шёл. Своё нажатие браузер помнит и сам, но полагаться на его память
    — значит показывать ход работы только тому, кто её начал."""


@router.get("/{card_id}/sheet", summary="Разбор спецификации таблицей")
def get_sheet(
    card_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    variant: Annotated[str, Query(description="Какой вариант читать")] = sheets.FIRST,
    _guard: Guard = None,
) -> SheetOut:
    """Отдаёт таблицу лота. Не собрана — пустая заготовка с тремя столбцами.

    Читать бесплатно: разбор моделью живёт в задаче и запускается кнопкой.
    Иначе открытая страница списывала бы со счёта, а F5 нажимают часто.
    """
    card = _card_row(db, identity, card_id)
    return _sheet_out(
        sheets.load(db, card, variant),
        running=_running_sheet(db, card, variant),
        letters=sheets.variants(db, card),
    )


def _running_sheet(db: Db, card: LotCard, variant: str = sheets.FIRST) -> uuid.UUID | None:
    """Разбор этого варианта, стоящий в очереди или идущий прямо сейчас.

    Именно варианта, а не лота: пересобирают обычно один из них, и признак,
    общий на все, зажигал бы «Модель разбирает…» в соседней таблице — той, где
    ничего не происходит. Кнопка «Разобрать» при этом гаснет, и человек ждёт
    работы, которую никто не начинал.

    У задач, поставленных до появления вариантов, поля `variant` в параметрах
    нет вовсе; такие считаются разбором «A» — других тогда и не было.
    """
    return (
        db.execute(
            select(Job.id)
            .where(
                Job.organization_id == card.organization_id,
                Job.module == card.module,
                Job.kind == "sheet",
                Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
                Job.params["card_id"].astext == str(card.id),
                func.coalesce(Job.params["variant"].astext, sheets.FIRST) == variant,
            )
            .order_by(Job.created_at.desc())
        )
        .scalars()
        .first()
    )


@router.put("/{card_id}/sheet", summary="Сохранить правки таблицы")
def put_sheet(
    card_id: uuid.UUID,
    body: SheetIn,
    identity: CurrentUser,
    db: Db,
    variant: Annotated[str, Query(description="Какой вариант правим")] = sheets.FIRST,
    _guard: Guard = None,
) -> SheetOut:
    """Сохраняет то, что человек изменил руками.

    Правки людей главнее разбора модели: строку про блок питания, которой в
    спецификации нет, дописывают именно здесь.
    """
    card = _card_row(db, identity, card_id)
    table = sheets.save(
        db,
        card,
        columns=[
            sheets.Column(key=i.key, title=i.title, width=i.width, filled_by=i.filled_by)
            for i in body.columns
        ],
        rows=[sheets.Row(key=i.key, cells=dict(i.cells)) for i in body.rows],
        variant=variant,
    )
    db.commit()
    return _sheet_out(table, letters=sheets.variants(db, card))


@router.post("/{card_id}/sheet/variants", summary="Завести вариант разбора", status_code=201)
def post_variant(
    card_id: uuid.UUID, identity: CurrentUser, db: Db, _guard: Guard = None
) -> SheetOut:
    """Заводит следующий вариант от «A».

    Требования заказчика в нём те же — их переписывают не мы, — а свои столбцы
    пустые: вариант затем и нужен, чтобы предложить тот же лот иначе.
    """
    card = _card_row(db, identity, card_id)
    letter = _act(lambda: sheets.branch(db, card))
    db.commit()
    return _sheet_out(sheets.load(db, card, letter), letters=sheets.variants(db, card))


@router.delete("/{card_id}/sheet/variants/{variant}", summary="Убрать вариант разбора")
def delete_variant(
    card_id: uuid.UUID, variant: str, identity: CurrentUser, db: Db, _guard: Guard = None
) -> SheetOut:
    """Убирает вариант и отдаёт тот, что остался первым."""
    card = _card_row(db, identity, card_id)
    _act(lambda: sheets.drop(db, card, variant))
    db.commit()
    letters = sheets.variants(db, card)
    return _sheet_out(sheets.load(db, card, letters[0]), letters=letters)


@router.post("/{card_id}/sheet", summary="Разобрать спецификацию моделью", status_code=202)
def start_sheet(
    card_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    request: Request,
    variant: Annotated[str, Query(description="Какой вариант пересобрать")] = sheets.FIRST,
    _guard: Guard = None,
) -> StartedJobOut:
    """Ставит разбор спецификации в очередь.

    Задачей, а не в запросе: модель думает над тремя тысячами знаков минуту с
    лишним, и обработчик, который столько держит соединение, — это истёкший
    срок у человека и повторное нажатие поверх идущей работы. Заодно это
    деньги, а платное в платформе всегда за кнопкой.
    """
    card = _card_row(db, identity, card_id)
    settings: Settings = request.app.state.settings
    job = JobService(db, request.app.state.redis).create(
        organization_id=identity.organization.id,
        created_by_id=identity.user.id,
        module=card.module,
        kind="sheet",
        params={"card_id": str(card_id), "variant": variant},
        total=1,
    )
    db.commit()
    enqueue_sync(settings, job.id)
    return StartedJobOut(job_id=job.id)


def _card_row(db: Db, identity: CurrentUser, card_id: uuid.UUID) -> LotCard:
    """Сама запись карточки, а не её показ.

    Таблице нужны площадка и устойчивое имя строки — по ним она и хранится.
    Показ (`cards.Card`) их тоже несёт, но он собран под экран и режется по
    ролям; ключ хранения не должен зависеть от того, кто смотрит.
    """
    found = db.execute(
        select(LotCard).where(
            LotCard.id == card_id, LotCard.organization_id == identity.organization.id
        )
    ).scalar_one_or_none()
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Такого лота нет")
    return found


def _sheet_out(
    table: sheets.Table,
    *,
    running: uuid.UUID | None = None,
    letters: list[str] | None = None,
) -> SheetOut:
    known = letters or [table.variant]
    return SheetOut(
        variant=table.variant,
        variants=known,
        can=[
            *(["branch"] if len(known) < sheets.MAX_VARIANTS else []),
            # Последний вариант не удаляется: лот без разбора — пустая
            # вкладка, а завести его заново можно только прогоном модели.
            *(["drop"] if len(known) > 1 else []),
        ],
        job_id=str(running) if running else "",
        columns=[
            ColumnIn(key=c.key, title=c.title, width=c.width, filled_by=c.filled_by)
            for c in table.columns
        ],
        rows=[RowIn(key=r.key, cells=r.cells) for r in table.rows],
        source_name=table.source_name,
        model=table.model,
        trouble=table.trouble,
        built_at=table.built_at,
    )


def _one(db: Db, identity: CurrentUser, card_id: uuid.UUID) -> cards.Card:
    try:
        return cards.one(
            db,
            organization_id=identity.organization.id,
            card_id=card_id,
            role=identity.role,
            user_id=identity.user.id,
        )
    except SpokenError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _task_out(db: Db, identity: CurrentUser, task_id: uuid.UUID) -> TaskOut:
    try:
        one = cards.task(db, organization_id=identity.organization.id, task_id=task_id)
    except SpokenError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return TaskOut(**asdict(one))


def _act[T](what: Callable[[], T]) -> T:
    """Переводит отказ службы в ответ 403 и отдаёт её итог.

    Именно 403: все отказы здесь про право сделать шаг, а не про испорченные
    данные, и человеку нужно понять, что дело в роли или в порядке работы.
    """
    try:
        return what()
    except SpokenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


def _card_out(item: cards.Card) -> CardOut:
    fields = asdict(item)
    fields["can"] = list(item.can)
    fields["approvals"] = [SignOut(**asdict(sign)) for sign in item.approvals]
    fields["amount"] = float(item.amount) if item.amount is not None else None
    fields["won_amount"] = float(item.won_amount) if item.won_amount is not None else None
    return CardOut(**fields)


__all__ = ["router"]
