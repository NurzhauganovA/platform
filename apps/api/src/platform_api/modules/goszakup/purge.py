"""Полная очистка раздела госзакупок.

Нужна, когда список разошёлся с порталом настолько, что чинить дешевле
заново: переезд на единый портал оставил в базе записи с прежними внутренними
номерами, а к ним успели прирасти карточки, обсуждения и устойчивые коды.

Удаление идёт в двух базах сразу, и это единственное место в платформе, где
так делается. База площадки хранит сами лоты, база платформы — всё, что мы
про них надумали. Оставить одно без другого хуже, чем не удалять вовсе:
карточка без лота открывается пустой, а устойчивый код без строки выдаётся
следующей закупке — и «GZ000045» в старой задаче начинает указывать на чужой
товар.

Что уцелеет намеренно: список кодов ЕНС ТРУ и файлы в хранилище. Список — это
настройка, а не данные; файлы могут быть приложены и к соседнему лоту.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from platform_api.db.models import Discussion, DiscussionMessage, LotCard, WorklistCode
from platform_api.logging import get_logger
from platform_api.modules.goszakup import core

logger = get_logger(__name__)

MODULE = "goszakup"


@dataclass(frozen=True, slots=True)
class Cleared:
    """Сколько чего удалено. Показывается человеку до и после."""

    lots: int
    cards: int
    remarks: int
    messages: int
    codes: int

    @property
    def total(self) -> int:
        return self.lots + self.cards + self.remarks + self.messages + self.codes


def count(db: DbSession) -> Cleared:
    """Что будет удалено. Спрашивается до нажатия, а не после.

    Человек соглашается на число, а не на слово «всё»: семнадцать карточек и
    шесть реплик — это чья-то работа, и увидеть её объём он должен заранее.
    """
    return Cleared(
        lots=_lots_count(),
        cards=_rows(db, LotCard),
        remarks=_rows(db, Discussion),
        messages=_rows(db, DiscussionMessage),
        codes=_codes(db),
    )


def run(db: DbSession) -> Cleared:
    """Удаляет лоты площадки и всё, что к ним приросло.

    Порядок: сначала платформа, потом площадка. Обратный оставил бы окно, в
    котором лотов уже нет, а карточки на них ещё ссылаются, — и открытая в
    этот момент страница показала бы пустой разбор вместо честного отказа.

    Задачи, подписи, лента событий и приложенные к карточке файлы уходят
    вместе с карточкой: у них внешний ключ с каскадом. Перечислять их здесь
    значило бы завести второй список того же, который разойдётся с базой при
    первой новой таблице.
    """
    было = count(db)

    db.execute(delete(DiscussionMessage).where(DiscussionMessage.module == MODULE))
    db.execute(delete(Discussion).where(Discussion.module == MODULE))
    db.execute(delete(LotCard).where(LotCard.module == MODULE))
    db.execute(delete(WorklistCode).where(WorklistCode.module == MODULE))
    db.flush()

    _clear_lots()

    logger.warning(
        "goszakup.purged",
        lots=было.lots,
        cards=было.cards,
        remarks=было.remarks,
        messages=было.messages,
        codes=было.codes,
    )
    return было


def _rows(db: DbSession, model: type[LotCard] | type[Discussion] | type[DiscussionMessage]) -> int:
    return int(
        db.execute(select(func.count()).select_from(model).where(model.module == MODULE)).scalar()
        or 0
    )


def _codes(db: DbSession) -> int:
    return int(
        db.execute(
            select(func.count()).select_from(WorklistCode).where(WorklistCode.module == MODULE)
        ).scalar()
        or 0
    )


def _lots_count() -> int:
    from goszakup.infrastructure.db.models import LotRecord

    with core.session() as portal:
        return int(portal.execute(select(func.count()).select_from(LotRecord)).scalar() or 0)


def _clear_lots() -> None:
    """Чистит таблицу лотов в базе площадки.

    Список кодов ЕНС ТРУ не трогаем: это настройка обхода, заведённая руками,
    и стирать её вместе с данными значит заставить администратора набирать
    тридцать четыре кода заново.
    """
    from goszakup.infrastructure.db.models import LotRecord

    with core.session() as portal:
        portal.execute(delete(LotRecord))
        portal.commit()
