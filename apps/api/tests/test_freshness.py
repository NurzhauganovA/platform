"""Пересборка по отпечатку базы.

Рабочий список skstore пересчитывался на каждое открытие: тысяча с лишним
закупов, работа процессорная, процесс API один. Тридцать человек в начале дня
вставали в очередь друг за другом.
"""

from __future__ import annotations

import threading

from platform_api.modules.freshness import ByStamp


def test_same_stamp_builds_once() -> None:
    """База не менялась — значит, и пересчитывать нечего."""
    builds = 0

    def build() -> int:
        nonlocal builds
        builds += 1
        return builds

    cached = ByStamp("demo", lambda: "one", build)

    assert cached.get() == 1
    assert cached.get() == 1
    assert builds == 1


def test_new_stamp_rebuilds() -> None:
    """Прогон отработал — список обязан показать новое."""
    stamps = iter(["one", "one", "two"])
    builds = 0

    def build() -> int:
        nonlocal builds
        builds += 1
        return builds

    cached = ByStamp("demo", lambda: next(stamps), build)

    assert cached.get() == 1
    assert cached.get() == 1
    assert cached.get() == 2


def test_unreadable_stamp_still_answers() -> None:
    """База ядра недоступна — отвечаем без экономии, а не отказом.

    Пятисотый ответ здесь означал бы пустой экран там, где данные есть.
    """

    def stamp() -> str:
        raise RuntimeError("база ядра недоступна")

    cached = ByStamp("demo", stamp, lambda: "собрано")

    assert cached.get() == "собрано"
    assert cached.get() == "собрано"


def test_rebuild_happens_once_under_load() -> None:
    """Десять одновременных открытий — одна пересборка, а не десять.

    Ради этого замок и стоит: без него утро после прогона превращается в
    десять одинаковых расчётов, занимающих единственный процессор.
    """
    builds = 0
    started = threading.Barrier(10)

    def build() -> int:
        nonlocal builds
        builds += 1
        return builds

    cached = ByStamp("demo", lambda: "one", build)

    def open_page() -> None:
        started.wait()
        cached.get()

    threads = [threading.Thread(target=open_page) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert builds == 1


def test_forget_drops_what_was_built() -> None:
    builds = 0

    def build() -> int:
        nonlocal builds
        builds += 1
        return builds

    cached = ByStamp("demo", lambda: "one", build)

    assert cached.get() == 1
    cached.forget()
    assert cached.get() == 2
