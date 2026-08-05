"""Разделение папки на отдельные закупки.

Тендерщик не всегда держит одну закупку в одной папке. В «11 Каплогистикс»
лежат двадцать девять маркетинговых заключений: бензин, седельный тягач,
битумоварка, ошейник для КРС — каждое про свой предмет и свою закупку. Пока
они считаются одной, сравнивать нечего: предложения разных закупок не сводятся
по позициям, и человек видит ноль там, где на самом деле двадцать девять
отдельных дел.

Разделение идёт по документам, задающим предмет: маркетинговому заключению и
техническому заданию. Каждый такой документ — это отдельная закупка, а
коммерческие предложения расходятся по ним по близости предмета.

Логика здесь, а не в ядре, и намеренно. Ядро отвечает на вопрос «что написано
в документах»; как из этого складывается работа отдела — что закупка, а что
папка с двадцатью девятью закупками — вопрос организации, и он платформы.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from platform_api.logging import get_logger

logger = get_logger(__name__)

SAME_SUBJECT = 0.72
"""Насколько похожими должны быть предметы, чтобы считаться одной закупкой.

Тот же порог, что ядро использует для сведения позиций. Ниже него «Битумоварка
БД-1,5 (на дизельном топливе)» и «Битумоварка БД-1,5 (на дизельном топливе)
для нужд филиала» разъехались бы на две закупки, хотя это одно и то же
заключение в двух редакциях."""

SAME_FILENAME = 0.85
"""Насколько похожими должны быть имена файлов, чтобы считать их редакциями
одного заключения.

Отдельный признак помимо предмета, и он надёжнее. «МЗ битумоварка БД-1,5.pdf»
и «МЗ битумоварка БД-1,5 (1).pdf» — очевидный дубль, но их предметы модель
описала по-разному: в одном «для нужд филиала», в другом нет. По предмету они
разъезжаются, по имени — нет."""

OFFER_MATCH = 0.55
"""Порог, по которому предложение относится к закупке.

Ниже, чем для предметов: поставщик пишет «Поставка ГСМ», а заключение —
«Закупка бензина АИ-92, АИ-95». Требовать здесь той же строгости значит
оставить половину КП без закупки."""


@dataclass(slots=True)
class ProposedCase:
    """Закупка, которую предлагается выделить из папки."""

    title: str
    subject: str
    customer: str = ""
    files: list[str] = field(default_factory=list)
    """Пути файлов внутри исходной папки."""

    anchors: int = 0
    """Сколько документов задают предмет. Больше одного — те же сведения в
    нескольких редакциях: «(1)» в имени файла встречается постоянно."""

    offers: int = 0


def propose_split(view: Any) -> list[ProposedCase]:
    """Смотрит на разобранную закупку и предлагает разделение.

    Пустой список означает «делить нечего»: предмет один, и папка — это
    действительно одна закупка.
    """
    from tender_analyze.application.cases import normalize_name, similarity
    from tender_analyze.domain.enums import DocumentKind

    anchors: list[Any] = []
    offers: list[Any] = []
    others: list[Any] = []

    for document in view.case.documents:
        insight = document.insight
        if insight is None:
            others.append(document)
            continue
        if insight.kind in (DocumentKind.MARKETING_REPORT, DocumentKind.TECHNICAL_SPEC):
            anchors.append(document)
        elif insight.kind is DocumentKind.COMMERCIAL_OFFER:
            offers.append(document)
        else:
            others.append(document)

    if len(anchors) < 2:
        return []

    groups: list[ProposedCase] = []
    keys: list[str] = []
    stems: list[str] = []

    for document in anchors:
        subject = (document.insight.subject or "").strip() or _stem(document.source.name)
        key = normalize_name(subject)

        stem = normalize_name(_stem(document.source.name))
        matched = next(
            (
                index
                for index, existing in enumerate(keys)
                if similarity(existing, key) >= SAME_SUBJECT
                or similarity(stems[index], stem) >= SAME_FILENAME
            ),
            None,
        )
        if matched is None:
            keys.append(key)
            stems.append(stem)
            groups.append(
                ProposedCase(
                    title=_title(subject, document.source.name),
                    subject=subject,
                    customer=_customer(document),
                    files=[str(document.source.relative_path)],
                    anchors=1,
                )
            )
        else:
            group = groups[matched]
            group.files.append(str(document.source.relative_path))
            group.anchors += 1
            # Более длинное описание предмета обычно точнее: в нём остаётся
            # «для нужд филиала», по которому видно заказчика.
            if len(subject) > len(group.subject):
                group.subject = subject
            if not group.customer:
                group.customer = _customer(document)

    if len(groups) < 2:
        return []

    for document in offers:
        subject = normalize_name(
            (document.insight.subject or "") or _positions_text(document.insight)
        )
        best, score = None, 0.0
        for index, key in enumerate(keys):
            value = similarity(key, subject)
            if value > score:
                best, score = index, value
        if best is not None and score >= OFFER_MATCH:
            groups[best].files.append(str(document.source.relative_path))
            groups[best].offers += 1
        else:
            # Предложение, которое не легло ни к одной закупке, теряться не
            # должно: без него закупка выглядит так, будто в ней нет цен.
            logger.info(
                "Предложение не отнесено к закупке",
                document=document.source.name,
                best_score=round(score, 2),
            )

    return groups


def _title(subject: str, filename: str) -> str:
    """Название закупки для человека.

    Предмет из документа, если он короткий и осмысленный; иначе имя файла —
    тендерщик узнаёт закупку именно по нему.
    """
    text = " ".join(subject.split())
    if 3 <= len(text) <= 90:
        return text
    return _stem(filename)


def _stem(filename: str) -> str:
    import re

    name = filename.rsplit(".", 1)[0]
    # «(1)», «(2)» в конце — метка копии, которую ставит файловый менеджер
    # при повторном сохранении. К предмету закупки она отношения не имеет.
    name = re.sub(r"\s*\(\d+\)\s*$", "", name)
    # «ЦМЗ с ЭЦП Материалы для ремонта…» → «Материалы для ремонта…».
    # Вид документа и пометка о подписи в названии закупки лишние: и то и
    # другое видно по составу, а название должно называть предмет.
    prefixes = ("Проект МЗ", "Проект", "ЦМЗ", "МЗ", "ТЗ", "СЗ", "с ЭЦП", "Каплог", "КапЛог")
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if name.lower().startswith(prefix.lower()):
                name = name[len(prefix) :].lstrip(" -—_")
                changed = True
    return name.strip() or filename


def _customer(document: Any) -> str:
    customer = getattr(document.insight, "customer", None)
    return (getattr(customer, "name", "") or "").strip()


def _positions_text(insight: Any) -> str:
    positions = getattr(insight, "positions", None) or []
    return " ".join(getattr(item, "name", "") for item in positions[:5])


def summarize(groups: Sequence[ProposedCase]) -> dict[str, int]:
    return {
        "cases": len(groups),
        "files": sum(len(group.files) for group in groups),
        "offers": sum(group.offers for group in groups),
    }


__all__ = ["SAME_SUBJECT", "ProposedCase", "propose_split", "summarize"]
