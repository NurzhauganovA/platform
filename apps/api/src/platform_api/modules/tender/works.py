"""Лот в работе: путь между отделом разбора и снабжением.

До сих пор отбор заканчивался разбором: посмотрели, поняли, что закупка
выгодная, — и дальше работа уходила в переписку и таблицы. Кто какого
поставщика подтвердил, что просили найти и что нашли, во сколько в итоге
обходится — всё это жило в головах и письмах.

Здесь тот же путь, но с состоянием, которое видно обоим отделам:

1. Разбор берёт лот в работу. Позиции переписываются в работу целиком, а не
   ссылкой: отбор пересобирается при каждом прогоне ядра, а работа должна
   остаться той же.
2. По каждой позиции разбор либо подтверждает найденный вариант, либо просит
   снабжение поискать — тогда у варианта заполнено одно название.
3. Снабжение видит только «где купить» и техническое задание. Правит цены и
   ссылки, ставит срок поставки, добавляет свои варианты.
4. Возвращает разбору — с подтверждёнными ценами.

Отвергнутые разбором находки снабжению не уходят. Показать их значит
попросить второй отдел заново пройти путь, который первый уже прошёл.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select

from platform_api.db.base import utcnow
from platform_api.db.models import (
    OptionSource,
    Role,
    TenderWork,
    TenderWorkOption,
    TenderWorkPosition,
    WorkStage,
)
from platform_api.errors import SpokenError

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session as DbSession


@dataclass(frozen=True, slots=True)
class Draft:
    """Позиция, какой её берут в работу."""

    folder_path: str
    title: str
    code: str
    quantity: Decimal | None
    unit: str
    total: Decimal | None
    options: tuple[dict[str, Any], ...]
    """Находки ядра по этой позиции — то, из чего разбор будет выбирать."""

    spec: str = ""
    spec_source: str = ""
    """Черновик задания снабжению и документ, из которого он собран."""


def take(
    db: DbSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    code: str,
    title: str,
    customer: str,
    positions: Sequence[Draft],
) -> TenderWork:
    """Берёт лот в работу. Повторно взять тот же нельзя.

    Второй раз — это второй путь по тем же позициям: два отдела, две
    переписки, и потом не выяснить, какая себестоимость настоящая.
    """
    if not positions:
        raise SpokenError("В этом лоте нет позиций — брать в работу нечего")

    уже = db.execute(
        select(TenderWork).where(
            TenderWork.organization_id == organization_id,
            TenderWork.code == code,
        )
    ).scalar_one_or_none()
    if уже is not None:
        raise SpokenError(f"Лот {code} уже в работе — откройте его в разделе «В работе»")

    work = TenderWork(
        organization_id=organization_id,
        created_by_id=user_id,
        code=code,
        title=title,
        customer=customer,
        stage=WorkStage.ANALYSIS,
    )
    db.add(work)
    db.flush()

    for порядок, draft in enumerate(positions):
        position = TenderWorkPosition(
            work_id=work.id,
            folder_path=draft.folder_path,
            title=draft.title,
            code=draft.code,
            quantity=draft.quantity,
            unit=draft.unit,
            total=draft.total,
            ordering=порядок,
            spec=draft.spec,
            spec_source=draft.spec_source,
        )
        db.add(position)
        db.flush()
        for найдено in draft.options:
            db.add(
                TenderWorkOption(
                    position_id=position.id,
                    source=OptionSource.FOUND,
                    **найдено,
                )
            )
    db.flush()
    return work


def taken(db: DbSession, organization_id: uuid.UUID) -> frozenset[str]:
    """Коды лотов, которые уже в работе. Нужно списку, чтобы не звать дважды."""
    rows = db.execute(
        select(TenderWork.code).where(TenderWork.organization_id == organization_id)
    ).scalars()
    return frozenset(rows)


def one(db: DbSession, organization_id: uuid.UUID, work_id: uuid.UUID) -> TenderWork:
    """Работа по имени. Чужой организации — как будто её нет."""
    work = db.execute(
        select(TenderWork).where(
            TenderWork.id == work_id,
            TenderWork.organization_id == organization_id,
        )
    ).scalar_one_or_none()
    if work is None:
        raise SpokenError("Такой работы нет")
    return work


def choose(db: DbSession, work: TenderWork, option_id: uuid.UUID) -> None:
    """Разбор подтверждает вариант: остальные найденные по этой позиции уходят.

    Уходят насовсем, а не прячутся. Снабжению они не нужны — разбор их уже
    посмотрел и отверг, — а лежащий рядом отвергнутый вариант однажды уедет в
    КП вместо выбранного.

    Своё и добавленное снабжением не трогаем: их добавляли руками, и стереть
    чужую работу одним щелчком по соседней строке нельзя.
    """
    _at_stage(work, _ANALYSIS_DESK, "Выбирать поставщика может отдел разбора")
    выбран = _option(work, option_id)
    выбран.chosen = True
    db.execute(
        delete(TenderWorkOption).where(
            TenderWorkOption.position_id == выбран.position_id,
            TenderWorkOption.id != выбран.id,
            TenderWorkOption.source == OptionSource.FOUND,
            TenderWorkOption.chosen.is_(False),
        )
    )
    db.flush()


def ask(db: DbSession, work: TenderWork, position_id: uuid.UUID, name: str) -> TenderWorkOption:
    """Разбор просит снабжение найти товар: заполнено одно название.

    Так и выглядит заявка: «вот это найдите сами». Пустые поля здесь не
    недоделка, а смысл — цену и поставщика выясняет снабжение.
    """
    _at_stage(work, _ANALYSIS_DESK, "Заказывать поиск может отдел разбора")
    имя = name.strip()
    if not имя:
        raise SpokenError("Напишите, что искать: без названия снабжению не с чем работать")

    # Заказ поиска — это и есть слова «найденное не подходит». Неподтверждённые
    # находки уходят: снабжение иначе потратит день на то, что разбор уже
    # посмотрел и отверг. Подтверждённое остаётся — его проверяют.
    position = _position(work, position_id)
    db.execute(
        delete(TenderWorkOption).where(
            TenderWorkOption.position_id == position.id,
            TenderWorkOption.source == OptionSource.FOUND,
            TenderWorkOption.chosen.is_(False),
        )
    )

    option = TenderWorkOption(
        position_id=position.id,
        source=OptionSource.ASKED,
        name=имя,
    )
    db.add(option)
    db.flush()
    return option


def add(
    db: DbSession, work: TenderWork, position_id: uuid.UUID, user_id: uuid.UUID, **fields: Any
) -> TenderWorkOption:
    """Снабжение добавляет свой вариант."""
    _at_stage(work, (WorkStage.SUPPLY,), "Добавлять варианты может снабжение")
    option = TenderWorkOption(
        position_id=_position(work, position_id).id,
        source=OptionSource.SUPPLY,
        updated_by_id=user_id,
        **_cleaned(fields),
    )
    db.add(option)
    db.flush()
    return option


def edit(
    db: DbSession, work: TenderWork, option_id: uuid.UUID, user_id: uuid.UUID, **fields: Any
) -> TenderWorkOption:
    """Снабжение правит вариант: цену, ссылку, поставщика, срок поставки.

    Правит любой, включая найденный моделью, — за тем его и передавали:
    цена с площадки бывает вчерашней, а ссылка ведёт на раздел, а не на товар.
    """
    _at_stage(work, (WorkStage.SUPPLY,), "Править варианты может снабжение")
    option = _option(work, option_id)
    for имя, значение in _cleaned(fields).items():
        setattr(option, имя, значение)
    option.updated_by_id = user_id
    db.flush()
    return option


def drop(db: DbSession, work: TenderWork, option_id: uuid.UUID) -> None:
    """Убрать вариант — тем отделом, у которого лот сейчас."""
    option = _option(work, option_id)
    if work.stage is WorkStage.SUPPLY and option.source is OptionSource.ASKED:
        raise SpokenError(
            "Это заявка отдела разбора — её не убирают, а заполняют."
            " Если товара нет, напишите об этом в комментарии"
        )
    db.execute(delete(TenderWorkOption).where(TenderWorkOption.id == option.id))


def set_spec(db: DbSession, work: TenderWork, position_id: uuid.UUID, body: str) -> None:
    """Разбор правит задание, которое увидит снабжение.

    Правит только разбор, и только пока лот у него. Снабжение задание читает:
    дать ему исправлять условия, по которым оно же и отчитывается, значит
    убрать единственное место, где записано, что именно просили купить.
    """
    from platform_api.modules.tender.spec import MAX_LENGTH

    _at_stage(work, _ANALYSIS_DESK, "Править задание может отдел разбора")
    position = _position(work, position_id)
    position.spec = body.strip()[:MAX_LENGTH]
    db.flush()


def hand_over(db: DbSession, work: TenderWork, note: str) -> TenderWork:
    """Передаёт лот другому отделу.

    Разбор передаёт снабжению, снабжение возвращает разбору. Третьего пути
    нет: это один процесс на два отдела, и «отправить» у каждого означает своё.
    """
    if work.stage is WorkStage.SUPPLY:
        work.supply_note = note.strip()
        work.stage = WorkStage.RETURNED
    else:
        _require_ready(work)
        work.analysis_note = note.strip()
        work.stage = WorkStage.SUPPLY
    work.sent_at = utcnow()
    db.flush()
    return work


def _require_ready(work: TenderWork) -> None:
    """Не отпускает лот, пока по каждой позиции нечего сказать.

    Позиция без единого варианта — это молчание: снабжение получит строку и не
    поймёт, искать по ней или она попала случайно. Спросить об этом оно сможет
    только письмом, а ради письма процесс и заводили.
    """
    немые = [position.title for position in work.positions if not position.options]
    if немые:
        raise SpokenError(
            f"По позиции «{_enumerate(немые)} не выбран поставщик и не заказан поиск."
            " Выберите вариант или нажмите «Заказать поиск»"
        )

    # Снабжение не видит исходных документов: в них цены заключения и печати.
    # Задание — единственное, по чему оно поймёт, что искать, и позиция без
    # него уходит немой ровно так же, как позиция без вариантов.
    безмолвные = [position.title for position in work.positions if not position.spec.strip()]
    if безмолвные:
        raise SpokenError(
            f"У позиции «{_enumerate(безмолвные)} пустое техническое задание."
            " Снабжение исходных документов не видит — опишите, что нужно купить"
        )


def _enumerate(titles: list[str]) -> str:
    """«Насос» или «Насос» и ещё 3 — начало жалобы на список позиций."""
    сколько = f" и ещё {len(titles) - 1}" if len(titles) > 1 else ""
    return f"{titles[0][:60]}»{сколько}"


def visible_for(work: TenderWork, role: Role) -> bool:
    """Видит ли эта роль работу вообще.

    Снабжение видит лот, только когда он у него: до передачи там ещё нечего
    смотреть, а после возврата работа снова у разбора.
    """
    if role in (Role.ADMIN, Role.ANALYST):
        return True
    return work.stage is WorkStage.SUPPLY


_ANALYSIS_DESK = (WorkStage.ANALYSIS, WorkStage.RETURNED)
"""Когда лот на столе у разбора.

