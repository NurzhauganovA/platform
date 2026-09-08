"""Журнал действий: каждое изменение, без исключений.

Посредником, а не вызовом в обработчике. Выборочная запись держится на памяти
того, кто писал обработчик: первый же новый эндпоинт оказывается вне журнала, и
замечают это ровно тогда, когда журнал понадобился — при разборе того, кто снял
лот с участия. Посредник видит все запросы и не забывает ни одного.

Пишутся изменения: POST, PUT, PATCH, DELETE. Чтения не пишутся намеренно —
страницу открывают по сотне раз за день, и журнал из просмотров хоронит в себе
те три строки, ради которых его и завели. Кто что видел, отвечает право
доступа, а не журнал.

**Своей транзакцией.** Действие могло не удаться, и откат данных не должен
уносить с собой запись о попытке: неудавшаяся попытка выдать себе роль
администратора интересна не меньше удавшейся. Поэтому отдельная сессия, свой
`commit`, и он идёт после того, как основная транзакция уже закрыта.

**Секреты вырезаны по имени поля.** Пароли, коды подтверждения, служебные ключи
в журнал не попадают: его читают люди, и его же однажды выгрузят наружу.

**Отказ журнала не роняет запрос.** Человек не должен получить красный экран
из-за того, что не записалась строка о его действии. Но и молчать нельзя:
несделанная запись пишется предупреждением, и по нему видно, что журнал неполон.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from platform_api.db.base import utcnow
from platform_api.db.models import AuditEntry
from platform_api.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = get_logger(__name__)

WATCHED = frozenset({"POST", "PUT", "PATCH", "DELETE"})
"""Что записывается. Чтения не пишутся: их сотни в день, и они хоронят в себе
те три строки, ради которых журнал и заводят."""

SECRET_FIELDS = frozenset(
    {
        "password",
        "current",
        "fresh",
        "code",
        "token",
        "secret",
        "api_key",
        "gemini_api_key",
        "anthropic_api_key",
    }
)
"""Поля, значения которых в журнал не идут. По имени, а не по содержимому:
угадывать пароль по виду строки — это пропустить его в первый же раз, когда
человек выберет пароль, похожий на обычное слово."""

MAX_BODY = 4_000
"""Сколько знаков тела запроса хранить. Четыре тысячи — это разбор
спецификации целиком; больше присылают только выгрузки, и от них в журнале
нужен факт, а не содержимое."""

SKIP_PATHS = ("/api/health", "/api/ready")
"""Что не писать. Проверки готовности идут от Docker каждые пятнадцать секунд —
за сутки это шесть тысяч строк ни о чём."""


class AuditMiddleware(BaseHTTPMiddleware):
    """Пишет каждое изменение после того, как ответ собран.

    После, а не до: до ответа неизвестен ни код, ни то, дошло ли действие до
    конца. Отказ в правах — это ровно та запись, ради которой журнал и нужен, и
    отличить её от успеха можно только по коду ответа.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in WATCHED or request.url.path.startswith(SKIP_PATHS):
            return await call_next(request)

        body = await _read_body(request)
        started = time.perf_counter()
        response = await call_next(request)
        spent = int((time.perf_counter() - started) * 1000)

        try:
            _write(request, response, body=body, spent=spent)
        # Ловим всё: несделанная запись не должна ронять ответ человеку. Но и
        # молчать нельзя — по предупреждению видно, что журнал неполон.
        except Exception as exc:
            logger.warning(
                "Действие не записано в журнал",
                path=request.url.path,
                method=request.method,
                error=str(exc),
            )
        return response


async def _read_body(request: Request) -> dict[str, Any] | None:
    """Тело запроса без секретов. Файлы и крупное не читаются.

    Читается до обработчика и остаётся в кэше запроса — Starlette отдаёт его
    обработчику повторно. Иначе поток был бы вычитан нами, и обработчик получил
    бы пустое тело.

    Загрузки файлов пропускаются: тендерная папка весит мегабайты, и класть её
    в журнал значит растить базу тем, что уже лежит в хранилище.
    """
    kind = request.headers.get("content-type", "")
    if "multipart/form-data" in kind or "octet-stream" in kind:
        return {"": "файл не записан"}
    try:
        raw = await request.body()
    except Exception:
        return None
    if not raw:
        return None
    if len(raw) > MAX_BODY * 4:
        return {"": f"тело в {len(raw)} байт не записано"}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {"": raw.decode("utf-8", "replace")[:MAX_BODY]}
    clean = _clean(parsed)
    # Тело бывает и списком, и числом: у списка нет имён полей, а журналу они
    # нужны — иначе в нём лежит голый массив, по которому потом не искать.
    return clean if isinstance(clean, dict) else {"": clean}


