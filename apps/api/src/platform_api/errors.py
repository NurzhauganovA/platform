"""Что платформа говорит человеку, когда что-то сломалось.

Сотрудники — закупщики и тендерщики, а не программисты. Им уходило то, что
написал питон: «'SheetRow' object has no attribute 'sources'». Прочитать это
нельзя, сделать по нему нечего, а выглядит оно так, будто человек что-то
испортил сам. За такой надписью следует звонок «у меня всё сломалось», и
дальше выясняется, что именно было на экране.

Поэтому наружу уходит короткая фраза и **код обращения** — шесть знаков,
которые видно и на экране, и в журнале. Человек называет их, и запись
находится одним поиском, вместе с полной трассировкой. Без кода приходится
угадывать по времени и имени.

Технические подробности при этом не теряются: они идут в журнал целиком.
Прячется не причина, а её вид.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status

from platform_api.logging import get_logger

logger = get_logger(__name__)


class SpokenError(Exception):
    """Ошибка, чей текст написан для человека и доходит до него как есть.

    Всё остальное — внутренняя поломка, и её текст человеку не адресован:
    «TypeError: 'NoneType' object is not subscriptable» он прочитать не может.
    Хочет обработчик что-то сказать — говорит этим исключением.
    """


def unavailable(section: str, exc: Exception) -> HTTPException:
    """Раздел не отвечает: короткая фраза человеку, подробности в журнал.

    `section` — то, что человек видит на экране: «Отбор закупок», «Закупы
    SKStore». Не имя модуля: «tender» ему ни о чём не говорит.
    """
    ref = _reference()
    logger.exception("Раздел недоступен", section=section, reference=ref)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            # «Раздел «Закупы SKStore» не отвечает», а не «Закупы SKStore не
            # отвечает»: имена разделов бывают и во множественном числе, и
            # согласовать сказуемое с каждым нельзя.
            f"Раздел «{section}» сейчас не отвечает. Это не ваша ошибка — мы её"
            f" уже видим. Если не пройдёт за пару минут, покажите администратору"
            f" код {ref}."
        ),
    )


def broke(what: str, exc: Exception) -> HTTPException:
    """Действие не выполнилось: собрать книгу, открыть документ, посчитать.

    `what` — что не получилось, глаголом: «Книга не собралась».
    """
    ref = _reference()
    logger.exception("Действие не выполнилось", what=what, reference=ref)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"{what}. Попробуйте ещё раз; если повторится — код для администратора: {ref}.",
    )


def job_failure(exc: Exception) -> str:
    """Почему не выполнилась фоновая задача — словами для того, кто её запустил.

    Ошибки самих проектов уже написаны по-человечески: «Сбой соединения»,
    «Доступ отклонён». Их и показываем. А `TypeError` и `KeyError` человеку
    не говорят ничего — вместо них короткая фраза и код обращения.
    """
    ref = _reference()
    logger.exception("Задача не выполнена", reference=ref)
    spoken = _spoken(exc)
    if spoken:
        return spoken
    return (
        "Прогон прервался из-за ошибки в платформе. Это не ваши данные —"
        f" покажите администратору код {ref}."
    )


def _spoken(exc: Exception) -> str:
    """Сообщение, написанное для человека, или пусто.

    Своими считаем ошибки подключённых проектов: они пишут «Сбой соединения» и
    «Доступ отклонён» — это готовый ответ на вопрос «что делать». Всё
    остальное — внутренняя поломка, и её текст человеку не адресован.
    """
    for base in type(exc).__mro__:
        if base.__name__ in _OUR_ERRORS:
            text = str(exc).strip()
            return text if text else ""
    return ""


_OUR_ERRORS = frozenset({"SkstoreError", "OmarketError", "TenderAnalyzeError", "SpokenError"})
"""Корни иерархий исключений, которые пишут по-человечески. По имени, а не по
классу: импортировать ядро ради проверки типа значит уронить платформу там,
где ядро не установлено."""


def _reference() -> str:
    """Код обращения: шесть знаков, которые не спутать при диктовке.

    Без похожих друг на друга: ноль и «O», единица и «I» по телефону
    неразличимы, а называть код будут именно голосом.
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = uuid.uuid4().int
    code = ""
    for _ in range(6):
        raw, index = divmod(raw, len(alphabet))
        code += alphabet[index]
    return code


__all__ = ["SpokenError", "broke", "job_failure", "unavailable"]
