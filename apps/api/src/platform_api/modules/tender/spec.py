"""Техническое задание позиции — то единственное, что видит снабжение.

Снабжению нужен предмет закупки и требования к нему. Исходный документ
заказчика ему открывать нельзя: в ТЗ стоят цены ценового заключения, реквизиты
сторон и печати, а от цены заказчика считается наша — увидев её, снабженец
знает потолок, по которому с ним же и будут торговаться поставщики.

Поэтому задание не вычищается, а **собирается заново** — из того, что ядро уже
разобрало, и только из перечисленных здесь полей. Разница принципиальная:
вычистка отвечает «мы убрали всё, что вспомнили», сборка — «сюда попало только
то, что названо». Первая ошибается молча и ровно один раз.

Платного шага здесь нет. Всё, из чего собирается задание, ядро извлекло при
разборе документов, и лежит это в его базе: открытая страница не тратит денег.

Черновик записывается в саму работу при взятии её в работу, а не считается на
каждый показ. Отбор пересобирается при каждом прогоне, названия у позиций
меняются — а задание, отданное снабжению, меняться от этого не должно.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

MAX_LENGTH = 20_000
"""Предел длины задания. Не про базу, а про человека: задание на двадцать
тысяч знаков не читают, а прокручивают."""


@dataclass(frozen=True, slots=True)
class Position:
    """Позиция глазами заказчика. Денежных полей здесь нет намеренно."""

    name: str
    specification: str
    quantity: Decimal | None
    unit: str
    ens_code: str


@dataclass(frozen=True, slots=True)
class CaseSpec:
    """Требования закупки — белый список полей, годных для снабжения.

    Собирается попутно со строками отбора: закупка в этот момент уже построена,
    и отдельного обращения к базе ядра это не стоит.
    """

    subject: str
    requirements: tuple[str, ...]
    delivery: str
    warranty: str
    positions: tuple[Position, ...]
    source: str
    """Из какого документа собрано. Спорное требование нужно уметь проверить —
    разбору исходный документ по-прежнему открыт."""


def gather(case: Any) -> CaseSpec:
    """Требования закупки из разобранных документов.

    Требования берутся из ТЗ и МЗ — документов заказчика. Из коммерческих
    предложений их брать нельзя: там поставщик пишет, что удобно ему.
    """
    заказчик = [
        document.insight
        for document in case.documents
        if document.insight is not None and str(document.insight.kind) in _CUSTOMER_KINDS
    ]
    источник = next(
        (
            document.source.name
            for document in case.documents
            if document.insight is not None and str(document.insight.kind) == "ТЗ"
        ),
        "",
    )
    return CaseSpec(
        subject=_line(case.subject),
        requirements=_requirements(заказчик, case),
        delivery=_first(insight.delivery_terms for insight in заказчик),
        warranty=_first(insight.warranty for insight in заказчик),
        positions=tuple(
            Position(
                name=_line(item.name),
                specification=_line(item.specification),
                quantity=item.quantity,
                unit=_line(item.unit),
                ens_code=_line(item.ens_code),
            )
            for item in case.requested
        ),
        source=источник,
    )


_CUSTOMER_KINDS = frozenset({"ТЗ", "МЗ"})
"""Чьи требования считаем требованиями закупки. Документы поставщиков сюда не
входят: в КП написано то, что удобно приславшему."""


def draft(folder_path: str, title: str) -> tuple[str, str]:
    """Черновик задания по позиции: сам текст и имя документа-источника.

    Пусто, если закупку ещё не разбирали. Пустое задание честнее выдуманного:
    снабжение по нему поймёт, что задание нужно написать руками, а не что
    требований к товару нет.
    """
    from platform_api.modules.tender import worklist

    known = worklist.case_spec(folder_path)
    if known is None:
        return "", ""
    return render(known, title), known.source


def render(spec: CaseSpec, title: str) -> str:
    """Задание по позиции — текстом, каким его и увидят.

    Текстом, а не набором полей: задание правит человек из разбора перед
    передачей, и «дописать строчку» должно оставаться дописыванием строчки.
    Разложенное по восьми полям задание правят так же часто, как заполняют
    восемь полей, то есть никогда.
    """
    выбрана = _match(spec.positions, title)
    позиции = (выбрана,) if выбрана is not None else spec.positions
    if not позиции:
        # Позиций заказчика ядро не нашло — папка без ценового заключения.
        # Название строки здесь единственное, что известно о товаре, и без
        # него задание выходит без предмета вовсе.
        позиции = (
            Position(name=_line(title), specification="", quantity=None, unit="", ens_code=""),
        )

    части: list[str] = ["ТЕХНИЧЕСКОЕ ЗАДАНИЕ", ""]
    if spec.subject and (выбрана is None or _same(spec.subject) != _same(выбрана.name)):
        части += [f"Предмет закупки: {spec.subject}", ""]

    for index, position in enumerate(позиции, start=1):
        номер = f"{index}. " if len(позиции) > 1 else ""
        части.append(f"{номер}{position.name or _line(title)}")
        if position.quantity is not None:
            части.append(f"   Количество: {_amount(position.quantity)} {position.unit}".rstrip())
        if position.ens_code:
            части.append(f"   Код ЕНС ТРУ: {position.ens_code}")
        if position.specification:
            части.append(f"   Характеристики: {position.specification}")
        части.append("")

    if spec.requirements:
        части.append("ТРЕБОВАНИЯ ЗАКАЗЧИКА")
        части += [f"— {item}" for item in spec.requirements]
        части.append("")
    if spec.delivery:
        части += ["МЕСТО И УСЛОВИЯ ПОСТАВКИ", spec.delivery, ""]
    if spec.warranty:
        части += ["ГАРАНТИЯ", spec.warranty, ""]

    return "\n".join(части).strip()[:MAX_LENGTH]


def document(title: str, code: str, body: str) -> bytes:
    """Задание файлом .docx — тем, что открывается у поставщика и печатается.

    Снабжение пересылает задание наружу: поставщику нужно понять, что искать.
    Пересылать ссылку на нашу платформу нельзя — там за той же позицией стоит
    себестоимость, а «просто не заходите в соседнюю вкладку» отделом снабжения
    не обеспечивается.
    """
    from io import BytesIO

    from docx import Document
    from docx.shared import Pt

    файл = Document()
    обычный = файл.styles["Normal"]
    обычный.font.name = "Calibri"
    обычный.font.size = Pt(11)

    заголовок = файл.add_paragraph()
    прогон = заголовок.add_run(f"{code} · {title}" if code else title)
    прогон.bold = True
    прогон.font.size = Pt(13)

    for строка in body.splitlines():
        абзац = файл.add_paragraph(строка)
        # Заголовки разделов набраны прописными — по ним и отбиваются, чтобы
        # не заводить вторую разметку рядом с той, которую правит человек.
        if строка and строка == строка.upper() and any(знак.isalpha() for знак in строка):
            абзац.runs[0].bold = True

    поток = BytesIO()
    файл.save(поток)
    return поток.getvalue()


# ---------------------------------------------------------------------------


_MONEY = re.compile(
    r"тенге|₸|\bkzt\b|\bндс\b|стоимост|\bцен[аыуеой]|\bцен\b|сумм|оплат|предоплат|аванс",
    re.IGNORECASE,
)
"""Признаки денежного условия в требовании.

