"""Фоновые задачи тендерного модуля.

Предметной логики здесь нет: задача достаёт из хранилища то, что загрузили,
раскладывает во временный каталог и передаёт ядру. Ядро разбирает файлы ровно
так же, как при запуске из терминала, — и это главное требование к этому
файлу. Второй способ разбирать документы неизбежно разойдётся с первым.
"""

from __future__ import annotations

import tempfile
import uuid
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


def analyze_case(ctx: JobContext, *, case_id: str, force: bool = False, **_: Any) -> dict[str, Any]:
    """Разбирает закупку целиком.

    Каталог закупки собирается жёсткими ссылками на хранилище и отдаётся ядру
    как обычная папка — той же командой, что работает из терминала. Второго
    способа разбирать документы у нас нет и не будет: он разошёлся бы с первым
    ровно на той закупке, где ошибка стоит дороже всего.
    """
    from tender_analyze.application.ingest import IngestOptions, IngestService
    from tender_analyze.application.selection import Selection

    from platform_api.modules.tender.core import core_settings
    from platform_api.modules.tender.models import CaseStatus, TenderCaseRow

    case = ctx.db.get(TenderCaseRow, uuid.UUID(case_id))
    if case is None or case.organization_id != ctx.organization_id:
        raise LookupError(f"Закупки {case_id} нет")
    if not case.files:
        return {"documents": 0, "cost_usd": 0.0}

    root, _placed = ctx.workspace.materialize(
        case.id,
        [(item.relative_path, item.sha256) for item in case.files],
        title=case.title,
    )
    ctx.advance(0, total=len(case.files), note="каталог собран")

    settings = core_settings()
    from tender_analyze.application.container import Container

    container = Container(settings)
    try:
        selection = Selection(
            root=root,
            files=tuple(container.scanner().scan(root)),
            description=case.title,
        )
        service = IngestService(
            uow=container.unit_of_work(root),
            extractors=container.extractors(with_ocr=settings.pdf.ocr_enabled),
            analyzer=container.analyzer(),
        )

        done = {"count": 0}

        def progress(name: str, status_text: str) -> None:
            done["count"] += 1
            ctx.advance(done["count"], note=f"{name} — {status_text}")

        report = service.run(
            selection,
            IngestOptions(workers=settings.workers, force_analyze=force),
            progress,
        )
    except Exception:
        # Разбор не удался — закупка возвращается в «готова». Иначе она
        # навсегда остаётся «разбирается»: человек ждёт результата, которого
        # не будет, и не видит, что прогон надо повторить.
        case.status = CaseStatus.READY
        ctx.db.commit()
        raise
    finally:
        container.dispose()

    case.status = CaseStatus.ANALYZED
    ctx.db.commit()

    return {
        "files": report.files_total,
        "documents": report.documents_analyzed,
        "pages": report.pages_total,
        "ocr_pages": report.pages_ocr,
        "failed": report.files_failed,
        "input_tokens": report.input_tokens,
        "output_tokens": report.output_tokens,
    }


def decide_case(
    ctx: JobContext,
    *,
    case_id: str,
    with_market: bool = False,
    force: bool = False,
    **_: Any,
) -> dict[str, Any]:
    """Решение по закупке: участвовать ли и по какой цене.

    Отдельно от разбора документов, и это не дробление ради дробления. Разбор
    отвечает на вопрос «что написано в бумагах», решение — «что нам с этим
    делать». Первый идёт по каждому документу и на дешёвой модели, второе одно
    на закупку, но именно оно про деньги — и модель там сильнее.

    Повторный запуск по той же закупке бесплатен: состав не менялся, значит и
    вывод прежний, ядро отдаёт его из кэша.
    """
    from tender_analyze.application.case_analysis import CaseAnalysisOptions, CaseAnalysisService
    from tender_analyze.application.container import Container

    from platform_api.modules.tender.core import build_case_view, core_settings
    from platform_api.modules.tender.models import TenderCaseRow

    case = ctx.db.get(TenderCaseRow, uuid.UUID(case_id))
    if case is None or case.organization_id != ctx.organization_id:
        raise LookupError(f"Закупки {case_id} нет")

    view = build_case_view(case)
    if view is None:
        # Документы ещё не разобраны — решать не по чему. Сказать это прямо
        # честнее, чем спросить модель наугад за деньги.
        return {"decided": 0, "reason": "Закупка не разобрана", "cost_usd": 0.0}

    ctx.advance(0, total=1, note="спрашиваем модель")

    settings = core_settings()
    container = Container(settings)
    try:
        service = CaseAnalysisService(
            uow=container.unit_of_work(ctx.workspace.path_for(case.id, case.title)),
            analyzer=container.case_analyzer(),
            analysis_settings=settings.analysis,
            llm_settings=settings.llm,
        )
        analyzed, report = service.run(
            [view.case],
            CaseAnalysisOptions(with_market=with_market, force=force, workers=1),
            lambda folder, status_text: ctx.advance(1, note=f"{folder} — {status_text}"),
        )
    finally:
        container.dispose()

    decision = analyzed[0].analysis if analyzed else None
    return {
        "decided": report.analyzed,
        "cached": report.cached,
        "failed": report.failed,
        "recommendation": _plain(decision.recommendation) if decision else None,
        "recommended_bid": decision.recommended_bid if decision else None,
        "expected_margin_percent": decision.expected_margin_percent if decision else None,
    }


def _plain(value: Any) -> str | None:
    return str(getattr(value, "value", value)) if value is not None else None


jobs = (
    JobSpec(kind="estimate", handler=estimate_cost, title="Оценка стоимости разбора"),
    JobSpec(kind="analyze", handler=analyze_case, title="Разбор закупки"),
    JobSpec(kind="decide", handler=decide_case, title="Решение по закупке"),
)

__all__ = ["jobs"]
