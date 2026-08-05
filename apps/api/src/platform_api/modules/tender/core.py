"""Единственная точка, где платформа обращается к тендерному ядру.

Всё остальное в модуле ходит через неё. Смысл в том, чтобы связь с чужим
пакетом была видна целиком в одном файле: когда ядро изменит имя класса или
сигнатуру, это выяснится здесь, а не россыпью по обработчикам запросов.

Ядро настраивается своим `.env` с префиксом `TENDER__` и своими ключами — оно
самостоятельный проект, а не часть платформы. Платформа его настройки не
подменяет и не пересказывает.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tender_analyze.config import CompanyDirectory, Settings
    from tender_analyze.domain.models import SourceFile
    from tender_analyze.infrastructure.extract.registry import ExtractorRegistry


@lru_cache(maxsize=1)
def core_settings() -> Settings:
    """Настройки тендерного ядра."""
    from tender_analyze.config import get_settings

    return get_settings()


def companies() -> CompanyDirectory:
    """Реквизиты наших компаний для коммерческих предложений."""
    return core_settings().companies


@lru_cache(maxsize=1)
def formats() -> ExtractorRegistry:
    """Реестр извлекателей — чем определяется, читаем ли формат.

    Без OCR: здесь отвечают на вопрос «умеем ли мы этот формат в принципе», и
    доступ к модели для этого не нужен. Заодно вопрос остаётся бесплатным —
    его задаёт браузер перед каждой загрузкой папки.
    """
    from tender_analyze.application.container import Container

    container = Container(core_settings())
    try:
        return container.extractors(with_ocr=False)
    finally:
        container.dispose()


def describe_upload(name: str, relative_path: str, size_bytes: int, sha256: str) -> SourceFile:
    """Строит описание файла, который лежит не на диске, а в запросе.

    Обход каталога такие описания собирает сам, но здесь каталога нет: есть
    имя, размер и хэш, посчитанный браузером. Путь остаётся относительным —
    абсолютного у загруженного файла попросту не существует, и подставлять
    вместо него что-то правдоподобное нельзя: по нему потом никто ничего
    не найдёт.
    """
    from datetime import UTC, datetime
    from pathlib import Path, PurePosixPath

    from tender_analyze.domain.models import SourceFile
    from tender_analyze.infrastructure.fs.scanner import categorize

    relative = PurePosixPath(relative_path)
    extension = Path(name).suffix.lower()
    return SourceFile(
        path=Path(relative_path),
        relative_path=Path(relative),
        name=name,
        extension=extension,
        category=categorize(extension),
        size_bytes=size_bytes,
        modified_at=datetime.now(UTC),
        sha256=sha256,
    )


def known_hashes(hashes: Sequence[str]) -> set[str]:
    """Какие из этих файлов уже разбирались.

    Кэш ядра ключуется по содержимому, поэтому известный файл не нужно ни
    загружать, ни разбирать заново: за его разбор уже заплачено. На повторной
    закупке это разница между «передать тринадцать мегабайт» и «не передать
    ничего».
    """
    if not hashes:
        return set()

    from tender_analyze.application.container import Container

    container = Container(core_settings())
    try:
        with container.unit_of_work() as uow:
            return {
                digest
                for digest in dict.fromkeys(hashes)
                if uow.documents.get_extraction(digest) is not None
            }
    finally:
        container.dispose()


@dataclass(frozen=True, slots=True)
class CaseView:
    """Закупка, собранная ядром из разобранных документов."""

    case: Any
    vat_rate: Decimal
    total_min: Decimal | None
    total_max: Decimal | None
    root: Path
    """Каталог закупки. По нему находятся сохранённые находки и решения:
    ядро ключует их корнем разбора."""


def build_case_view(case_row: Any) -> CaseView | None:
    """Собирает закупку по её каталогу — тем же кодом, что и CLI.

    Ничего не считает сама: сведение цен по позициям, приведение к базе без
    НДС и разброс живут в ядре. Второй способ сравнивать предложения разошёлся
    бы с первым ровно на той закупке, где ошибка стоит дороже всего.

    Возвращает `None`, если закупку ещё не разбирали: пустая сводка честнее
    выдуманной.
    """
    from tender_analyze.application.case_analysis import case_fingerprint
    from tender_analyze.application.cases import CaseBuilder
    from tender_analyze.application.container import Container

    settings = core_settings()
    root = _case_root(case_row)
    if root is None or not root.exists():
        return None

    container = Container(settings)
    try:
        with container.unit_of_work(root) as uow:
            documents = [
                item for item in uow.documents.list_analyzed(root) if item.insight is not None
            ]
            if not documents:
                return None

            cases = CaseBuilder(settings.analysis).build(documents)
            if not cases:
                return None
            case = max(cases, key=lambda item: len(item.documents))

            # Сохранённое решение подставляется сюда же: отчёт должен
            # показывать рекомендации, за которые уже заплачено.
            model = getattr(container.case_analyzer(), "model_name", "")
            stored = uow.cases.get_case_analysis(case.folder, model, case_fingerprint(case))
            if stored is not None:
                from tender_analyze.domain.models import CaseAnalysis

                payload, notes = stored
                case = case.model_copy(update={"analysis": CaseAnalysis.model_validate(payload)})
                del notes
    finally:
        container.dispose()

    vat = settings.analysis.vat_rate
    totals = [offer.total for offer in case.offers if offer.total is not None]
    return CaseView(
        case=case,
        vat_rate=vat,
        total_min=min(totals) if totals else None,
        total_max=max(totals) if totals else None,
        root=root,
    )


def _case_root(case_row: Any) -> Path | None:
    """Каталог закупки на диске."""
    from platform_api.config import get_settings
    from platform_api.modules.tender.workspace import CaseWorkspace
    from platform_api.storage import FileStorage

    settings = get_settings()
    storage = FileStorage(settings.storage.root, int(settings.storage.max_upload_mb * 1024 * 1024))
    workspace = CaseWorkspace(settings.storage.cases_root, storage)
    return workspace.path_for(case_row.id, case_row.title)


def core_version() -> str:
    """Версия подключённого ядра — чтобы в сводке было видно, что именно
    работает под платформой."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("tender-analyze")
    except PackageNotFoundError:  # pragma: no cover — пакет всегда установлен
        return "неизвестна"


__all__ = [
    "CaseView",
    "build_case_view",
    "companies",
    "core_settings",
    "core_version",
    "describe_upload",
    "formats",
    "known_hashes",
]
