"""Разметка, которую человек пишет в полях: ссылки и цвет.

В ячейке разбора и в тексте замечания человек пишет своими словами, и по
написанному работают другие. Ссылка на страницу товара и красное «не сходится
по мощности» — это то, за чем в разбор и возвращаются; в обычном тексте всё
выглядит одинаково.

Отсюда узкий набор: `<a href>`, `<span style="color">` и перевод строки. Всё
остальное — вставленное из Word, из браузера, из письма — вычищается.

**Чистится на сервере, а не только в браузере.** В базу пишет запрос, а не
страница: чистая разметка на экране ничего не говорит о том, что придёт с
чужого клиента, а лежащее в базе потом показывается всем. Вставленный
`<script>` или `javascript:` в ссылке исполнился бы с нашего адреса по нажатию
коллеги — то есть с его сессией, ценами и маржой.

Разбор, а не строка с заменами. Строкой это обходится первым же хитро
составленным атрибутом: `<a href="java&#115;cript:...">` не совпадёт ни с
одним разумным шаблоном, а браузер его поймёт.
"""

from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser

KEEP = frozenset({"a", "span", "br"})
"""Что остаётся. Больше ничего: ни жирного, ни таблиц, ни картинок."""

BLOCKS = frozenset({"p", "div", "li", "tr"})
"""Блочные превращаются в перевод строки: в ячейке таблицы их отступы дают
ряд в треть экрана, а смысл у них тот же — «здесь новая строка»."""

_COLOR = re.compile(r"^(?:var\(--color-[a-z0-9-]+\)|#[0-9a-f]{3,8}|rgba?\([\d\s.,%]+\))$", re.I)
"""Чем бывает цвет: наша переменная палитры или обычная запись.

Список закрыт намеренно. `color` принимает и `url(...)`, и выражения — а всё,
что браузер согласится вычислить, однажды окажется способом что-нибудь
подгрузить."""

_LINK = re.compile(r"^https?://", re.I)
"""Только http и https. `javascript:` в ссылке — это код, исполняемый с нашего
адреса по нажатию коллеги."""

MAX_LENGTH = 20_000
"""Предел на поле. Двадцать тысяч знаков — это десять страниц: больше в ячейку
таблицы и в замечание не пишут, а вставленный целиком документ раздувает ответ
API на каждое открытие вкладки."""


class _Tidy(HTMLParser):
    """Собирает заново только разрешённое."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._links = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        known = dict(attrs)
        if tag == "br":
            self.out.append("<br>")
            return
        if tag in BLOCKS:
            # Перед блоком — перевод строки, а не после: иначе текст начинается
            # с пустой строки, и в ячейке это выглядит сбитой вёрсткой.
            if self.out:
                self.out.append("<br>")
            return
        if tag == "a":
            href = (known.get("href") or "").strip()
            if not _LINK.match(href):
                return
            self._links += 1
            self.out.append(
                f'<a href="{escape(href, quote=True)}" target="_blank" rel="noreferrer noopener">'
            )
            return
        if tag == "span":
            color = _color_of(known.get("style") or "")
            # Без цвета `span` не нужен: он пришёл из Word вместе со шрифтом,
            # который мы всё равно выбросили.
            self.out.append(f'<span style="color:{color}">' if color else "")
            self._spans = getattr(self, "_spans", [])
            self._spans.append(bool(color))

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._links:
            self._links -= 1
            self.out.append("</a>")
        elif tag == "span":
            spans: list[bool] = getattr(self, "_spans", [])
            if spans and spans.pop():
                self.out.append("</span>")

    def handle_data(self, data: str) -> None:
        self.out.append(escape(data, quote=False))

    def result(self) -> str:
        # Незакрытые ссылки закрываем сами: обрезанная разметка иначе
        # проглатывает остаток строки в ссылку.
        return "".join(self.out) + "</a>" * self._links


def _color_of(style: str) -> str:
    for part in style.split(";"):
        name, _, value = part.partition(":")
        if name.strip().lower() != "color":
            continue
        clean = value.strip()
        return clean if _COLOR.match(clean) else ""
    return ""


def tidy(raw: str) -> str:
    """Оставляет из разметки только ссылку, цвет и перевод строки.

    Не падает ни на чём: битая разметка, обрезанный тег, чужой документ целиком
    — всё это повод вычистить и сохранить, а не отдать пятисотую. Поле с
    текстом не то место, где человек должен угадывать, что ему не понравилось.
    """
    if not raw:
        return ""
    parser = _Tidy()
    parser.feed(raw[:MAX_LENGTH])
    parser.close()
    return parser.result().strip()


def plain(raw: str) -> str:
    """Тот же текст без разметки — для письма, выгрузки и поиска.

    Замечание уходит заказчику через портал, книга собирается Excel'ем, а
    поиск идёт по словам: в каждом из этих мест `<span style="color:red">`
    читался бы как текст.
    """
    without = re.sub(r"<br\s*/?>", "\n", raw or "", flags=re.I)
    without = re.sub(r"<[^>]+>", "", without)
    return (
        without.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .strip()
    )


__all__ = ["MAX_LENGTH", "plain", "tidy"]
