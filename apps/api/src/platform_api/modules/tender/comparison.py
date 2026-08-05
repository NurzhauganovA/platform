"""Сравнение предложений по закупке.

Ради этого разбор и делается: пока цены разных КП не сведены по позициям,
сравнивать можно только итоговые суммы — а они складываются из разного состава
и потому мало о чём говорят.

Здесь же проходит граница прав, и она не косметическая. Закупщик видит
позиции, поставщиков и цены конкурентов — с этим он работает. Нашей отпускной
цены, себестоимости и маржи он не видит: для его работы они не нужны, а уходят
вместе с ним. Решение принимается на эндпоинте, а не в интерфейсе: спрятанная
кнопка при открытом адресе — самый простой способ отдать себестоимость наружу.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from platform_api.auth.dependencies import CurrentUser, Db, requires_sourcing
from platform_api.db.models import Role
from platform_api.logging import get_logger
from platform_api.modules.tender.models import TenderCaseRow

logger = get_logger(__name__)

router = APIRouter(prefix="/cases", tags=["Закупки"])


class QuoteOut(BaseModel):
    """Цена одного поставщика по одной позиции."""

    supplier: str | None
    document: str
    specification: str | None
    quantity: float | None
    unit: str | None
    unit_price: float | None
    """Цена за единицу, приведённая к базе без НДС.

    Приведённая намеренно: одни поставщики указывают цену с НДС, другие без,
    и сравнение «как прислали» показывает победителем того, кто просто
    посчитал иначе."""

    total_price: float | None
    is_cheapest: bool = False


class RequestedOut(BaseModel):
    """Позиция, которую хочет заказчик, — из его собственных документов."""

    name: str
    specification: str | None = None
    quantity: float | None = None
    unit: str | None = None
    customer_price: float | None = None
    """Ориентир заказчика из заключения. Выше него предлагать бессмысленно."""

    source_document: str = ""


class PositionOut(BaseModel):
    """Одна позиция закупки со всеми предложениями по ней."""

    name: str
    quotes: list[QuoteOut]
    min_price: float | None
    max_price: float | None
    median_price: float | None
    spread_ratio: float | None
    """Во сколько раз дороже самое дорогое. Разброс в разы — сигнал не выгоды,
    а несопоставимости: поставщики поняли требование по-разному."""

    supplier_count: int


class FindingOut(BaseModel):
    """Где нашли товар и почём.

    То, с чем менеджер идёт работать: площадка, поставщик, цена, ссылка. Всё,
    чего не хватает для звонка, — это незакрытая работа, а не находка.
    """

    position: str
    country: str
    marketplace: str
    supplier: str | None = None
    title: str = ""
    price_kzt: float | None = None
    landed_cost: float | None = None
    """Цена с логистикой и растаможкой — то, во что товар обойдётся нам."""

    unit: str | None = None
    delivery_days: int | None = None
    min_order: str | None = None
    url: str | None = None
    contact: str | None = None
    matches_spec: bool = True
    match_note: str = ""

    margin_percent: float | None = None
    margin_total: float | None = None


class MarketOut(BaseModel):
    """Что нашлось на рынках по этой закупке."""

    searched: bool = False
    findings: list[FindingOut] = []
    total_margin: float | None = None
    by_country: dict[str, int] = {}


class DecisionOut(BaseModel):
    """Решение модели по закупке. Видно тем, кто отвечает за деньги."""

    recommendation: str | None = None
    confidence: str | None = None
    summary: str = ""
    comparability: str = ""
    best_offer_supplier: str | None = None
    best_offer_reason: str | None = None

    estimated_cost: float | None = None
    recommended_bid: float | None = None
    expected_margin_percent: float | None = None
    margin_reasoning: str = ""

    blockers: list[str] = []
    questions: list[str] = []


class ComparisonOut(BaseModel):
    """Закупка глазами тендерщика."""

    case_id: uuid.UUID
    subject: str | None = None
    customer: str | None = None

    documents: int = 0
    offers: int = 0
    positions: list[PositionOut] = []
    requirements: list[str] = []
    risks: list[str] = []

    total_min: float | None = None
    total_max: float | None = None

    requested: list[RequestedOut] = []
    """Что нужно заказчику. Показывается, когда предложений ещё нет: закупка
    без КП — не повод её пропускать."""

    market: MarketOut | None = None
    """Находки на рынках. У закупщика тоже: он с ними и работает — звонит,
    договаривается, покупает."""

    decision: DecisionOut | None = None
    """Отсутствует у закупщика и наблюдателя: там себестоимость и маржа."""

    analyzed: bool = True


@router.get("/{case_id}/comparison", summary="Сравнение предложений")
def get_comparison(
    case_id: uuid.UUID,
    identity: CurrentUser,
    db: Db,
    _guard: Annotated[None, requires_sourcing] = None,
) -> ComparisonOut:
    """Сводит предложения по позициям.

    Считается на лету по разобранным документам, а не хранится: состав закупки
    меняется — доложили КП, — и сохранённая сводка тут же начинает врать. Она
    и так дешёвая: обращения к модели здесь нет.
    """
    case = db.get(TenderCaseRow, case_id)
    if case is None or case.organization_id != identity.organization.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Закупка не найдена")

    from platform_api.modules.tender.core import build_case_view

    view = build_case_view(case)
    if view is None:
        return ComparisonOut(
            case_id=case.id,
            subject=case.subject or None,
            customer=case.customer or None,
            analyzed=False,
        )

    # Деньги видят те, кто за них отвечает. Закупщику и наблюдателю сюда
    # нельзя: себестоимость и маржа для их работы не нужны.
    with_money = identity.role in (Role.ADMIN, Role.ANALYST)
    return _to_out(case, view, with_money=with_money)


def _to_out(case: TenderCaseRow, view: Any, *, with_money: bool) -> ComparisonOut:
    vat: Decimal = view.vat_rate
    positions: list[PositionOut] = []

    for group in view.case.groups:
        cheapest = group.min_price(vat)
        quotes = [
            QuoteOut(
                supplier=quote.supplier,
                document=quote.document_name,
                specification=quote.specification,
                quantity=_float(quote.quantity),
                unit=quote.unit,
                unit_price=_float(quote.net_unit_price(vat)),
                total_price=_float(quote.total_price),
                is_cheapest=(cheapest is not None and quote.net_unit_price(vat) == cheapest),
            )
            for quote in group.quotes
        ]
        positions.append(
            PositionOut(
                name=group.name,
                quotes=quotes,
                min_price=_float(cheapest),
                max_price=_float(group.max_price(vat)),
                median_price=_float(group.median_price(vat)),
                spread_ratio=_float(group.spread_ratio(vat)),
                supplier_count=group.supplier_count,
            )
        )

    analysis = view.case.analysis
    decision = None
    if with_money and analysis is not None:
        decision = DecisionOut(
            recommendation=_value(analysis.recommendation),
            confidence=_value(getattr(analysis, "win_chance", None)),
            summary=analysis.summary or "",
            comparability=analysis.comparability or "",
            best_offer_supplier=analysis.best_offer_supplier,
            best_offer_reason=analysis.best_offer_reason,
            estimated_cost=analysis.estimated_cost,
            recommended_bid=analysis.recommended_bid,
            expected_margin_percent=analysis.expected_margin_percent,
            margin_reasoning=analysis.margin_reasoning or "",
            blockers=list(getattr(analysis, "blockers", []) or []),
            questions=list(getattr(analysis, "questions", []) or []),
        )

    return ComparisonOut(
        case_id=case.id,
        requested=[
            RequestedOut(
                name=item.name,
                specification=item.specification,
                quantity=_float(item.quantity),
                unit=item.unit,
                customer_price=_float(item.customer_price),
                source_document=item.source_document,
            )
            for item in view.case.requested
        ],
        market=_market(view),
        subject=view.case.subject or case.subject or None,
        customer=(view.case.customer.name if view.case.customer else None) or case.customer or None,
        documents=len(view.case.documents),
        offers=len(view.case.offers),
        positions=positions,
        requirements=list(view.case.requirements),
        risks=list(view.case.risks),
        total_min=_float(view.total_min),
        total_max=_float(view.total_max),
        decision=decision,
    )


def _market(view: Any) -> MarketOut | None:
    """Находки прошлого поиска по этой закупке.

    Читаются из базы ядра: поиск платный, и его результат нужен потом — при
    сборке КП и при звонке поставщику, а не только в момент выполнения.
    """
    from pydantic import ValidationError
    from tender_analyze.application.case_analysis import case_fingerprint
    from tender_analyze.application.container import Container
    from tender_analyze.domain.models import Opportunity

    from platform_api.modules.tender.core import core_settings

    settings = core_settings()
    container = Container(settings)
    try:
        with container.unit_of_work(view.root) as uow:
            payload = uow.cases.get_opportunities(view.case.folder, case_fingerprint(view.case))
    finally:
        container.dispose()

    if payload is None:
        return MarketOut(searched=False)

    try:
        opportunities = [Opportunity.model_validate(item) for item in payload]
    except ValidationError:
        logger.warning("Сохранённые находки не читаются", case=str(view.case.folder))
        return MarketOut(searched=False)

    by_country: dict[str, int] = {}
    findings: list[FindingOut] = []
    for item in opportunities:
        finding = item.finding
        country = finding.country.value
        by_country[country] = by_country.get(country, 0) + 1
        findings.append(
            FindingOut(
                position=item.position,
                country=country,
                marketplace=finding.marketplace,
                supplier=finding.supplier,
                title=finding.title or "",
                price_kzt=_float(finding.price_kzt),
                landed_cost=_float(item.landed_cost),
                unit=finding.unit,
                delivery_days=finding.delivery_days,
                min_order=finding.min_order,
                url=finding.url,
                contact=finding.contact,
                matches_spec=finding.matches_spec,
                match_note=finding.match_note or "",
                margin_percent=_float(item.margin_percent),
                margin_total=_float(item.margin_total),
            )
        )

    findings.sort(key=lambda item: item.margin_percent or 0, reverse=True)
    return MarketOut(
        searched=True,
        findings=findings,
        total_margin=float(sum(item.margin_total for item in opportunities if item.is_viable)),
        by_country=by_country,
    )


def _float(value: Decimal | float | None) -> float | None:
    return float(value) if value is not None else None


def _value(item: Any) -> str | None:
    """Значение перечисления ядра в виде строки."""
    if item is None:
        return None
    return str(getattr(item, "value", item))


__all__ = ["router"]
