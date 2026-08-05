"""Структурированное логирование платформы.

Устроено так же, как в подключённых проектах, и намеренно: когда веб-запрос,
фоновая задача и разбор пишут в один поток разными форматами, читать этот
поток невозможно ровно в тот момент, когда он нужен.

Маскирование обязательно. В логи попадают сообщения об ошибках SDK, а в них
может оказаться ключ API — дешевле вырезать его на выходе, чем потом чистить
историю логов. К ключам Anthropic и Google здесь добавлены куки сессий: они
такой же пропуск внутрь, как и ключ.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

_SECRET_PATTERNS = (
    # Ключи Anthropic (sk-ant-...) и Google (AIza...). Хвост любой длины.
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|token|password|secret|cookie)[\"'\s:=]+[^\s\"',}]+"),
)


def redact(value: str) -> str:
    """Убирает секреты из строки."""
    result = _SECRET_PATTERNS[0].sub("sk-ant-***", value)
    result = _SECRET_PATTERNS[1].sub("AIza***", result)
    return _SECRET_PATTERNS[2].sub(r"\1=***", result)


def _redact_processor(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key, value in event_dict.items():
        if isinstance(value, str):
            event_dict[key] = redact(value)
    return event_dict


def configure_logging(level: str = "INFO", fmt: str = "console") -> None:
    """Настраивает structlog и стандартный logging единообразно."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    # Библиотеки разбора болтливы до неприличия, а платформа тянет их через
    # подключённые проекты: pdfminer комментирует раскладку шрифтов, extract_msg
    # — каждый отсутствующий поток OLE. Плюс uvicorn.access, который дублирует
    # наш же лог запроса.
    for noisy in ("httpx", "httpcore", "pdfminer", "PIL", "extract_msg", "py7zr"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    logging.getLogger("uvicorn.access").disabled = True

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