def _clean(value: Any) -> Any:
    """Убирает секреты и обрезает длинное. Рекурсивно: пароль бывает вложенным."""
    if isinstance(value, dict):
        return {
            key: ("<скрыто>" if str(key).lower() in SECRET_FIELDS else _clean(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_clean(item) for item in value[:50]]
    if isinstance(value, str) and len(value) > MAX_BODY:
        return value[:MAX_BODY] + "…"
    return value


def _write(request: Request, response: Response, *, body: Any, spent: int) -> None:
    """Кладёт запись своей сессией и своим `commit`.

    Своей — чтобы откат основной транзакции не унёс запись о попытке. Сессия
    берётся из той же фабрики, что и рабочая: своё соединение к базе ради
    журнала означало бы второй набор настроек и второй повод не подняться.
    """
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        return

    identity = getattr(request.state, "identity", None)
    action = f"{request.method} {_pattern(request)}"

    with factory() as db:
        db.add(
            AuditEntry(
                organization_id=identity.organization.id if identity else None,
                user_id=identity.user.id if identity else None,
                role=str(identity.role.value) if identity else "",
                action=action[:64],
                target=_target(request),
                payload=body if isinstance(body, dict) else {},
                method=request.method,
                path=str(request.url.path)[:512],
                status=response.status_code,
                duration_ms=spent,
                ip_address=_ip(request),
                user_agent=request.headers.get("user-agent", "")[:512],
                created_at=utcnow(),
            )
        )
        db.commit()


def _pattern(request: Request) -> str:
    """Адрес с ключами, заменёнными на имена: `/api/cards/{card_id}/tasks`.

    Собирается из настоящего адреса подстановкой, а не берётся у маршрута.
    Маршрут отдаёт свой путь без общего префикса — роутеры вложены друг в
    друга, — и в журнале оказывалось `/cards/…` вместо `/api/cards/…`: отбор
    по нему не сходился ни с чем.

    Образец, а не адрес, потому что по нему собираются события одного рода.
    Адрес с подставленным ключом уникален, и отбор «покажи все переводы лота»
    по нему невозможен.
    """
    path = request.url.path
    for name, value in (request.scope.get("path_params") or {}).items():
        text = str(value)
        if text:
            path = path.replace(text, "{" + name + "}", 1)
    return path


def _target(request: Request) -> str:
    """К чему относилось действие: ключи из адреса.

    Из образца пути, а не разбором адреса: `{card_id}` в образце прямо говорит,
    что этот кусок — ключ, а угадывание по виду однажды примет за ключ слово
    «tasks».
    """
    values = request.scope.get("path_params") or {}
    if not values:
        return ""
    return ", ".join(f"{key}={value}" for key, value in values.items())[:255]


def _ip(request: Request) -> str:
    """Адрес, с которого пришли.

    Сперва `X-Forwarded-For`: наружу платформа смотрит через Cloudflare Tunnel и
    nginx, и без этого в журнале у всех был бы один адрес — соседнего
    контейнера, то есть никакой.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


def note(
    db: Any,
    *,
    user_id: uuid.UUID | None,
    organization_id: uuid.UUID | None,
    action: str,
    target: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    """Запись о том, чего в HTTP не видно.

    Посредник пишет запросы, а часть работы делают прогоны: обход портала,
    написание замечания, разбор спецификации. Для них — этот вход. Пишется в ту
    же таблицу: два журнала означали бы два места, куда смотреть, и вопрос «а
    там точно всё» к каждому из них.
    """
    db.add(
        AuditEntry(
            organization_id=organization_id,
            user_id=user_id,
            action=action[:64],
            target=target[:255],
            payload=_clean(payload or {}),
            method="",
            path="",
            status=0,
            created_at=utcnow(),
        )
    )


__all__ = ["MAX_BODY", "SECRET_FIELDS", "WATCHED", "AuditMiddleware", "note"]
