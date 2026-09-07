"""Прогоны по расписанию.

Расписания не было вовсе: выгрузку запускали кнопкой. Кнопку не нажимали три
недели, и два раздела из четырёх простояли пустыми — все строки в них успели
протухнуть.
"""

from __future__ import annotations

import pytest
from platform_api.jobs.contract import JobSpec
from platform_api.modules import discover_modules


def _handler(ctx: object, **_: object) -> dict[str, object]:
    return {}


def test_schedule_is_declared_by_modules() -> None:
    """Расписание собирается из объявлений, а не перечисляется в исполнителе.

    Вписанный в каркас список означал бы, что следующая площадка обновляется
    руками, пока кто-нибудь не вспомнит про тот файл.
    """
    from platform_api.jobs.worker import collect_schedule

    planned = collect_schedule()
    names = {job.name for job in planned}

    assert names == {"skstore:sync", "omarket:sync", "goszakup:harvest"}


def test_paid_jobs_have_no_schedule() -> None:
    """Платный шаг сам себя не запускает.

    Пересчёт ходит в модель за деньги. Задача, заводящая себя сама, однажды
    потратит бюджет за ночь, и объяснить это будет нечем.
    """
    paid = {("skstore", "analyze"), ("omarket", "analyze"), ("goszakup", "remark")}

    scheduled = {
        (module.slug, spec.kind)
        for module in discover_modules()
        for spec in module.jobs
        if spec.every_hours
    }

    assert not (scheduled & paid), f"Платное в расписании: {scheduled & paid}"


def test_runs_do_not_collide() -> None:
    """Минуты запуска разные.

    Три выгрузки, стартующие разом, дерутся за единственный процессор и
    растягивают друг друга втрое.
    """
    minutes = [
        spec.at_minute for module in discover_modules() for spec in module.jobs if spec.every_hours
    ]

    assert len(minutes) == len(set(minutes)), f"Совпали минуты: {minutes}"


@pytest.mark.parametrize(
    ("minute", "hours"),
    [(60, 1), (-1, 1), (0, 0), (0, 25)],
)
def test_broken_schedule_is_refused(minute: int, hours: int) -> None:
    """Опечатка в расписании должна выясниться при запуске, а не в три ночи."""
    if hours == 0:
        pytest.skip("Ноль часов — это «только по кнопке», а не опечатка")
    with pytest.raises(ValueError):
        JobSpec(kind="demo", handler=_handler, every_hours=hours, at_minute=minute)
