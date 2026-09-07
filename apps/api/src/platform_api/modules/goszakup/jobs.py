"""Фоновые задачи модуля госзакупок.

Предметной логики здесь нет: задача зовёт тот же сервис ядра, что и его CLI.

Обход живёт в очереди, а не в обработчике запроса, и причина не только в
длительности. Портал государственный, между запросами держится пауза, и на
тридцати четырёх кодах это минуты. Обработчик, который столько держит
соединение, — это истёкший таймаут у человека и повторное нажатие поверх
идущей работы.
"""

from __future__ import annotations

from typing import Any

from platform_api.jobs.contract import JobContext, JobSpec
from platform_api.logging import get_logger

logger = get_logger(__name__)


def harvest(
    ctx: JobContext, *, per_code: int = 1000, with_details: bool = True, **_: Any
) -> dict[str, Any]:
    """Обходит портал по списку кодов ЕНС ТРУ и складывает лоты в базу.

    Строго по списку: на портале сотни тысяч лотов, и сплошной обход — это и
    часы запросов, и список, в котором нужное не найти.
    """
    from goszakup.application.harvest import HarvestService

    from platform_api.modules.goszakup import core

    ctx.advance(0, total=1, note="Читаем список кодов ЕНС ТРУ")
    with core.session() as db:
        outcome = HarvestService(core.core_settings()).run(
            db,
            per_code=per_code,
            with_details=with_details,
            # Числа шага уезжают в задачу, а не только текст: без них полоса
            # показывала ноль процентов все пять минут прогона, и по ней не
            # отличить работающий обход от зависшего.
            on_progress=lambda note, done, total: ctx.advance(done, total=total, note=note),
        )
        db.commit()

    if outcome.failed:
        logger.warning("goszakup.harvest.partial", codes=list(outcome.failed))
    if outcome.broken:
        logger.warning("goszakup.harvest.broken", records=list(outcome.broken))
    if outcome.interrupted:
        logger.warning("goszakup.harvest.interrupted", reason=outcome.interrupted)

    # Упали все коды — это не «прогон прошёл, ничего не нашлось». Такой
    # прогон записывался успешным, раздел тихо оставался вчерашним, и
    # замечали это через сутки по пустому списку. Частичная неудача остаётся
    # успехом: один код из тридцати не повод выбрасывать двадцать девять.
    if outcome.codes and len(outcome.failed) == outcome.codes:
        raise RuntimeError(
            "Обход не удался ни по одному коду ЕНС ТРУ — портал недоступен "
            f"или нет связи. Коды: {', '.join(outcome.failed)}"
        )

    # Обрыв посреди обхода прогон не проваливает: собранное до него уже в
    # базе. Провал выбрасывал бы вместе с прогоном и сотни прочитанных
    # карточек — а человек, увидев красное, нажимал бы кнопку заново и платил
    # порталу теми же пятью минутами.
    return {
        "codes": outcome.codes,
        "found": outcome.found,
        "added": outcome.added,
        "updated": outcome.updated,
        "failed": list(outcome.failed),
        "broken": len(outcome.broken),
        "interrupted": outcome.interrupted,
    }


def write_remark(ctx: JobContext, *, remark_id: str = "", **_: Any) -> dict[str, Any]:
    """Пишет замечание к технической спецификации лота.

    В очереди, а не в обработчике запроса: модель отвечает десятками секунд, и
    держать на этом соединение значит показать человеку истёкший таймаут и
    получить второе нажатие поверх идущей работы.

    Отказ модели не роняет задачу. Кончились деньги на ключе, модель занята,
    ответ не пришёл вовремя — во всех случаях замечание остаётся ненаписанным,
    причина ложится в карточку словами, и менеджер пишет сам. Упавшая задача
    показала бы ему красный крест без объяснения.
    """
    import uuid as _uuid

    from platform_api.config import get_settings
    from platform_api.modules import remarks, writer
    from platform_api.modules.goszakup import core

    if not remark_id:
        raise ValueError("Не указано, какое обсуждение писать")
    wanted = _uuid.UUID(remark_id)

    ctx.advance(0, total=3, note="Читаем лот и спецификацию")
    remarks.starting(ctx.db, remark_id=wanted)
    ctx.db.commit()

    subject = _subject_of(ctx, wanted)
    if subject is None:
        remarks.written(
            ctx.db,
            remark_id=wanted,
            text="",
            model="",
            trouble="Лот не найден в базе площадки: обновите список и повторите",
        )
        ctx.db.commit()
        return {"written": False, "reason": "лот не найден"}

    ctx.advance(1, total=3, note="Модель пишет замечание")
    draft = writer.write(subject, get_settings())

    ctx.advance(2, total=3, note="Складываем написанное")
    # Спецификация лежит файлом, а файл портал отдаёт только вошедшему по ЭЦП.
    # Без её текста модель пишет по названию лота — замечание выйдет общим, и
    # человек должен знать об этом до того, как отправит его заказчику, а не
    # после отказа.
    trouble = draft.trouble
    if draft.text and not subject.spec_text:
        trouble = (
            "Техническая спецификация не прочитана: файл отдаётся только из кабинета. "
            "Замечание написано по названию лота — проверьте его особенно внимательно"
        )

    remarks.written(
        ctx.db,
        remark_id=wanted,
        text=draft.text,
        model=draft.model,
        trouble=trouble,
    )
    ctx.db.commit()
    ctx.advance(3, total=3, note="Готово")

    logger.info(
        "goszakup.remark.written",
        remark=remark_id,
        written=bool(draft.text),
        grounds=list(draft.grounds),
    )
    return {
        "written": bool(draft.text),
        "grounds": list(draft.grounds),
        "trouble": trouble,
        "length": len(draft.text),
        # Ссылка на `core` держит модуль в зависимостях задачи и заодно
        # проверяет, что база площадки жива к моменту записи результата.
        "module": core.__name__.rsplit(".", 2)[-2],
    }


