"""Каталог закупки на диске.

Ядро работает обычной папкой — ровно так же, как когда тендерщик запускает
его из терминала на `~/Desktop/тендеры`. Задача этого модуля — собрать такую
папку из того, что загружено через веб, и не заплатить за это вторым
экземпляром каждого файла.

Файлы попадают в каталог жёсткими ссылками. Содержимое лежит в хранилище один
раз, по sha256; ссылка — это ещё одно имя того же куска диска, а не копия. На
закупке в тринадцать мегабайт разница незаметна, на архиве в два гигабайта —
это два гигабайта.

Каталог постоянный, а не временный. Закупку открывают через месяц, к ней
возвращаются, по ней пересобирают КП, и разбор, привязанный к исчезнувшей
папке, пришлось бы делать заново — за деньги.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from platform_api.logging import get_logger
from platform_api.storage import FileStorage

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PlacedFile:
    relative_path: str
    linked: bool
    """Файл появился ссылкой. `False` — пришлось копировать."""


class CaseWorkspace:
    """Каталоги закупок."""

    def __init__(self, root: Path, storage: FileStorage) -> None:
        self._root = root
        self._storage = storage

    def path_for(self, case_id: object, title: str = "") -> Path:
        """Каталог одной закупки.

        В имени и название, и идентификатор. Название — чтобы человек узнал
        папку, попав в неё через файловый менеджер; идентификатор — чтобы две
        закупки с одинаковым названием не оказались одной папкой, а такое
        случается: «Системный блок» приходит от разных заказчиков.
        """
        slug = _slug(title)
        name = f"{slug}-{case_id}" if slug else str(case_id)
        return self._root / name

    def materialize(
        self, case_id: object, files: Iterable[tuple[str, str]], *, title: str = ""
    ) -> tuple[Path, list[PlacedFile]]:
        """Раскладывает файлы закупки в её каталог.

        Принимает пары «путь внутри закупки — sha256». Уже разложенное не
        трогается: повторный разбор не должен переписывать каталог целиком.
        """
        root = self.path_for(case_id, title)
        root.mkdir(parents=True, exist_ok=True)

        placed: list[PlacedFile] = []
        for relative_path, sha256 in files:
            target = _safe_join(root, relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                placed.append(PlacedFile(relative_path, linked=True))
                continue
            placed.append(PlacedFile(relative_path, linked=self._link(sha256, target)))
        return root, placed

    def _link(self, sha256: str, target: Path) -> bool:
        source = self._storage.path_for(sha256)
        try:
            os.link(source, target)
            return True
        except OSError as exc:
            # Разные тома или файловая система без жёстких ссылок: копируем.
            # Медленнее и занимает место, но закупка должна собраться.
            logger.warning("Ссылка не создана, копирую", target=str(target), error=str(exc))
            shutil.copyfile(source, target)
            return False

    def remove(self, case_id: object, title: str = "") -> bool:
        """Убирает каталог закупки.

        Содержимое в хранилище остаётся: на него ссылаются другие закупки, и
        удаление здесь не должно их задеть. Ссылка исчезает — файл нет.
        """
        path = self.path_for(case_id, title)
        if not path.exists():
            return False
        shutil.rmtree(path)
        return True


def _safe_join(root: Path, relative_path: str) -> Path:
    """Собирает путь внутри каталога закупки и не даёт из него выйти.

    Путь приходит из браузера вместе с загруженной папкой. `../../.ssh/id_rsa`
    в этом поле — не выдумка, а первое, что пробуют: без проверки файл лёг бы
    куда угодно, куда достаёт учётная запись сервера.
    """
    candidate = (root / relative_path).resolve()
    base = root.resolve()
    if candidate != base and base not in candidate.parents:
        raise ValueError(f"Путь выходит за пределы закупки: {relative_path}")
    return candidate


def _slug(title: str) -> str:
    """Имя каталога из названия закупки: без разделителей и лишних пробелов."""
    cleaned = "".join(char if char.isalnum() or char in " -_" else "_" for char in title)
    return " ".join(cleaned.split())[:60].strip()


__all__ = ["CaseWorkspace", "PlacedFile"]
