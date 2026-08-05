"""Формы ответов тендерного модуля.

Отдельно от доменных моделей ядра, и это не дублирование ради слоя. Модели
ядра меняются вместе с разбором, а по этим схемам генерируется клиент для
фронтенда: если отдавать домен напрямую, любая внутренняя правка молча ломает
интерфейс. И ровно здесь решается, что наружу не уходит — себестоимость и
маржа не должны утечь в ответ, который увидит закупщик или заказчик.
"""

from __future__ import annotations

import uuid

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
    """Файл с таким содержимым уже загружен **этой организацией**.

    Проверка идёт по своим файлам, а не по всем: иначе достаточно заявить
    чужой хэш, получить в ответ «загружать не нужно» — и чужой документ
    оказался бы прикреплён к своей закупке."""

    analysis_cached: bool = False
    """Разбор такого содержимого уже оплачен. Загрузить файл всё равно надо,
    но денег он не будет стоить — это видно в оценке до запуска."""

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

    already_analyzed: int = 0
    """Сколько из загружаемых файлов не потребуют платного разбора."""


class UploadedFileOut(BaseModel):
    """Принятый файл."""

    id: uuid.UUID
    sha256: str
    size_bytes: int
    relative_path: str

    deduplicated: bool = False
    """Содержимое уже лежало в хранилище — на диске оно осталось одно."""


class EstimateIn(BaseModel):
    """Что оценивать."""

    file_ids: list[uuid.UUID] = Field(min_length=1)
    with_market: bool = False
    """Считать ли вместе с поиском на рынках: он оплачивается отдельно от
    токенов и заметно меняет итог."""


class StartedJobOut(BaseModel):
    """Задача принята в работу."""

    job_id: uuid.UUID


class ModuleHealth(BaseModel):
    """Готовность модуля к работе."""

    ok: bool
    core_version: str
    provider: str
    model_access: bool
    companies_configured: int
    problems: tuple[str, ...] = ()