def _subject_of(ctx: JobContext, remark_id: Any) -> Any:
    """Собирает закупку для подсказки модели из базы площадки.

    Ключ — номер лота, а не номер закупки: у объявления с четырьмя лотами
    номер закупки один на всех, и замечание ушло бы про чужой товар.
    """
    from decimal import Decimal

    from goszakup.infrastructure.db.models import LotRecord
    from sqlalchemy import select

    from platform_api.db.models import Discussion
    from platform_api.modules.goszakup import core
    from platform_api.modules.writing import Subject

    remark = ctx.db.get(Discussion, remark_id)
    if remark is None:
        return None

    with core.session() as db:
        found = (
            db.execute(select(LotRecord).where(LotRecord.lot_number == remark.row_id))
            .scalars()
            .first()
        )
        if found is None:
            return None
        return Subject(
            code=remark.code,
            purchase_number=found.purchase_number,
            title=found.name or found.enstru_name,
            customer=found.customer,
            amount=Decimal(found.amount) if found.amount is not None else None,
            count=Decimal(found.count) if found.count is not None else None,
            unit=found.unit,
            enstru_code=found.enstru_code,
            enstru_name=found.enstru_name,
            lot_number=found.lot_number,
            spec_text=found.spec_text,
        )


def build_sheet(ctx: JobContext, *, card_id: str = "", **_: Any) -> dict[str, Any]:
    """Раскладывает техническую спецификацию лота таблицей.

    Текст спецификации лежит в базе площадки — его забрал обход, и второй раз
    к порталу тут не ходим. Нет текста — задача не падает: у большинства лотов
    спецификации действительно нет, и «не приложена» это ответ, а не сбой.
    """
    import uuid as _uuid

    from sqlalchemy import select

    from platform_api.config import get_settings
    from platform_api.db.models import LotCard
    from platform_api.modules import sheets

    if not card_id:
        raise ValueError("Не указано, какой лот разбирать")

    ctx.advance(0, total=1, note="Читаем спецификацию")
    card = ctx.db.execute(
        select(LotCard).where(LotCard.id == _uuid.UUID(card_id))
    ).scalar_one_or_none()
    if card is None:
        raise RuntimeError("Лот не найден — возможно, его удалили, пока задача ждала очереди")

    spec_text, spec_name = _spec_of(card.row_id)
    ctx.advance(0, total=1, note="Модель раскладывает требования по предметам")
    table = sheets.build(
        ctx.db,
        card,
        get_settings(),
        spec_text=spec_text,
        spec_name=spec_name,
        user_id=ctx.user_id,
    )
    ctx.db.commit()

    logger.info("goszakup.sheet.built", card=card_id, rows=len(table.rows))
    return {
        "rows": len(table.rows),
        "model": table.model,
        "source": table.source_name,
        "trouble": table.trouble,
    }


def _spec_of(lot_number: str) -> tuple[str, str]:
    """Текст спецификации лота и имя её файла."""
    from goszakup.infrastructure.db.models import LotRecord
    from sqlalchemy import select

    from platform_api.modules.goszakup import core

    with core.session() as portal:
        found = (
            portal.execute(select(LotRecord).where(LotRecord.lot_number == lot_number))
            .scalars()
            .first()
        )
        if found is None:
            return "", ""
        return found.spec_text or "", found.spec_name or ""


jobs = (
    # На тридцать пятой минуте. Обход идёт строго по списку ЕНС ТРУ и денег
    # не стоит: открытое API портала не требует ни токена, ни ЭЦП.
    JobSpec(
        kind="harvest",
        handler=harvest,
        title="Обновление лотов с портала",
        every_hours=1,
        at_minute=35,
    ),
    JobSpec(kind="remark", handler=write_remark, title="Написание замечания"),
    JobSpec(kind="sheet", handler=build_sheet, title="Разбор спецификации таблицей"),
)

__all__ = ["jobs"]
