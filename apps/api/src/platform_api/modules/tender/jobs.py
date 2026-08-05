"""Фоновые задачи тендерного модуля.

Предметной логики здесь нет: задача достаёт из хранилища то, что загрузили,
раскладывает во временный каталог и передаёт ядру. Ядро разбирает файлы ровно
так же, как при запуске из терминала, — и это главное требование к этому
файлу. Второй способ разбирать документы неизбежно разойдётся с первым.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select

from platform_api.db.models import StoredFile
from platform_api.jobs.contract import JobContext, JobSpec
from platform_api.logging import get_logger

logger = get_logger(__name__)


def estimate_cost(
    ctx: JobContext, *, file_ids: list[str], with_market: bool = False, **_: Any
) -> dict[str, Any]:
    """Во сколько обойдётся разбор загруженного.

    Два шага, и оба бесплатные. Сначала из файлов извлекается текст — без
    обращения к модели: сканы остаются неразобранными, но по ним уже видно,
    сколько страниц придётся распознавать. Потом ядро считает по этому цену.

    Ответ на вопрос «сколько это будет стоить» нужен до того, как деньги
    потрачены. На архиве в две тысячи файлов разница между оценкой и её
    отсутствием — это разница между решением и сюрпризом в счёте.
    """
    from tender_analyze.application.container import Container
    from tender_analyze.application.estimate import estimate_cost as core_estimate
    from tender_analyze.exceptions import TenderAnalyzeError

    from platform_api.modules.tender.core import core_settings

    rows = _files(ctx, file_ids)
    if not rows:
        return {"files": 0, "usd": 0.0, "documents": 0, "ocr_pages": 0}

    settings = core_settings()
    ctx.advance(0, total=len(rows) * 2, note="раскладываю файлы")

    with tempfile.TemporaryDirectory(prefix="tender-estimate-") as workdir:
        root = _materialize(ctx, rows, Path(workdir))

        container = Container(settings)
        try:
            # Без OCR: здесь выясняется, что за файлы, а не что в них
            # написано. Распознавание — как раз то, чью цену мы считаем.
            registry = container.extractors(with_ocr=False)
            extracted = []
            for index, file in enumerate(container.scanner().scan(root), start=1):
                ctx.advance(len(rows) + index, note=file.name)
                if not registry.supports(file):
                    continue
                try:
                    extracted.append(registry.extract(file))
                except TenderAnalyzeError as exc:
                    # Битый файл не должен останавливать оценку: он просто не
                    # попадёт в неё, а разбор о нём скажет отдельно.
                    logger.warning("Файл не читается", name=file.name, error=str(exc))

            estimate = core_estimate(
                extracted,
                cases=1,
                pricing=settings.pricing,
                llm=settings.llm,
                with_market=with_market,
            )
        finally:
            container.dispose()

    return {
        "files": len(rows),
        "documents": estimate.documents,
        "ocr_pages": estimate.ocr_pages,
        "usd": float(estimate.usd),
        "input_tokens": estimate.input_tokens,
        "output_tokens": estimate.output_tokens,
        "provider": estimate.provider,
        # Стоимость самой оценки: ноль. Она считается кодом и в модель не ходит.
        "cost_usd": 0.0,
    }


def _files(ctx: JobContext, file_ids: list[str]) -> list[StoredFile]:
    """Файлы задачи — и только своей организации.

    Идентификаторы приходят из параметров задачи, а те задавал человек.
    Проверка принадлежности здесь не дублирование: задача выполняется в другом
    процессе, где проверок обработчика запроса уже нет.
    """
    if not file_ids:
        return []
    return list(
        ctx.db.scalars(
            select(StoredFile).where(
                StoredFile.organization_id == ctx.organization_id,
                StoredFile.id.in_(file_ids),
            )
        )
    )


def _materialize(ctx: JobContext, rows: list[StoredFile], workdir: Path) -> Path:
    """Раскладывает файлы из хранилища во временный каталог.

    Ядро работает с каталогом на диске — так же, как при запуске из терминала.
    Разложить и отдать ему привычную папку дешевле, чем учить его читать из
    хранилища: это второй путь к содержимому, и он однажды разойдётся с первым.
    """
    root = workdir / "закупка"
    root.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows, start=1):
        target = root / (row.original_name or f"{row.sha256[:12]}.bin")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            for chunk in ctx.storage.read_chunks(row.sha256):
                handle.write(chunk)
        ctx.advance(index, note=target.name)
    return root


jobs = (JobSpec(kind="estimate", handler=estimate_cost, title="Оценка стоимости разбора"),)

__all__ = ["jobs"]
