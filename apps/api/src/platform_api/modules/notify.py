"""Связь с сервисом уведомлений: поставить заявку и вести реестр людей.

Один вход на всю платформу. Обработчики зовут `about(...)`, а куда именно
уйдёт сообщение — в Телеграм, письмом или никуда, потому что сервис не
поднят, — решается здесь и в самом сервисе.

**Ничего не бросает наружу.** Несделанная рассылка — это плохо; несохранённая
задача — хуже. Отказ сервиса, оборванная сеть, истёкший срок ответа — всё это
пишется в журнал предупреждением, а обработчик идёт дальше и отвечает
человеку. Обратное однажды означало бы, что лот нельзя взять в работу, пока
чинят бота.

**Тексты живут в сервисе, а не здесь.** Платформа присылает имя события и его
поля — «задача назначена, вот лот, вот срок»; как это звучит, решает
`templates.py` сервиса. Иначе формулировка расходится по десятку обработчиков,
и одно и то же событие приходит то «Новая задача», то «Вам назначена задача».

**Адрес — путь, а не полная ссылка.** Домен подставит сервис: у проверочной
среды он свой, и зашитый здесь `bcorp.kz` уводил бы человека из stage в
рабочую платформу.

Реестр людей ведёт платформа: сервис не ходит за сотрудниками в чужую базу,
иначе он замолкает ровно тогда, когда платформу остановили на обновление.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from platform_api.config import Settings
from platform_api.logging import get_logger

logger = get_logger(__name__)

SOURCE = "platform"
"""Чем помечены наши заявки в истории сервиса."""


def about(
    settings: Settings,
    *,
    event: str,
    payload: dict[str, Any],
    users: list[uuid.UUID] | None = None,
    emails: list[str] | None = None,
    url: str = "",
    deadline: str = "",
    group: str = "",
    remind_before_minutes: list[int] | None = None,
    idempotency_key: str = "",
    title: str = "",
    body_text: str = "",
) -> bool:
    """Ставит уведомление. Возвращает, дошла ли заявка до сервиса.

    Получателей может быть несколько: «нужна подпись» уходит пяти отделам
    сразу, и пять запросов вместо одного — это пять поводов для сервиса
    ответить отказом на середине.

    `group` — общий ключ, по которому потом снимать. Закрыли задачу — гаснут
    напоминания о её сроке: напоминание о закрытой вчера задаче обесценивает
    всю рассылку, и на второй раз человек перестаёт открывать сообщения бота.

    `idempotency_key` спасает от повтора обработчика: задача ставится из
    прогона, а прогон бывает повторён.
    """
    to: list[dict[str, str]] = [{"user_id": str(one)} for one in users or ()]
    to += [{"email": one} for one in emails or ()]
    if not to:
        return False

    body: dict[str, Any] = {"to": to, "event": event, "payload": payload, "source": SOURCE}
    # Готовый текст сильнее заготовки. Так уходит то, чего в списке событий
    # сервиса ещё нет: он не должен становиться местом, куда ходят за правкой
    # одной фразы. Прижилось — заводится заготовка, и текст уходит отсюда.
    if title:
        body["title"] = title
    if body_text:
        body["body"] = body_text
    if url:
        body["url"] = url
    if deadline:
        body["deadline"] = deadline
    if group:
        body["group"] = group
    if remind_before_minutes:
        body["remind_before_minutes"] = remind_before_minutes
    if idempotency_key:
        body["idempotency_key"] = idempotency_key

    return _post(settings, "/api/notifications", body) is not None


def drop(settings: Settings, *, group: str) -> None:
    """Снимает неотправленное по общему ключу.

    Отправленное не отменяется — из чужого Телеграма сообщение не забрать.
    """
    _post(settings, "/api/notifications/cancel", {"group": group})


def enroll(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    email: str,
    full_name: str,
    role: str = "",
    is_active: bool = True,
) -> None:
    """Заводит или обновляет человека в реестре сервиса.

    Зовётся при правке сотрудника, а не по расписанию: человек меняет почту и
    ждёт, что письмо придёт на новую, а не через час.

    Настройки каналов не трогаются — их правит сам человек, и выгрузка,
    которая их перезаписывает, возвращала бы отключённый в боте Телеграм при
    каждом сохранении профиля.
    """
    _post(
        settings,
        "/api/recipients",
        {
            "user_id": str(user_id),
            "email": email,
            "full_name": full_name,
            "role": role,
            "is_active": is_active,
        },
    )


def sync_all(settings: Settings, people: list[dict[str, Any]]) -> None:
    """Отдаёт сервису список сотрудников целиком.

    Полная выгрузка с `deactivate_missing`: кого нет в списке, тот больше не
    работает. Частичная оставила бы уволившегося получать письма о наших
    закупках — заметили бы это не скоро.

    Зовётся при запуске платформы. Сервис живёт своей жизнью и переживает наши
    выкладки; между ними человека могли завести, переименовать или выключить, и
    догонять это по одному событию значит однажды пропустить одно из них.

    Настройки каналов выгрузка не трогает — так устроен сервис: иначе
    отключённый в боте Телеграм возвращался бы при каждом запуске платформы.
    """
    if not people:
        return
    _post(settings, "/api/recipients/sync", {"people": people, "deactivate_missing": True})


def channels(settings: Settings, *, user_id: uuid.UUID) -> dict[str, Any] | None:
    """Что у человека настроено: каналы и привязан ли Телеграм.

    `None` — сервис не ответил или не знает такого. Разницы между «не знает» и
    «не отвечает» экрану не нужно: и там и там показывать нечего, а объяснение
    для человека одно — «настройки уведомлений сейчас недоступны».
    """
    return _get(settings, f"/api/recipients/{user_id}")


def set_channels(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    telegram_enabled: bool | None = None,
    email_enabled: bool | None = None,
) -> dict[str, Any] | None:
    """Меняет каналы человека. Решает он сам, а не администратор."""
    body: dict[str, Any] = {}
    if telegram_enabled is not None:
        body["telegram_enabled"] = telegram_enabled
    if email_enabled is not None:
        body["email_enabled"] = email_enabled
    if not body:
        return channels(settings, user_id=user_id)
    answer = _request(settings, "PATCH", f"/api/recipients/{user_id}", body)
    return answer if isinstance(answer, dict) else None


def unlink_telegram(settings: Settings, *, user_id: uuid.UUID) -> None:
    """Отвязывает чат. Уведомления после этого идут почтой: человек отказался
    от Телеграма, а не от работы."""
    _request(settings, "DELETE", f"/api/recipients/{user_id}/telegram", None)


def alive(settings: Settings) -> dict[str, Any] | None:
    """Готовность сервиса: настроены ли каналы и что он сам считает пробелами.

    Открыта без ключа — её же опрашивает Docker. Отвечает даже тогда, когда у
    сервиса недоступна база: проверка смотрит настройки, а не хранилище.
    Поэтому одной её мало, и рядом всегда спрашивается сводка.
    """
    return _get(settings, "/api/health", guarded=False)


def counters(settings: Settings) -> dict[str, Any] | None:
    """Сводка рассылки: сколько людей, сколько привязано, что не дошло.

    Собирается из базы сервиса, поэтому заодно доказывает, что база у него
    жива, — в отличие от готовности.
    """
    return _get(settings, "/api/stats")


def everyone(settings: Settings) -> list[dict[str, Any]] | None:
    """Весь реестр сервиса: у кого привязан Телеграм, кто что себе отключил.

    Список приходит от сервиса, а не собирается из базы платформы. Реестр —
    его, и вопрос «почему Ивану не приходит» решается взглядом именно туда:
    человек мог отключить канал в боте, и платформа об этом не знает.
    """
    answer = _request(settings, "GET", "/api/recipients", None, listed=True)
    return answer if isinstance(answer, list) else None


def history(settings: Settings, *, user_id: uuid.UUID, limit: int = 10) -> list[dict[str, Any]]:
    """Чем кончились последние отправки человеку.

    Причина неудачи лежит у доставки, а не у уведомления: «Телеграм не
    привязан», «тихие часы», отказ почтового сервера словами. Это и есть
    ответ на «почему не пришло» — остальное про него только догадки.
    """
    answer = _request(
        settings,
        "GET",
        f"/api/notifications?user_id={user_id}&limit={limit}",
        None,
        listed=True,
    )
    return answer if isinstance(answer, list) else []


def check(settings: Settings, *, user_id: uuid.UUID) -> bool:
    """Ставит человеку проверочное сообщение. Возвращает, приняли ли заявку."""
    return _post(settings, f"/api/recipients/{user_id}/test", {}) is not None


def _post(settings: Settings, path: str, body: dict[str, Any]) -> dict[str, Any] | None:
    answer = _request(settings, "POST", path, body)
    return answer if isinstance(answer, dict) else None


def _get(settings: Settings, path: str, *, guarded: bool = True) -> dict[str, Any] | None:
    answer = _request(settings, "GET", path, None, guarded=guarded)
    return answer if isinstance(answer, dict) else None


def _request(
    settings: Settings,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    *,
    guarded: bool = True,
    listed: bool = False,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    """Один запрос к сервису. Молчит в журнал и возвращает `None` при отказе.

    Сервис не настроен — уходим сразу и без записи: у разработчика он обычно
    не поднят, и строка в журнале на каждое действие превратила бы вывод в
    ленту о том, чего не делаем намеренно.
    """
    if not settings.notify.ready:
        return None

    base = settings.notify.url.rstrip("/")
    try:
        with httpx.Client(timeout=settings.notify.timeout_seconds) as http:
            answer = http.request(
                method,
                f"{base}{path}",
                headers={"X-Service-Token": settings.notify.token} if guarded else {},
                json=body,
            )
        if answer.status_code >= 400:
            logger.warning(
                "Сервис уведомлений отказал",
                path=path,
                status=answer.status_code,
                answer=answer.text[:300],
            )
            return None
        if not answer.content:
            return [] if listed else {}
        found = answer.json()
        if listed:
            return [dict(one) for one in found] if isinstance(found, list) else []
        return dict(found)
    except (httpx.HTTPError, ValueError) as exc:
        # Именно предупреждение, а не ошибка: платформа работает дальше, и
        # красная строка в журнале звала бы чинить то, что чинится само.
        logger.warning("Сервис уведомлений недоступен", path=path, error=str(exc))
        return None


__all__ = [
    "SOURCE",
    "about",
    "channels",
    "drop",
    "enroll",
    "set_channels",
    "unlink_telegram",
]
