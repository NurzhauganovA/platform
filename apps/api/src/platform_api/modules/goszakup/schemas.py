"""Формы ответов модуля госзакупок.

Отдельно от моделей ядра: по ним генерируется клиент фронтенда, и отдавать
домен напрямую значит ломать интерфейс любой внутренней правкой.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class ModuleHealth(BaseModel):
    """Готовность модуля к работе."""

    ok: bool
    core_version: str
    database: str = ""
    lots: int = 0
    codes: int = 0
    """Сколько кодов ЕНС ТРУ отслеживается. Ноль означает, что обход не найдёт
    ничего: он идёт строго по списку."""

    harvested_at: str = ""
    problems: list[str] = []


class WatchedCodeOut(BaseModel):
    """Код ЕНС ТРУ в списке настроек парсинга."""

    code: str
    name: str = ""
    active: bool = True
    note: str = ""
    category: str = ""
    """Наша категория товара. По ней делят работу между людьми: ноутбуки
    ведёт один человек, серверы другой."""

    platform: str = "goszakup"


class WatchedCodeIn(BaseModel):
    """Что добавляют в список."""

    code: str
    note: str = ""
    category: str = ""
    platform: str = ""


class CategoryIn(BaseModel):
    """Наша категория товара для кода."""

    category: str


class PlatformIn(BaseModel):
    """На какой площадке искать этот код.

    Пусто — на всех сразу. Портал единый, и лоты ЭГЗ, Mitwork и SKK лежат в
    нём вперемешку; сузить отбор проще, чем однажды обнаружить, что половина
    закупок не приходит.
    """

    platform: str


class RemarkStartedOut(BaseModel):
    """Заведённое обсуждение и поставленная задача написания.

    Возвращаются оба: по первому браузер открывает карточку обсуждения, по
    второму подписывается на поток прогресса. Без задачи человек смотрит на
    пустой текст и не знает, пишется он или уже не будет.
    """

    remark_id: str
    job_id: uuid.UUID
