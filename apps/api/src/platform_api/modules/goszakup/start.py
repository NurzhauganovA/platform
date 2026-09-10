"""Заведение обсуждения по лоту портала и запуск написания.

Отдельным файлом, потому что зовут отсюда двое: кнопка «Обсудить» в разборе
лота и перевод карточки в состояние «Обсуждение» на доске. Пока это лежало
внутри обработчика кнопки, второй путь молча ничего не заводил: человек
переводил лот в обсуждение, попадал в раздел обсуждений и не находил там
своего лота — его надо было отдельно отыскать в списке портала и нажать
кнопку ещё раз.

Обе двери ведут в одно и то же: одно обсуждение на лот и одно написание.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from platform_api.config import Settings
from platform_api.db.models import Discussion, DiscussionWriting, Job, JobStatus
from platform_api.jobs import JobService
from platform_api.jobs.worker import enqueue_sync
from platform_api.logging import get_logger
from platform_api.modules import codes
from platform_api.modules.goszakup import core
from platform_api.modules.remarks import Subject, open_remark

logger = get_logger(__name__)

CODE_PREFIX = "GZ"
CODE_WIDTH = 6
CODE_SEPARATOR = ""


class LotMissingError(Exception):
    """Такого лота в базе портала нет."""


@dataclass(frozen=True, slots=True)
class Started:
    """Что получилось: обсуждение и задача написания, если её ставили."""

    remark: Discussion
    job_id: uuid.UUID | None
    """`None` — писать не стали: текст уже есть или написание уже идёт."""


def ensure(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID | None,
    lot_number: str,
    settings: Settings,
    redis: Any,
) -> Started:
    """Заводит обсуждение по лоту и, если нужно, ставит написание в очередь.

    Ключ — номер лота, а не номер закупки. У объявления с четырьмя лотами
    номер закупки один на всех, и замечание ушло бы заказчику про чужой товар.

    Срок считается от публикации объявления: два рабочих дня, как их даёт
    закон. Портал своих полей не отдаёт — `discussion_start_date` и
    `discussion_end_date` в открытом API приходят пустыми и у запроса ценовых
    предложений, и у конкурса, проверено на живых объявлениях. Раньше вместо
    них подставлялось окончание приёма заявок, и «осталось» показывало неделю
    там, где на замечание оставался день.

    Написание ставится один раз. Модель стоит денег, а сюда приходят и
    перетаскиванием: лот, поводивший туда-обратно между колонками, оплатил бы
    каждый заход.
    """
    from goszakup.infrastructure.db.models import LotRecord

    with core.session() as portal:
        found = (
            portal.execute(select(LotRecord).where(LotRecord.lot_number == lot_number))
            .scalars()
            .first()
        )
        if found is None:
            raise LotMissingError(lot_number)
        subject = Subject(
            code=codes.assign(
                db,
                module="goszakup",
                prefix=CODE_PREFIX,
                keys=[lot_number],
                width=CODE_WIDTH,
                separator=CODE_SEPARATOR,
            ).get(lot_number, ""),
            title=found.name or found.enstru_name,
            customer=found.customer,
            amount=found.amount,
            enstru_code=found.enstru_code,
            category=found.enstru_name,
            deadline=discussion_deadline(found),
        )

    remark = open_remark(
        db,
        organization_id=organization_id,
        module="goszakup",
        row_id=lot_number,
        subject=subject,
    )

    if not _needs_writing(db, organization_id, remark):
        return Started(remark=remark, job_id=None)

    job = JobService(db, redis).create(
        organization_id=organization_id,
        created_by_id=user_id,
        module="goszakup",
        kind="remark",
        params={"remark_id": str(remark.id)},
        total=3,
    )
    remark.writing = DiscussionWriting.QUEUED
    db.flush()
    return Started(remark=remark, job_id=job.id)


DISCUSSION_DAYS = 2
"""Сколько рабочих дней даётся на предварительное обсуждение.