Возврат от снабжения — это тоже стол разбора, а не готовый результат. Оно
прислало цены; разбор их читает и вполне может передумать: подтверждённый
поставщик оказался дороже соседнего или не успевает к сроку. Считать
возвращённый лот закрытым значило бы, что передумать можно только заведя
второй лот по тем же позициям.
"""


def _at_stage(work: TenderWork, stages: tuple[WorkStage, ...], refusal: str) -> None:
    if work.stage not in stages:
        raise SpokenError(f"{refusal}, и только пока лот у него")


def _position(work: TenderWork, position_id: uuid.UUID) -> TenderWorkPosition:
    for position in work.positions:
        if position.id == position_id:
            return position
    raise SpokenError("Такой позиции в этой работе нет")


def _option(work: TenderWork, option_id: uuid.UUID) -> TenderWorkOption:
    for position in work.positions:
        for option in position.options:
            if option.id == option_id:
                return option
    raise SpokenError("Такого варианта в этой работе нет")


_FIELDS = frozenset(
    {"name", "supplier", "marketplace", "country", "url", "price", "delivery_days", "note"}
)


def _cleaned(fields: dict[str, Any]) -> dict[str, Any]:
    """Оставляет только известные поля и убирает не заданные.

    `None` значит «не трогай», а не «сотри»: правка приходит по одному полю —
    поправили цену, и ссылка не должна обнулиться заодно.
    """
    return {
        имя: (значение.strip() if isinstance(значение, str) else значение)
        for имя, значение in fields.items()
        if имя in _FIELDS and значение is not None
    }


__all__ = [
    "Draft",
    "add",
    "ask",
    "choose",
    "drop",
    "edit",
    "hand_over",
    "one",
    "set_spec",
    "take",
    "taken",
    "visible_for",
]
