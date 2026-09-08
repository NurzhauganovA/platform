"""Прогоны раздела работы. Пока один — суточный вывоз журнала действий.

Журнал живёт в базе, и это правильно: запись идёт своей транзакцией, попадает в
те же резервные копии, ищется обычным запросом. Но база лежит в томе Docker, а
том сносится одной командой — `make clean`, переезд, чистка места. И это не
теория: виртуальный диск Docker уже переполнялся, и PostgreSQL падал на докатке
журнала с «No space left on device».

Поэтому раз в сутки журнал вывозится файлом на диск самой машины — в каталог,
подключённый томом. Файл переживает и снос томов, и переполнение, и переезд.
Формат построчный JSON и сжатие: строка на запись читается чем угодно, вплоть
до `zgrep`, а разбирать его целиком ради одной строки не нужно.

Файлы не чистятся. Они и есть то, что должно пережить всё остальное; место они
занимают несравнимо меньшее, чем то, ради чего их держат.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from platform_api.config import get_settings
from platform_api.db.models import AuditEntry
from platform_api.jobs.contract import JobContext, JobSpec
from platform_api.logging import get_logger

logger = get_logger(__name__)


def export_audit(ctx: JobContext, **_: Any) -> dict[str, Any]:
    """Вывозит вчерашний журнал файлом и подчищает старое в базе.

    Вчерашний, а не сегодняшний: сутки должны кончиться, иначе выгрузка
    получается неполной и её приходится переписывать — а переписанный файл уже
    не доказательство.

    Готовый файл не переписывается. Повторный прогон в тот же день — обычное
    дело после перезапуска, и затирать им вчерашнюю выгрузку значит однажды
    затереть её наполовину записанной.
    """
    settings = get_settings()
    root = Path(settings.audit.root)
    root.mkdir(parents=True, exist_ok=True)

    day = (datetime.now(UTC) - timedelta(days=1)).date()
    since = datetime(day.year, day.month, day.day, tzinfo=UTC)
    until = since + timedelta(days=1)
    target = root / f"audit-{day.isoformat()}.jsonl.gz"

    if target.exists():
        logger.info("audit.export.skipped", file=target.name)
        return {"file": target.name, "written": 0, "skipped": True}

    ctx.advance(0, total=2, note=f"Вывозим журнал за {day.isoformat()}")
    rows = list(
        ctx.db.scalars(
            select(AuditEntry)
            .where(AuditEntry.created_at >= since, AuditEntry.created_at < until)
            .order_by(AuditEntry.created_at)
        )
    )

    # Через временный файл: прерванный прогон иначе оставляет обрезанный
    # архив с настоящим именем, и отличить его от полного нельзя ничем.
    draft = target.with_suffix(".tmp")
    with gzip.open(draft, "wt", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(_as_row(row), ensure_ascii=False) + "\n")
    draft.replace(target)

    ctx.advance(1, total=2, note="Чистим старое в базе")
    edge = datetime.now(UTC) - timedelta(days=settings.audit.keep_days)
    old = ctx.db.query(AuditEntry).filter(AuditEntry.created_at < edge).delete()
    ctx.db.commit()

    logger.info("audit.export.done", file=target.name, rows=len(rows), removed=old)
    return {"file": target.name, "written": len(rows), "removed": old}


def _as_row(row: AuditEntry) -> dict[str, Any]:
    """Запись строкой. Все поля как есть: файл — доказательство, и урезать в
    нём нечего, секреты вырезаны ещё при записи."""
    return {
        "id": str(row.id),
        "at": row.created_at.isoformat(),
        "user_id": str(row.user_id) if row.user_id else None,
        "organization_id": str(row.organization_id) if row.organization_id else None,
        "role": row.role,
        "action": row.action,
        "target": row.target,
        "method": row.method,
        "path": row.path,
        "status": row.status,
        "duration_ms": row.duration_ms,
        "ip": row.ip_address,
        "user_agent": row.user_agent,
        "payload": row.payload,
    }


jobs = (
    # Раз в сутки. Минута своя: пятая, двадцатая и тридцать пятая заняты
    # выгрузками площадок, а три прогона, стартующие разом, дерутся за
    # единственный процессор и растягивают друг друга втрое.
    #
    # Бесплатно: модель здесь не участвует, читается своя же база.
    JobSpec(
        kind="audit",
        handler=export_audit,
        title="Вывоз журнала действий",
        every_hours=24,
        at_minute=50,
    ),
)

__all__ = ["export_audit", "jobs"]