Закон о государственных закупках: замечания к проекту документации подаются
в течение двух рабочих дней со дня размещения объявления.
"""


def discussion_deadline(lot: Any) -> datetime | None:
    """До какого момента принимаются замечания.

    Считается, а не читается: портал в открытой части оба своих поля
    (`discussion_start_date`, `discussion_end_date`) отдаёт пустыми — и у
    запроса ценовых предложений, и у конкурса. Если он однажды начнёт их
    заполнять, заполненное и победит: свой расчёт — замена, а не правило.

    Выходные пропускаются, праздники — нет. Календаря праздников у нас не
    заведено, а придуманный по памяти хуже отсутствующего: он ошибётся молча,
    и ошибётся в сторону «ещё есть время». Считанный срок поэтому и помечен на
    экране расчётным.

    Публикации нет — остаётся окончание приёма заявок: срок заведомо поздний,
    но пустое «осталось» в карточке читается как «обсуждать не надо».
    """
    filled = getattr(lot, "discussion_end", None)
    if filled is not None:
        return cast("datetime", filled)

    published = getattr(lot, "published_at", None)
    if published is None:
        return cast("datetime | None", getattr(lot, "end_date", None))

    moment = cast("datetime", published)
    left = DISCUSSION_DAYS
    while left:
        moment += timedelta(days=1)
        # 5 и 6 — суббота и воскресенье.
        if moment.weekday() < 5:
            left -= 1
    return moment


def stop_writing(
    db: DbSession,
    *,
    organization_id: uuid.UUID,
    lot_number: str,
    redis: Any,
) -> Discussion | None:
    """Прекращает написание замечания: снимает задачу и отпускает обсуждение.

    Нужна не для экономии, а чтобы выбраться. Пока задача числится идущей,
    кнопка «написать» заперта — иначе одно нажатие стоило бы двух вызовов
    модели. Значит, любой сбой на её стороне запирает обсуждение до срока:
    выкладка посреди прогона, оборванная сеть, зависший ответ SDK. На экране
    это выглядит как модель, которая пишет и не заканчивает.

    Отмена доходит до исполнителя не мгновенно: он смотрит на состояние в базе
    между шагами, а внутри вызова модели шагов нет. Поэтому пометка ставится
    здесь же, сразу: человеку нужно, чтобы кнопка отпустилась, а не чтобы
    где-то остановился поток.

    Нечего останавливать — не ошибка: кнопку жмут по второму разу, и отказ на
    это выглядел бы поломкой там, где всё уже хорошо.
    """
    remark = db.execute(
        select(Discussion).where(
            Discussion.organization_id == organization_id,
            Discussion.module == "goszakup",
            Discussion.row_id == lot_number,
        )
    ).scalar_one_or_none()
    if remark is None:
        return None

    service = JobService(db, redis)
    running = (
        db.execute(
            select(Job)
            .where(Job.organization_id == organization_id)
            .where(Job.module == "goszakup", Job.kind == "remark")
            .where(Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)))
            .where(Job.params["remark_id"].astext == str(remark.id))
        )
        .scalars()
        .all()
    )
    for job in running:
        service.cancel(job.id)

    if remark.writing in (DiscussionWriting.QUEUED, DiscussionWriting.RUNNING):
        remark.writing = DiscussionWriting.FAILED
        remark.trouble = "Написание остановлено вручную. Можно запустить заново"
    db.flush()
    logger.info("goszakup.remark.stopped", lot=lot_number, jobs=len(running))
    return remark


def _needs_writing(db: DbSession, organization_id: uuid.UUID, remark: Discussion) -> bool:
    """Стоит ли звать модель.

    Не стоит, если текст уже написан или его прямо сейчас пишут. Иначе каждый
    возврат карточки в «Обсуждение» — это ещё один платный вызов и затёртый
    текст, который до этого правили руками.
    """
    if remark.text.strip():
        return False
    running = db.execute(
        select(Job.id)
        .where(Job.organization_id == organization_id)
        .where(Job.module == "goszakup", Job.kind == "remark")
        .where(Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)))
        .where(Job.params["remark_id"].astext == str(remark.id))
        .limit(1)
    ).first()
    return running is None


def on_take(
    db: DbSession,
    *,
    card: Any,
    user_id: uuid.UUID | None,
    settings: Settings,
    redis: Any,
) -> tuple[uuid.UUID, ...]:
    """Заводит обсуждение и разбор сразу, как лот взяли в работу.

    Ради того, чтобы не нажимать две кнопки на каждый лот. Взятых за утро
    бывает десяток, оба прогона идут минутами, и человек, нажимающий их руками,
    либо ждёт у экрана, либо забывает половину: лот лежит в работе без разбора,
    а замечание не написано, хотя срок на него — два рабочих дня.

    Обе задачи ставятся в очередь, а не выполняются здесь: нажатие должно
    вернуть карточку сразу, а прогоны идут своим чередом и переживают уход со
    страницы. Пока они идут, карточка это показывает — по ним и видно, что
    работа началась.

    Повторный заход ничего не запускает второй раз. Кнопку нажимают дважды, а
    карточку открывают с двух машин; каждая задача стоит денег, и оплаченного
    дважды в списке прогонов потом не объяснить.
    """
    started: list[uuid.UUID] = []

    made = ensure(
        db,
        organization_id=card.organization_id,
        user_id=user_id,
        lot_number=card.row_id,
        settings=settings,
        redis=redis,
    )
    if made.job_id is not None:
        started.append(made.job_id)

    sheet_job = _sheet_job(db, card=card, user_id=user_id, redis=redis)
    if sheet_job is not None:
        started.append(sheet_job)

    logger.info("goszakup.take.autostart", lot=card.row_id, jobs=len(started))
    return tuple(started)


def _sheet_job(
    db: DbSession,
    *,
    card: Any,
    user_id: uuid.UUID | None,
    redis: Any,
) -> uuid.UUID | None:
    """Ставит разбор спецификации, если его есть из чего собирать и он не идёт.

    Спецификации у большинства лотов портала нет вовсе: файл отдаётся только по
    токену кабинета, а он выдаётся после входа по ЭЦП. Задача на пустом тексте
    честно напишет «раскладывать нечего» — но напишет это в списке прогонов,
    рядом с настоящей работой, и через неделю по нему нельзя будет понять, что
    из этого было делом.
    """
    from platform_api.db.models import SpecSheet
    from platform_api.modules.goszakup.jobs import spec_of

    # Лениво: `jobs` импортирует этот файл сам — обработчик кнопки и обработчик
    # задачи заводят обсуждение одинаково, — и на верхнем уровне это круг.
    if not spec_of(card.row_id)[0].strip():
        return None

    already = db.execute(
        select(SpecSheet).where(SpecSheet.module == card.module, SpecSheet.row_id == card.row_id)
    ).scalar_one_or_none()
    if already is not None and already.rows:
        return None
    if _running_sheet(db, card) is not None:
        return None

    job = JobService(db, redis).create(
        organization_id=card.organization_id,
        created_by_id=user_id,
        module="goszakup",
        kind="sheet",
        params={"card_id": str(card.id), "variant": "A"},
        total=1,
    )
    db.flush()
    return job.id


def _running_sheet(db: DbSession, card: Any) -> Job | None:
    """Разбор этого лота, который уже стоит в очереди или идёт."""
    return (
        db.execute(
            select(Job)
            .where(
                Job.organization_id == card.organization_id,
                Job.module == "goszakup",
                Job.kind == "sheet",
                Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
                Job.params["card_id"].astext == str(card.id),
            )
            .order_by(Job.created_at.desc())
        )
        .scalars()
        .first()
    )


def launch(settings: Settings, job_id: uuid.UUID | None) -> None:
    """Отдаёт задачу очереди. Уже после `commit`: до него её никто не найдёт."""
    if job_id is not None:
        enqueue_sync(settings, job_id)


__all__ = ["LotMissingError", "Started", "ensure", "launch", "on_take", "stop_writing"]
