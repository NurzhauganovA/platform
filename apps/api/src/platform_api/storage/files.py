"""Хранилище загруженных файлов.

Раскладка по sha256 содержимого, как и кэш разбора в тендерном ядре: один и
тот же документ в трёх закупках лежит на диске один раз. В тендерных папках
это не редкость, а норма — один образец МЗ встречается в пяти папках разных
заказчиков.

Хэш пересчитывается при сохранении и сверяется с заявленным. Клиент считает
его сам, чтобы не грузить лишнего, но верить этому значению нельзя: тот, кто
подменит содержимое под чужой хэш, положит свой файл на место чужого — и
дальше его получит любой, кто этот файл запросит.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from platform_api.logging import get_logger

logger = get_logger(__name__)

_CHUNK = 1024 * 1024


class ChecksumMismatchError(ValueError):
    """Содержимое не соответствует заявленному хэшу."""


class FileTooLargeError(ValueError):
    """Файл крупнее разрешённого."""


@dataclass(frozen=True, slots=True)
class SavedFile:
    sha256: str
    size_bytes: int
    path: Path
    already_existed: bool
    """Файл с таким содержимым уже лежал в хранилище."""


class FileStorage:
    """Файлы на диске, разложенные по хэшу содержимого."""

    def __init__(self, root: Path, max_bytes: int) -> None:
        self._root = root
        self._max_bytes = max_bytes

    def path_for(self, sha256: str) -> Path:
        """Два уровня подкаталогов по первым символам хэша.

        Без них в одном каталоге оказались бы десятки тысяч файлов: обход
        такого каталога тормозит любую файловую систему, а `ls` в нём
        перестаёт быть выполнимой операцией.
        """
        digest = sha256.lower()
        return self._root / digest[:2] / digest[2:4] / digest

    def exists(self, sha256: str) -> bool:
        return self.path_for(sha256).exists()

    def save(self, stream: BinaryIO, *, expected_sha256: str) -> SavedFile:
        """Сохраняет поток, проверяя хэш и размер по ходу.

        Пишется во временный файл: прерванная загрузка не должна оставить в
        хранилище обрезанный файл под именем настоящего хэша — такой файл
        потом невозможно отличить от целого.
        """
        expected = expected_sha256.lower()
        digest = hashlib.sha256()
        size = 0

        self._root.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(dir=self._root, delete=False, suffix=".part")
        temporary = Path(handle.name)
        try:
            with handle:
                while chunk := stream.read(_CHUNK):
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise FileTooLargeError(
                            f"Файл больше {self._max_bytes // 1024 // 1024} МБ"
                        )
                    digest.update(chunk)
                    handle.write(chunk)

            actual = digest.hexdigest()
            if actual != expected:
                raise ChecksumMismatchError(
                    "Содержимое не совпадает с заявленным хэшем"
                )

            target = self.path_for(actual)
            if target.exists():
                return SavedFile(actual, size, target, already_existed=True)

            target.parent.mkdir(parents=True, exist_ok=True)
            # Перемещение в пределах одного тома атомарно: файл появляется
            # под своим именем уже целиком.
            shutil.move(str(temporary), str(target))
            temporary = target
            return SavedFile(actual, size, target, already_existed=False)
        finally:
            if temporary.exists() and temporary.suffix == ".part":
                temporary.unlink(missing_ok=True)

    def open(self, sha256: str) -> BinaryIO:
        path = self.path_for(sha256)
        if not path.exists():
            raise FileNotFoundError(f"Файла {sha256[:12]}… нет в хранилище")
        return path.open("rb")

    def read_chunks(self, sha256: str) -> Iterator[bytes]:
        with self.open(sha256) as handle:
            while chunk := handle.read(_CHUNK):
                yield chunk

    def delete(self, sha256: str) -> bool:
        """Убирает файл с диска.

        Вызывать можно только убедившись, что на это содержимое не ссылается
        ни одна другая запись: хранилище общее, и файл, удалённый по одной
        закупке, пропал бы сразу во всех.
        """
        path = self.path_for(sha256)
        if not path.exists():
            return False
        path.unlink()
        return True


def compute_sha256(stream: BinaryIO) -> tuple[str, int]:
    """Хэш и размер потока."""
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(_CHUNK):
        size += len(chunk)
        digest.update(chunk)
    return digest.hexdigest(), size


def temporary_name() -> str:
    return uuid.uuid4().hex


__all__ = [
    "ChecksumMismatchError",
    "FileStorage",
    "FileTooLargeError",
    "SavedFile",
    "compute_sha256",
]
