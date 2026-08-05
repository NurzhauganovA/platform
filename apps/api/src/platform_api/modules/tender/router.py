"""Эндпоинты тендерного модуля."""

from __future__ import annotations

from fastapi import APIRouter

from platform_api.modules.tender import core
from platform_api.modules.tender.health import check as check_health
from platform_api.modules.tender.schemas import (
    CompanyOut,
    FileProbe,
    FileVerdict,
    FormatOut,
    ModuleHealth,
    UploadPlan,
)

router = APIRouter(prefix="/tender", tags=["Тендеры"])


@router.get("/health", summary="Готовность модуля к разбору")
def get_health() -> ModuleHealth:
    """Всё ли настроено для платного разбора.

    Спрашивается до загрузки папки: разбор идёт минутами и падает на первом же
    файле, если нет доступа к модели, — а человек к этому моменту уже ждёт.
    """
    return ModuleHealth.model_validate(check_health())


@router.get("/companies", summary="Наши компании")
def list_companies() -> list[CompanyOut]:
    """От кого можно отправить коммерческое предложение.

    Незаполненные реквизиты отдаются вместе с профилем: недостающий БИН должен
    всплыть при выборе компании, а не в готовом КП у заказчика.
    """
    directory = core.companies()
    return [
        CompanyOut(
            key=key,
            name=profile.name,
            bin=profile.bin,
            director=profile.director,
            is_default=key == directory.default,
            missing=profile.missing,
            notes=" ".join(profile.notes.split()),
        )
        for key, profile in directory.profiles.items()
    ]


@router.get("/formats", summary="Какие форматы читаются")
def list_formats() -> list[FormatOut]:
    """Состав поддерживаемых форматов — то, по чему браузер заранее видит,
    что из выбранной папки вообще пойдёт в разбор."""
    registry = core.formats()
    result: list[FormatOut] = []
    for extension in _KNOWN_EXTENSIONS:
        probe = core.describe_upload(f"probe{extension}", f"probe{extension}", 0, "0" * 64)
        result.append(
            FormatOut(
                extension=extension,
                supported=registry.supports(probe),
                is_container=registry.is_container(probe),
            )
        )
    return result


@router.post("/upload-plan", summary="Что из выбранной папки нужно загружать")
def plan_upload(files: list[FileProbe]) -> UploadPlan:
    """Считает план загрузки до её начала.

    Браузер присылает имена, размеры и хэши — сами файлы остаются на машине.
    В ответ приходит, что грузить: неподдерживаемые форматы отсеиваются, а
    файлы с уже известным содержимым не передаются вовсе. За их разбор
    заплачено в прошлый раз, и повторять это ни в трафике, ни в токенах
    смысла нет.
    """
    registry = core.formats()
    known = core.known_hashes([item.sha256 for item in files])

    verdicts: list[FileVerdict] = []
    upload_bytes = 0
    for item in files:
        probe = core.describe_upload(item.name, item.relative_path, item.size_bytes, item.sha256)
        supported = registry.supports(probe) or registry.is_container(probe)
        if not supported:
            verdicts.append(
                FileVerdict(
                    relative_path=item.relative_path,
                    supported=False,
                    reason=f"формат {item.extension or 'без расширения'} пока не читается",
                )
            )
            continue
        if item.sha256 in known:
            verdicts.append(
                FileVerdict(
                    relative_path=item.relative_path,
                    supported=True,
                    known=True,
                    reason="уже разобран — загрузка не нужна",
                )
            )
            continue
        upload_bytes += item.size_bytes
        verdicts.append(FileVerdict(relative_path=item.relative_path, supported=True))

    return UploadPlan(
        files=tuple(verdicts),
        total=len(files),
        to_upload=sum(1 for item in verdicts if item.supported and not item.known),
        upload_bytes=upload_bytes,
        skipped_known=sum(1 for item in verdicts if item.known),
        skipped_unsupported=sum(1 for item in verdicts if not item.supported),
    )


_KNOWN_EXTENSIONS = (
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".txt",
    ".rtf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".zip",
    ".rar",
    ".7z",
    ".msg",
    ".eml",
)
"""Расширения, о которых спрашивают чаще всего.

Список для показа, а не для решения: читается ли файл, определяет реестр
извлекателей ядра, и он же отвечает на `/upload-plan`. Здесь — только то, что
интерфейс показывает человеку до выбора папки."""