Требования заказчика идут в задание как есть, кроме коммерческих: «цена не
выше стольких-то» — это наш потолок, а не свойство товара. Техническое
требование такими словами почти не пишется, а цена, ушедшая снабжению, торгует
против нас.
"""


def _requirements(insights: list[Any], case: Any) -> tuple[str, ...]:
    """Требования заказчика без денежных условий, без повторов, по порядку.

    Один проход по объединению: требования повторяются в ТЗ и МЗ дословно, и
    без сведения задание начинается с трёх одинаковых абзацев.
    """
    источники = [item for insight in insights for item in insight.requirements] or list(
        case.requirements
    )
    видели: set[str] = set()
    отобраны: list[str] = []
    for item in источники:
        текст = _line(item)
        ключ = _same(текст)
        if not текст or ключ in видели or _MONEY.search(текст):
            continue
        видели.add(ключ)
        отобраны.append(текст)
    return tuple(отобраны)


def _match(positions: tuple[Position, ...], title: str) -> Position | None:
    """Позиция закупки, отвечающая строке отбора.

    Строка отбора берёт название прямо из позиции заказчика, поэтому сходится
    оно точно. Когда не сходится — закупка одной позиции, у строки название
    всей закупки: тогда позиция и так одна, и брать её можно без сравнения.
    """
    искомое = _same(title)
    точная = next((item for item in positions if _same(item.name) == искомое), None)
    if точная is not None:
        return точная
    return positions[0] if len(positions) == 1 else None


def _first(values: Any) -> str:
    return next((_line(value) for value in values if _line(value)), "")


def _line(value: Any) -> str:
    return " ".join(str(value).split()) if value else ""


def _same(text: str) -> str:
    return " ".join(text.casefold().split())


def _amount(value: Decimal) -> str:
    """Количество без хвоста нулей: «105», а не «105,000»."""
    целое = value.to_integral_value()
    return f"{целое:f}" if value == целое else f"{value.normalize():f}".replace(".", ",")


__all__ = ["MAX_LENGTH", "CaseSpec", "Position", "document", "draft", "gather", "render"]
