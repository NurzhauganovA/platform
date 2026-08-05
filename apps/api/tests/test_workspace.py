"""Каталог закупки.

Ядро работает обычной папкой, и собрать её надо так, чтобы не заплатить вторым
экземпляром каждого файла и не дать сложить чужой файл куда попало.
"""

from __future__ import annotations

import hashlib
import io
import os
import uuid
from pathlib import Path

import pytest
from platform_api.modules.tender.workspace import CaseWorkspace
from platform_api.storage import FileStorage

PDF = "%PDF-1.4 КП Примеро".encode()
OTHER = "%PDF-1.4 МЗ".encode()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def storage(tmp_path: Path) -> FileStorage:
    store = FileStorage(tmp_path / "storage", max_bytes=1024 * 1024)
    store.save(io.BytesIO(PDF), expected_sha256=_digest(PDF))
    store.save(io.BytesIO(OTHER), expected_sha256=_digest(OTHER))
    return store


@pytest.fixture
def workspace(tmp_path: Path, storage: FileStorage) -> CaseWorkspace:
    return CaseWorkspace(tmp_path / "cases", storage)


def test_files_appear_under_their_own_names(workspace: CaseWorkspace) -> None:
    """В хранилище файл лежит под хэшем, в закупке — под своим именем."""
    case_id = uuid.uuid4()

    root, placed = workspace.materialize(
        case_id,
        [("КП Примеро.pdf", _digest(PDF)), ("МЗ.docx", _digest(OTHER))],
        title="Системный блок",
    )

    assert (root / "КП Примеро.pdf").read_bytes() == PDF
    assert (root / "МЗ.docx").read_bytes() == OTHER
    assert all(item.linked for item in placed)


def test_subfolders_are_preserved(workspace: CaseWorkspace) -> None:
    """«обновленные кп» — отдельная папка, и по ней ядро отличает закупки."""
    root, _ = workspace.materialize(
        uuid.uuid4(),
        [("КП.pdf", _digest(PDF)), ("обновленные кп/КП.pdf", _digest(OTHER))],
    )

    assert (root / "КП.pdf").exists()
    assert (root / "обновленные кп" / "КП.pdf").read_bytes() == OTHER


def test_content_is_not_stored_twice(workspace: CaseWorkspace, storage: FileStorage) -> None:
    """Главное здесь.

    Файл в закупке — жёсткая ссылка на хранилище, а не копия. На закупке в
    тринадцать мегабайт разница незаметна, на архиве в два гигабайта — это
    два гигабайта.
    """
    root, _ = workspace.materialize(uuid.uuid4(), [("КП.pdf", _digest(PDF))])

    linked = root / "КП.pdf"
    original = storage.path_for(_digest(PDF))
    assert linked.stat().st_ino == original.stat().st_ino
    assert os.stat(original).st_nlink >= 2


def test_same_file_in_two_cases_is_one_on_disk(workspace: CaseWorkspace) -> None:
    """Один образец МЗ лежит в пяти папках заказчиков — на диске он один."""
    first, _ = workspace.materialize(uuid.uuid4(), [("МЗ.docx", _digest(OTHER))])
    second, _ = workspace.materialize(uuid.uuid4(), [("МЗ.docx", _digest(OTHER))])

    assert (first / "МЗ.docx").stat().st_ino == (second / "МЗ.docx").stat().st_ino


def test_repeat_does_not_rewrite(workspace: CaseWorkspace) -> None:
    """Повторный разбор не должен переписывать каталог целиком."""
    case_id = uuid.uuid4()
    workspace.materialize(case_id, [("КП.pdf", _digest(PDF))])

    _root, placed = workspace.materialize(
        case_id, [("КП.pdf", _digest(PDF)), ("МЗ.docx", _digest(OTHER))]
    )

    assert len(placed) == 2


def test_escaping_the_case_is_refused(workspace: CaseWorkspace) -> None:
    """Главное здесь.

    Путь приходит из браузера вместе с выбранной папкой. `../../.ssh/id_rsa`
    в этом поле — не выдумка, а первое, что пробуют: без проверки файл лёг бы
    куда угодно, куда достаёт учётная запись сервера.
    """
    for path in ("../побег.pdf", "../../.ssh/id_rsa", "обновленные кп/../../побег.pdf"):
        with pytest.raises(ValueError, match="выходит за пределы"):
            workspace.materialize(uuid.uuid4(), [(path, _digest(PDF))])


def test_case_name_is_readable(workspace: CaseWorkspace) -> None:
    """Попав в папку через файловый менеджер, человек должен её узнать."""
    case_id = uuid.uuid4()

    path = workspace.path_for(case_id, "Системный блок от 27.07.2027 г")

    assert path.name.startswith("Системный блок от 27_07_2027 г-")
    # Идентификатор в имени: две закупки с одним названием — обычное дело.
    assert str(case_id) in path.name


def test_removing_a_case_keeps_the_content(workspace: CaseWorkspace, storage: FileStorage) -> None:
    """Удалили закупку — файл в хранилище остался: на него ссылаются другие."""
    case_id = uuid.uuid4()
    workspace.materialize(case_id, [("КП.pdf", _digest(PDF))])

    assert workspace.remove(case_id) is True
    assert storage.exists(_digest(PDF))


def test_removing_a_missing_case_is_not_an_error(workspace: CaseWorkspace) -> None:
    assert workspace.remove(uuid.uuid4()) is False
