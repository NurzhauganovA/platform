"""Эндпоинты модуля OMarket."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from platform_api.auth.dependencies import CurrentUser, Db, requires_money, requires_read
from platform_api.config import Settings
from platform_api.jobs import JobService
from platform_api.jobs.worker import enqueue_sync
from platform_api.modules.detail import for_role
from platform_api.modules.omarket import core
from platform_api.modules.omarket.columns import COMPACT, ESSENTIAL, POLICY, ROLES
from platform_api.modules.omarket.health import check as check_health
from platform_api.modules.omarket.schemas import ModuleHealth
from platform_api.modules.schemas import (
    ColumnOut,
    DetailOut,
    LegendItem,
    RowOut,
    StartedJobOut,
    WorklistOut,
)
from platform_api.modules.table import build_table, sees_money

router = APIRouter(prefix="/omarket", tags=["OMarket"])


@router.get("/health", summary="Готовность модуля")
def get_health() -> ModuleHealth:
    """Что настроено, а что нет.

    Спрашивается до запуска прогона: он идёт минутами и стоит денег, а
    «не задан ключ» должно всплыть раньше, чем человек начнёт ждать.
    """
    return ModuleHealth.model_validate(check_health())


@router.get("/worklist", summary="Рабочий список предзаказов")
def get_worklist(
    identity: CurrentUser,
    _guard: Annotated[None, requires_read] = None,
) -> WorklistOut:
    """Предзаказы так же, как их показывает лист «Фокус (что смотреть)».

    Колонки, их порядок, сортировка и значения берутся из книги Excel того же
    проекта: человек сверяет экран с выгруженным файлом, и расхождение в них —
    это полчаса на выяснение, кто из двух прав.

    `focus` — только то, с чем можно что-то сделать. `all` добавляет закрытые
    по признакам площадки и заведомо невыгодные: их не прячут совсем, иногда
    надо посмотреть, почему предзаказ отсеялся.

    Ответ не стоит денег и не ходит в сеть: оценки лежат в базе готовыми.
    """
    try:
        data = core.worklist()
    except Exception as exc:
        # База ядра может быть ещё не создана — это не поломка платформы,
        # а состояние, о котором должна сказать сводка готовности.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Данные OMarket недоступны: {exc}",
        ) from exc

    table = build_table(
        core.focus_columns(),
        data.rows,
        policy=POLICY,
        role=identity.role,
        tone=core.tone_of,
        focus=core.in_focus,
        identity=core.row_id,
        deadline=core.row_deadline,
        essential=ESSENTIAL,
        compact=COMPACT,
        roles=ROLES,
    )
    money = sees_money(identity.role)

    return WorklistOut(
        sheet=core.sheet_title(),
        legend=[
            LegendItem(tone=tone, title=title, hint=hint) for tone, title, hint in core.legend()
        ],
        # Обновление — всем, кто работает с разделом: оно бесплатно и ждать
        # ради него тендерщика незачем. Пересчёт ходит в модель за деньги, а в
        # книге себестоимость и маржа целиком — и то и другое закрыто тем же
        # `requires_money`, что и эндпоинты. Кнопка, которая ответит 403, —
        # это обещание, которого раздел не выполнит.
        actions=["sync"] + (["analyze", "export"] if money else []),
        columns=[ColumnOut.model_validate(asdict(item)) for item in table.columns],
        rows=[RowOut.model_validate(asdict(row)) for row in table.rows],
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


@router.get("/item/{item_id}", summary="Разбор одной строки")
def get_detail(
    item_id: str,
    identity: CurrentUser,
    _guard: Annotated[None, requires_read] = None,
) -> DetailOut:
    """Откуда взялась цифра: решение, деньги, где взять, что проверить.

    Тому же порядку следует лист разбора в книге. Разделы с деньгами не уходят
    закупщику — так же, как колонки в таблице, и по той же причине: спрятать в
    браузере и отдать в JSON значит отдать.
    """
    try:
        found = core.detail(item_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Данные недоступны: {exc}",
        ) from exc

    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Такого предзаказа нет среди актуальных",
        )
    return DetailOut.model_validate(asdict(for_role(found, identity.role)))


@router.post("/sync", summary="Обновить данные с площадки", status_code=status.HTTP_202_ACCEPTED)
def start_sync(
    identity: CurrentUser,
    db: Db,
    request: Request,
    with_details: bool = True,
    _guard: Annotated[None, requires_read] = None,
) -> StartedJobOut:
    """Ставит в очередь выгрузку предзаказов, карточек и склада.

    Бесплатная операция: идёт в кабинет площадки и модель не трогает. Поэтому
    доступна всем, кто работает с разделом.

    Работает на сессии, снятой при `omarket login`: вход по ЭЦП идёт в окне
    браузера на машине сотрудника. Без живой сессии задача не пойдёт в кабинет
    вслепую, а вернётся с указанием, что сделать.
    """
    settings: Settings = request.app.state.settings
    job = JobService(db, request.app.state.redis).create(
        organization_id=identity.organization.id,
        created_by_id=identity.user.id,
        module="omarket",
        kind="sync",
        params={"with_details": with_details},
        total=3,
    )
    # Фиксируем до постановки в очередь: исполнитель заберёт задачу мгновенно
    # и не найдёт её в базе, если транзакция ещё не закрыта.
    db.commit()
    enqueue_sync(settings, job.id)
    return StartedJobOut(job_id=job.id)


@router.post("/analyze", summary="Пересчитать себестоимость и маржу", status_code=202)
def start_analyze(
    identity: CurrentUser,
    db: Db,
    request: Request,
    search_market: bool = True,
    _guard: Annotated[None, requires_money] = None,
) -> StartedJobOut:
    """Ставит в очередь расчёт себестоимости.

    Только тендерщику, и не из-за секретности: с поиском на внешних рынках
    прогон стоит денег. Кнопка, которая тратит бюджет, должна быть у того, кто
    за него отвечает.
    """
    settings: Settings = request.app.state.settings
    job = JobService(db, request.app.state.redis).create(
        organization_id=identity.organization.id,
        created_by_id=identity.user.id,
        module="omarket",
        kind="analyze",
        params={"search_market": search_market},
        total=1,
    )
    db.commit()
    enqueue_sync(settings, job.id)
    return StartedJobOut(job_id=job.id)


@router.get("/export", summary="Выгрузить книгу Excel")
def export(
    identity: CurrentUser,
    _guard: Annotated[None, requires_money] = None,
) -> FileResponse:
    """Отдаёт ту же книгу, что делает `omarket export`.

    Только тендерщику: в книге листы с себестоимостью и маржой целиком, и
    урезать их по ролям здесь нечем — файл уходит одним куском и дальше живёт
    своей жизнью, в почте и на флешках.

    Собирается синхронно, а не задачей: книга строится по уже посчитанным
    оценкам, без обращений к складу и модели, и это секунды.
    """
    del identity
    try:
        path = core.export_workbook()
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


__all__ = ["router"]
