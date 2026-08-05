"""Формы ответов тендерного модуля.

Отдельно от доменных моделей ядра, и это не дублирование ради слоя. Модели
ядра меняются вместе с разбором, а по этим схемам генерируется клиент для
фронтенда: если отдавать домен напрямую, любая внутренняя правка молча ломает
интерфейс. И ровно здесь решается, что наружу не уходит — себестоимость и
маржа не должны утечь в ответ, который увидит закупщик или заказчик.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CompanyOut(BaseModel):
    """Наша компания — то, от чьего имени уходит предложение."""

    key: str
    name: str
    bin: str = ""
    director: str = ""
    is_default: bool = False

    missing: tuple[str, ...] = ()
    """Незаполненные реквизиты. Отдаются намеренно: недостающий БИН должен
    всплыть при выборе компании, а не в КП у заказчика."""

    notes: str = ""
    """Что требует уточнения. Внутренняя пометка, в документ не попадает."""


class FormatOut(BaseModel):
    """Что платформа умеет прочитать."""

    extension: str
    supported: bool
    is_container: bool = False
    """Архивы и письма: сам файл ничего не значит, разбирается содержимое."""


class FileProbe(BaseModel):
    """Файл, который браузер собирается загрузить.

    Сам файл остаётся на машине: сюда приходят только имя, размер и хэш,
    посчитанный браузером. Хэш — то, по чему выясняется, разбирали ли мы уже
    такое содержимое.
    """

    name: str
    relative_path: str = Field(description="Путь внутри выбранной папки")
    size_bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")

    @property
    def extension(self) -> str:
        _, _, suffix = self.name.rpartition(".")
        return f".{suffix.lower()}" if suffix and suffix != self.name else ""


class FileVerdict(BaseModel):
    """Что платформа сделает с этим файлом."""

    relative_path: str
    supported: bool
    known: bool = False
    """Файл с таким содержимым уже разбирали. Загружать его повторно не нужно,
    и платить за разбор — тем более."""

    reason: str = ""


class UploadPlan(BaseModel):
    """Ответ на вопрос браузера «что из этого грузить».

    Считается до загрузки: в архиве два гигабайта, и передавать заново то, что
    уже разобрано и оплачено, незачем.
    """

    files: tuple[FileVerdict, ...]
    total: int
    to_upload: int
    upload_bytes: int
    skipped_known: int
    skipped_unsupported: int


class ModuleHealth(BaseModel):
    """Готовность модуля к работе."""

    ok: bool
    core_version: str
    provider: str
    model_access: bool
    companies_configured: int
    problems: tuple[str, ...] = ()
