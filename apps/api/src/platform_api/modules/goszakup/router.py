"""Эндпоинты модуля госзакупок."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from platform_api.auth.dependencies import CurrentUser, Db, requires_read, requires_remarks
from platform_api.config import Settings
from platform_api.db.models import Role
from platform_api.errors import unavailable
from platform_api.jobs.service import JobService
from platform_api.jobs.worker import enqueue_sync
from platform_api.modules import codes, discussion
from platform_api.modules.goszakup import core, purge, start
from platform_api.modules.goszakup.columns import (
    CODE_PREFIX,
    CODE_SEPARATOR,
    CODE_WIDTH,
    COMPACT,
    ESSENTIAL,
    POLICY,
    ROLES,
)
from platform_api.modules.goszakup.health import check as check_health
from platform_api.modules.goszakup.schemas import (
    CategoryIn,
    ModuleHealth,
    PlatformIn,
    RemarkStartedOut,
    WatchedCodeIn,
    WatchedCodeOut,
)
from platform_api.modules.schemas import (
    ColumnOut,
    DetailOut,
    LegendItem,
    RowLotOut,
    RowOut,
    Scope,
    StartedJobOut,
    WorklistOut,
    in_scope,
)
from platform_api.modules.table import build_table

router = APIRouter(prefix="/goszakup", tags=["Госзакупки"])


@router.get("/health", summary="Готовность модуля")
def get_health() -> ModuleHealth:
    return ModuleHealth.model_validate(check_health())


@router.get("/worklist", summary="Лоты госзакупок")
def get_worklist(
    identity: CurrentUser,
    db: Db,
    scope: Scope = "focus",
    _guard: Annotated[None, requires_read] = None,
) -> WorklistOut:
    """Лоты портала так же, как их показывает лист «ГЗ» рабочей книги.

    Ничего не запускает и не ходит в сеть: обход портала — отдельная задача с
    кнопкой. Иначе обновление страницы било бы по государственному порталу, а
    F5 в отделе нажимают часто.
    """
    try:
        data = core.worklist()
    except Exception as exc:
        raise unavailable("Госзакупки", exc) from exc

    table = build_table(
        core.columns(),
        data.rows,
        policy=POLICY,
        role=identity.role,
        tone=core.tone_of,
        focus=core.in_focus,
        identity=core.row_id,
        deadline=core.row_deadline,
        essential=tuple(ESSENTIAL),
        compact=COMPACT,
        roles=ROLES,
    )

    # Счётчики обсуждения — одним запросом на весь список: строк сотни, а
    # обращение на каждую было бы сотнями запросов ради нескольких десятков
    # веток.
    rows = [RowOut.model_validate(asdict(item)) for item in table.rows]
    _mark_announces(rows, data.rows)
    issued = codes.assign(
        db,
        "goszakup",
        CODE_PREFIX,
        [row.id for row in rows if row.id],
        width=CODE_WIDTH,
        separator=CODE_SEPARATOR,
    )
    db.commit()
    for row in rows:
        row.code = issued.get(row.id, "")

    threads = discussion.summaries(
        db, identity.organization.id, "goszakup", [row.id for row in rows if row.id]
    )
    for row in rows:
        found = threads.get(row.id)
        if found is not None:
            row.discussion, row.discussion_last = found.count, found.last

    # Собранные строки нужны дважды: отобранные уезжают, полное число
    # показывается плиткой «Показано 28 из 184».
    _ready = rows

    return WorklistOut(
        sheet=core.sheet_title(),
        columns=[ColumnOut.model_validate(asdict(item)) for item in table.columns],
        rows=in_scope(_ready, scope),
        rows_total=len(_ready),
        legend=[
            LegendItem(tone=tone, title=title, hint=hint) for tone, title, hint in core.legend()
        ],
        actions=["sync"],
        hidden_columns=table.hidden_columns,
        total=data.total,
        shown=data.live,
        expired=data.total - data.live,
        verdicts={},
        margin_total=None,
        priced=data.total,
        analyzed=bool(data.total),
        urgent_hours=core.URGENT_HOURS,
    )


def _mark_announces(rows: list[RowOut], source: Sequence[Any]) -> None:
    """Отмечает лоты, пришедшие из одного объявления.

    В объявлении бывает четыре лота, а мы берём их по своим кодам ЕНС ТРУ
    вразнобой — и в списке они оказываются в разных местах, как четыре разные
    закупки. Между тем это одна: срок один, документы общие, и заявка подаётся
    сразу на всё, что из неё берут.

    Отметка та же, что у объединённых позиций тендерного отбора: таблица уже
    умеет ставить такие строки рядом и сворачивать их в одну. Заводить второй
    способ показывать «это вместе» значит рисовать одно и то же дважды.

    Объявление с одним нашим лотом не отмечается: пометка «1 лот» ничего не
    сообщает, а строку сворачивает.
    """
    counts: dict[int, int] = {}
    for item in source:
        counts[item.announce_id] = counts.get(item.announce_id, 0) + 1

    for row, item in zip(rows, source, strict=False):
        if counts.get(item.announce_id, 0) < 2:
            continue
        row.lot = RowLotOut(
            key=str(item.announce_id),
            positions=counts[item.announce_id],
            unit=("лот", "лота", "лотов"),
            whole="объявление",
            whole_of="объявления",
            hint="Заявка подаётся по каждому лоту отдельно, срок и документы общие.",
        )


@router.get("/item/{item_id}", summary="Разбор лота")
def get_item(
    item_id: str,
    identity: CurrentUser,
    db: Db,
    facts: Annotated[
        bool, Query(description="Только сроки и что покупают, без похода на портал")
    ] = False,
    _guard: Annotated[None, requires_read] = None,
) -> DetailOut:
    """Что за лот и что ещё в этом объявлении.

    Сам лот берётся из базы — он там уже лежит. Соседние лоты объявления
    читаются с портала при открытии: под наши коды из объявления подходит
    одна позиция из четырёх, а торги идут по объявлению целиком.

    Один запрос к порталу на открытие. Держать чужие позиции в базе незачем:
    они меняются вместе с объявлением, а смотрят их один раз — когда решают,
    браться ли.

    `facts=1` этого запроса не делает: карточка лота открывает панель ради
    сроков и предмета, а портал отвечает до минуты, и однажды не отвечает
    вовсе. Ждать чужой сервер ради раздела, который в этом режиме не
    рисуется, — минута на нажатие, которое делают по нескольку раз за лот.
    """
    from goszakup.infrastructure.db.models import LotRecord
    from sqlalchemy import select

    from platform_api.modules.goszakup import detail as lot_detail

    # Сессия площадки названа отдельно, а не `db`. Под тем же именем она
    # перекрывала сессию платформы, и код строки искался в базе площадки —
    # там таблицы кодов нет вовсе, и разбор падал пятисотой на каждом
    # открытии. Ошибка тихая: обе переменные сессии, типы совпадают.
    with core.session() as portal:
        # По номеру лота, а не закупки. Номер закупки у объявления с четырьмя
        # лотами один на всех, и разбор открывал тот, который первым вернула
        # база: человек нажимал на компрессор и читал спецификацию фильтра.
        #
        # Запасной поиск по номеру закупки оставлен для ссылок, разосланных до
        # этой правки, и для карточек, заведённых тогда же. Однозначен он не
        # всегда, поэтому только вторым заходом.
        found = (
            portal.execute(select(LotRecord).where(LotRecord.lot_number == item_id))
            .scalars()
            .first()
            or portal.execute(select(LotRecord).where(LotRecord.purchase_number == item_id))
            .scalars()
            .first()
        )
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Такого лота в базе нет"
            )
        # Устойчивый код живёт в базе платформы. Ключ — номер лота: у
        # объявления с четырьмя лотами номер закупки один на всех.
        code = codes.assign(
            db,
            module="goszakup",
            prefix=CODE_PREFIX,
            keys=[found.lot_number],
            width=CODE_WIDTH,
            separator=CODE_SEPARATOR,
        ).get(found.lot_number, "")

        # Разделов, закрытых от роли, здесь нет: плановая сумма заказчика
        # открыта на портале любому участнику, а своей себестоимости по
        # госзакупкам мы пока не считаем. Появится — появится и разделение.
        return lot_detail.build(found, code=code, facts=facts)


@router.post("/sync", summary="Обновить лоты с портала", status_code=status.HTTP_202_ACCEPTED)
def start_sync(
    identity: CurrentUser,
    db: Db,
    request: Request,
    _guard: Annotated[None, requires_read] = None,
) -> StartedJobOut:
    """Ставит в очередь обход портала — тот же, что идёт каждый час.

    Кнопка нужна не вместо расписания, а рядом с ним. Объявление вешают
    посреди дня, срок подачи у запроса ценовых предложений — двое суток, и
    ждать ближайшего часа означает потерять час из сорока восьми. Человек,
    которому позвонили про закупку, должен увидеть её сейчас.

    Бесплатно: открытое API портала не требует ни токена, ни ЭЦП, и модель
    здесь не участвует. Поэтому доступно всем, кто работает с разделом, —
    ждать тендерщика ради обновления списка незачем.

    Вид задачи — `harvest`, тот же, что у почасовой: исполнитель ищет
    обработчик по паре «модуль и вид», и `sync` он бы не нашёл. Кнопка на
    экране называется «Обновить данные» одинаково во всех разделах.
    """
    settings: Settings = request.app.state.settings
    job = JobService(db, request.app.state.redis).create(
        organization_id=identity.organization.id,
        created_by_id=identity.user.id,
        module="goszakup",
        kind="harvest",
        params={},
        total=1,
    )
    # Фиксируем до постановки в очередь: исполнитель заберёт задачу мгновенно
    # и не найдёт её в базе, если транзакция ещё не закрыта.
    db.commit()
    enqueue_sync(settings, job.id)
    return StartedJobOut(job_id=job.id)


@router.post(
    "/lots/{lot_number}/remark",
    summary="Завести обсуждение по лоту",
    status_code=status.HTTP_202_ACCEPTED,
)
def start_remark(
    lot_number: str,
    identity: CurrentUser,
    db: Db,
    request: Request,
    _guard: Annotated[None, requires_remarks] = None,
) -> RemarkStartedOut:
    """Заводит замечание к спецификации лота и ставит написание в очередь.

    Та же дверь, что и перевод карточки в «Обсуждение» на доске: обе ведут в
    `start.ensure`. Пока логика лежала здесь, второй путь молча ничего не
    заводил — человек переводил лот и не находил его в разделе обсуждений.

    Нажатие повторно ничего не ломает: обсуждение по лоту одно, а написание
    ставится только пока текста нет.
    """
    settings: Settings = request.app.state.settings
    try:
        made = start.ensure(
            db,
            organization_id=identity.organization.id,
            user_id=identity.user.id,
            lot_number=lot_number,
            settings=settings,
            redis=request.app.state.redis,
        )
    except start.LotMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Такого лота в базе нет"
        ) from exc

    # Фиксируем до постановки в очередь: исполнитель заберёт задачу мгновенно
    # и не найдёт ни задачу, ни обсуждение, если транзакция ещё не закрыта.
    db.commit()
    start.launch(settings, made.job_id)
    return RemarkStartedOut(remark_id=str(made.remark.id), job_id=made.job_id)


@router.get("/codes", summary="Коды ЕНС ТРУ, по которым идёт обход")
def list_codes(
    identity: CurrentUser,
    _guard: Annotated[None, requires_read] = None,
) -> list[WatchedCodeOut]:
    """Список кодов вместе с выключенными.

    Выключенные показываются всем, у кого есть доступ к разделу: по ним видно,
    что раздел не показывает не потому, что закупок нет, а потому что код
    убрали.
    """
    from goszakup.application import catalog

    with core.session() as db:
        found = catalog.watched(db, only_active=False)
    return [WatchedCodeOut(**asdict(item)) for item in found]


@router.post("/codes", summary="Добавить код", status_code=status.HTTP_201_CREATED)
def add_code(
    body: WatchedCodeIn,
    identity: CurrentUser,
    _guard: Annotated[None, requires_read] = None,
) -> WatchedCodeOut:
    """Добавляет код в список обхода. Только администратору.

    Список задаёт, что вообще попадёт в отбор: код, добавленный по ошибке, —
    это сотни чужих лотов в списке и запросы к государственному порталу за
    ними. Решение о номенклатуре принимает тот, кто за неё отвечает.
    """
    from goszakup.application import catalog
    from goszakup.exceptions import GoszakupError

    _only_admin(identity)
    try:
        with core.session() as db:
            added = catalog.add(
                db,
                body.code,
                note=body.note,
                category=body.category,
                platform=body.platform,
            )
            db.commit()
    except GoszakupError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return WatchedCodeOut(**asdict(added))


@router.put("/codes/{code}/category", summary="Категория кода")
def put_category(
    code: str,
    body: CategoryIn,
    identity: CurrentUser,
    _guard: Annotated[None, requires_read] = None,
) -> WatchedCodeOut:
    """Меняет нашу категорию товара у кода.

    Отдельно от добавления: коды заводят пачкой, а категории пересматривают
    позже — когда становится ясно, кто что ведёт.
    """
    from goszakup.application import catalog
    from goszakup.exceptions import GoszakupError

    _only_admin(identity)
    try:
        with core.session() as db:
            catalog.set_category(db, code, body.category)
            db.commit()
            found = next(
                item for item in catalog.watched(db, only_active=False) if item.code == code
            )
    except GoszakupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return WatchedCodeOut(**asdict(found))


@router.put("/codes/{code}/platform", summary="Площадка кода")
def put_platform(
    code: str,
    body: PlatformIn,
    identity: CurrentUser,
    _guard: Annotated[None, requires_read] = None,
) -> WatchedCodeOut:
    """Меняет площадку, на которой ищется этот код.

    Отдельно от добавления: коды заводят пачкой, а площадку уточняют потом —
    когда видно, где под этот код закупок больше.
    """
    from goszakup.application import catalog
    from goszakup.exceptions import GoszakupError

    _only_admin(identity)
    try:
        with core.session() as db:
            catalog.set_platform(db, code, body.platform)
            db.commit()
            found = next(
                item for item in catalog.watched(db, only_active=False) if item.code == code
            )
    except GoszakupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return WatchedCodeOut(**asdict(found))


@router.delete("/codes/{code}", summary="Убрать код", status_code=status.HTTP_204_NO_CONTENT)
def drop_code(
    code: str,
    identity: CurrentUser,
    _guard: Annotated[None, requires_read] = None,
) -> None:
    """Выключает код: обход его больше не берёт, строка остаётся.

    Остаётся намеренно — выключают обычно временно, и восстановить проще, чем
    набирать двенадцать цифр заново.
    """
    from goszakup.application import catalog
    from goszakup.exceptions import GoszakupError

    _only_admin(identity)
    try:
        with core.session() as db:
            catalog.drop(db, code)
            db.commit()
    except GoszakupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/item/{item_id}/spec", summary="Файл технической спецификации")
def get_spec_file(
    item_id: str,
    identity: CurrentUser,
    _guard: Annotated[None, requires_read] = None,
) -> StreamingResponse:
    """Отдаёт сам документ спецификации, а не только его текст.

    Через нас, а не ссылкой на портал. Ссылка ведёт на соседний хост портала,
    живёт вместе с его выкладками и в один прекрасный день перестанет
    открываться; к тому же по ней приходит имя вида `file_1837462.docx`, по
    которому в папке «Загрузки» ничего не найти.

    Текст остаётся рядом: по нему идёт разбор и поиск, а файл нужен, когда
    спецификацию отправляют технологу или прикладывают к заявке. Одно другого
    не заменяет — текст нельзя подписать, а файл нельзя прочитать глазами в
    списке.
    """
    from goszakup.infrastructure.db.models import LotRecord
    from goszakup.infrastructure.http import PortalClient
    from sqlalchemy import select

    with core.session() as portal:
        found = (
            portal.execute(select(LotRecord).where(LotRecord.lot_number == item_id))
            .scalars()
            .first()
        )
        if found is None or not found.spec_url:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="У этого лота спецификация не приложена",
            )
        url, name = found.spec_url, found.spec_name or "specification"

    try:
        with PortalClient(core.core_settings().http) as client:
            body = client.get_bytes(url)
    except Exception as exc:
        raise unavailable("Портал госзакупок", exc) from exc

    # Имя файла в кавычках и отдельно в UTF-8: спецификации зовутся
    # по-русски, а без `filename*` браузер сохраняет их как «______.docx».
    quoted = quote(name)
    return StreamingResponse(
        iter((body,)),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )


class PurgeOut(BaseModel):
    """Сколько записей удалено или будет удалено."""

    lots: int
    cards: int
    remarks: int
    messages: int
    codes: int
    total: int


@router.get("/purge", summary="Что удалится при очистке раздела")
def preview_purge(
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_read] = None,
) -> PurgeOut:
    """Показывает объём до нажатия.

    Соглашаться человек должен на число, а не на слово «всё»: за карточками и
    репликами стоит чужая работа, и увидеть её объём он должен заранее.
    """
    _only_admin(identity)
    ahead = purge.count(db)
    return PurgeOut(**asdict(ahead), total=ahead.total)


@router.delete("/lots", summary="Удалить все лоты портала", status_code=status.HTTP_200_OK)
def purge_lots(
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_read] = None,
) -> PurgeOut:
    """Стирает лоты площадки и всё, что к ним приросло.

    Только администратору. Отменить нельзя: карточки, обсуждения и устойчивые
    коды удаляются вместе с лотами — оставить их значило бы получить карточку
    без закупки и код, который завтра выдастся чужому товару.

    Список кодов ЕНС ТРУ остаётся: это настройка обхода, а не данные.
    """
    _only_admin(identity)
    cleared = purge.run(db)
    db.commit()
    return PurgeOut(**asdict(cleared), total=cleared.total)


@router.put("/codes/{code}/active", summary="Вернуть код в обход")
def revive_code(
    code: str,
    identity: CurrentUser,
    _guard: Annotated[None, requires_read] = None,
) -> WatchedCodeOut:
    """Включает выключенный код обратно.

    Обратная сторона выключения. Без неё выключенный код оставался строкой,
    которую нечем вернуть: приходилось заводить его заново, теряя категорию и
    площадку, — а выключают обычно временно.
    """
    from goszakup.application import catalog
    from goszakup.exceptions import GoszakupError

    _only_admin(identity)
    try:
        with core.session() as db:
            back = catalog.revive(db, code)
            db.commit()
    except GoszakupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return WatchedCodeOut.model_validate(asdict(back))


def _only_admin(identity: CurrentUser) -> None:
    if identity.role is not Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Менять список кодов ЕНС ТРУ может только администратор",
        )


__all__ = ["router"]
