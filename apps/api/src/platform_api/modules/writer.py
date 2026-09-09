"""Вызов модели, которая пишет замечание.

Отделён от сборки подсказки (`writing.py`) намеренно: подсказку и очистку
ответа проверяют тестами без сети и без денег, а здесь остаётся один поход
наружу, который в тестах подменяется.

Модель — Gemini, та же, что у подключённых ядер, и ключ тот же
(`GEMINI_API_KEY` из окружения). Второй поставщик означал бы второй счёт,
второй ключ в `.env` и второй набор причин, по которым сегодня не работает.

Запасные модели перечислены рядом с основной, как в ядрах: у предварительных
моделей квота кончается посреди дня, а замечание пишется под срок — два
рабочих дня со дня объявления. Какой именно моделью оно написано, важно
меньше, чем то, что оно написано вовремя; чем именно, видно в карточке.

Ошибки модели — не поломка платформы, а обстоятельство. Кончилась квота,
модель перегружена, ответ не пришёл за три минуты: во всех случаях замечание
остаётся ненаписанным, менеджер видит причину словами и пишет сам. Упавшая
задача вместо этого показала бы ему красный крест без объяснений.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import TYPE_CHECKING, Any

from platform_api.config import Settings
from platform_api.db.base import utcnow
from platform_api.logging import get_logger
from platform_api.modules import writing

if TYPE_CHECKING:
    from platform_api.modules.writing import Draft, Subject

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Answer:
    """Что вернул поход к модели: текст, чем отвечено и почему не вышло."""

    text: str = ""
    model: str = ""
    trouble: str = ""

    cut: bool = False
    """Ответ упёрся в потолок объёма и оборван на полуслове.

    Отдельным признаком, а не пустым текстом: обрезанный ответ приходит
    непустым, и без этого признака разбор падал на «модель ответила не
    таблицей» — сообщение, по которому чинят не то. Причина же одна и
    понятная: спецификация длиннее, чем отведённый объём.
    """


def ask(
    prompt: str,
    settings: Settings,
    *,
    about: str = "",
    max_tokens: int | None = None,
    json_only: bool = False,
) -> Answer:
    """Спрашивает модель, перебирая запасные по порядку.

    Общий вход для всего, что платформа спрашивает у Gemini: и замечание
    заказчику, и разбор спецификации таблицей. Второй такой перебор разошёлся
    бы с первым на первой же правке — а правки здесь про деньги и про сроки:
    у предварительных моделей квота кончается посреди дня.

    `max_tokens` — свой потолок объёма на этот вопрос. У замечания и у разбора
    спецификации он разный: замечание это страница текста, а разбор переносит
    требования дословно и растёт вместе с исходником.

    `json_only` — просить у модели сразу JSON. Просьба «ответь только JSON»
    словами выполняется через раз: то обёртка ```json, то строка «Вот таблица»
    перед ней. Заданный формат ответа снимает и то и другое.

    Не бросает исключение. Отказ модели — обстоятельство, а не поломка
    платформы: причина возвращается словами, и человек делает то же самое
    руками.
    """
    trouble = ""
    for model in _models(settings):
        try:
            raw, cut = _ask(prompt, model, settings, max_tokens=max_tokens, json_only=json_only)
        except Exception as exc:
            trouble = _spoken(exc)
            logger.warning("model.failed", about=about, model=model, error=str(exc))
            if not _worth_retrying(exc):
                break
            continue
        if raw.strip():
            if cut:
                logger.warning("model.cut", about=about, model=model, chars=len(raw))
            return Answer(text=raw, model=model, cut=cut)
        trouble = "Модель вернула пустой ответ"
    return Answer(trouble=trouble or "Модель не ответила")


def write(subject: Subject, settings: Settings, *, today: date | None = None) -> Draft:
    """Пишет замечание по закупке.

    Возвращает пустой текст с объяснением, а не бросает исключение. Задача
    считается выполненной: она сходила к модели и принесла результат, пусть и
    отрицательный.
    """
    answer = ask(
        writing.prompt(subject, today=today or utcnow().date()),
        settings,
        about=subject.code,
    )
    if not answer.text:
        return writing.Draft(text="", grounds=(), trouble=answer.trouble)
    draft = writing.shape(answer.text)
    if draft.text or draft.trouble:
        return replace(draft, model=answer.model)
    return writing.Draft(text="", grounds=(), trouble="Модель вернула пустой ответ")


def _models(settings: Settings) -> tuple[str, ...]:
    """Основная модель и запасные, по порядку."""
    return (settings.writer.model, *settings.writer.model_backups)


def _ask(
    prompt: str,
    model: str,
    settings: Settings,
    *,
    max_tokens: int | None = None,
    json_only: bool = False,
) -> tuple[str, bool]:
    """Один поход к модели. Возвращает ответ и признак «оборван по объёму»."""
    from google.genai import types

    client = _client(settings)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=max_tokens or settings.writer.max_tokens,
            thinking_config=_thinking(model, settings.writer.thinking_level, types),
            **({"response_mime_type": "application/json"} if json_only else {}),
        ),
    )
    text = getattr(response, "text", None)
    if not text:
        raise RuntimeError(_why_empty(response))
    return str(text), _hit_ceiling(response)


def _hit_ceiling(response: Any) -> bool:
    """Упёрся ли ответ в потолок объёма.

    Смотрим, даже когда текст пришёл: Gemini отдаёт написанное до обрыва, и
    внешне такой ответ неотличим от целого — пока не начнёшь его разбирать.
    """
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return False
    reason = getattr(candidates[0], "finish_reason", None)
    return (getattr(reason, "name", None) or str(reason or "")) == "MAX_TOKENS"


def _thinking(model: str, level: str, types: Any) -> Any:
    """Настройка обдумывания в том виде, в каком её принимает эта модель.

    У линеек параметр разный: 3.x понимает `thinking_level`, 2.5 — только
    `thinking_budget` в токенах и на чужом параметре отвечает 400.

    Своя копия, а не заимствование у tender-analyze. Правило это про SDK
    Gemini, а не про разбор тендеров, и брать его из чужого пакета значило бы
    сломать замечания при переименовании внутри соседнего проекта — того
    самого, к чьим внутренностям платформе ходить и не полагается.
    """
    if model.startswith("gemini-3"):
        return types.ThinkingConfig(thinking_level=level)
    budget = {"LOW": 2_048, "MEDIUM": 8_192, "HIGH": 24_576}.get(level, 8_192)
    return types.ThinkingConfig(thinking_budget=budget)


def _client(settings: Settings) -> Any:
    """Клиент Gemini.

    Срок задаётся явно: по умолчанию SDK ждёт ответа бесконечно, и зависший
    вызов держал бы место в очереди, пока срок обсуждения не пройдёт.
    """
    from google import genai
    from google.genai import types

    return genai.Client(
        http_options=types.HttpOptions(timeout=int(settings.writer.timeout_seconds * 1000))
    )


def _why_empty(response: Any) -> str:
    """Отчего ответа нет — словами, которые говорят, что чинить.

    Причина лежит в `finish_reason` кандидата и лечится по-разному:
    `MAX_TOKENS` — ответ обрезан и потолок надо поднимать, `SAFETY` — подсказку
    надо переписывать. Без этого в карточке стояло бы «модель не ответила», по
    которому нельзя понять ровно ничего.
    """
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        blocked = getattr(getattr(response, "prompt_feedback", None), "block_reason", None)
        return f"Модель отклонила запрос: {blocked}" if blocked else "Модель ответила пустым"
    reason = getattr(candidates[0], "finish_reason", None)
    name = getattr(reason, "name", None) or str(reason or "причина не указана")
    if name == "MAX_TOKENS":
        return "Ответ не поместился в отведённый объём и обрезан целиком"
    return f"Модель прервала ответ: {name}"


def _worth_retrying(exc: Exception) -> bool:
    """Стоит ли пробовать запасной моделью.

    Занятость и кончившаяся квота — про конкретную модель, и соседняя может
    ответить. Отсутствующий ключ и отклонённый запрос — про нас: перебирать
    модели значит потратить втрое больше времени на тот же отказ.
    """
    words = f"{type(exc).__name__} {exc}".lower()
    свои = ("api key", "api_key", "credential", "permission", "unauthorized", "отклонила")
    return not any(word in words for word in свои)


def _spoken(exc: Exception) -> str:
    """Причина неудачи словами человека.

    Без имени класса исключения: «ResourceExhausted» менеджеру ничего не
    говорит, а решение у него в обоих случаях одно — написать самому или
    нажать ещё раз попозже.
    """
    words = f"{type(exc).__name__} {exc}".lower()
    # Незаполненный ключ SDK сообщает длинной английской фразой. Для человека
    # это выглядит поломкой платформы, хотя чинится одной строкой в `.env` — и
    # чинит её администратор, а не тот, кто нажал кнопку.
    if "api key" in words or "api_key" in words or "credential" in words:
        return "Не задан ключ модели: пропишите GEMINI_API_KEY в .env платформы и перезапустите"
    if "resource" in words and "exhaust" in words:
        return "Дневная квота модели исчерпана, замечание придётся написать самим"
    if "429" in words or "rate" in words or "quota" in words:
        return "Модель занята, попробуйте ещё раз через несколько минут"
    if "unavailable" in words or "503" in words or "overload" in words:
        return "Модель сейчас недоступна, попробуйте позже"
    if "timeout" in words or "deadline" in words:
        return "Модель не ответила вовремя"
    if "permission" in words or "unauthorized" in words:
        return "Ключ модели не принят: проверьте GEMINI_API_KEY"
    return str(exc) if str(exc).startswith(("Модель", "Ответ")) else f"Не удалось написать: {exc}"


__all__ = ["Answer", "ask", "write"]
