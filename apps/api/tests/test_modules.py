"""Контракт подключения проектов.

Проверяется то, ради чего платформа и затевалась: новый проект добавляется
объявлением, а не правками в каркасе.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from platform_api.modules import ModuleRegistry, ModuleSpec, NavItem


def _module(slug: str = "demo", **overrides: object) -> ModuleSpec:
    defaults: dict[str, object] = {
        "slug": slug,
        "title": "Демо",
        "router": APIRouter(prefix=f"/{slug}"),
    }
    return ModuleSpec(**{**defaults, **overrides})  # type: ignore[arg-type]


def test_registry_keeps_declaration_order() -> None:
    """Порядок задаёт меню, и он не должен зависеть от словарей."""
    registry = ModuleRegistry([_module("tender"), _module("skstore")])

    assert [module.slug for module in registry.all()] == ["tender", "skstore"]


def test_duplicate_slug_is_refused() -> None:
    """Два модуля с одним префиксом молча перекрыли бы эндпоинты друг друга."""
    registry = ModuleRegistry([_module("tender")])

    with pytest.raises(ValueError, match="уже подключён"):
        registry.add(_module("tender"))


def test_unknown_module_names_the_known_ones() -> None:
    registry = ModuleRegistry([_module("tender")])

    with pytest.raises(KeyError, match="tender"):
        registry.get("тендеры")


def test_jobs_are_collected_from_all_modules() -> None:
    """Исполнитель очереди получает задачи всех модулей одним списком."""

    def analyze() -> None: ...

    def sourcing() -> None: ...

    def sync() -> None: ...

    registry = ModuleRegistry(
        [
            _module("tender", jobs=(analyze, sourcing)),
            _module("skstore", jobs=(sync,)),
        ]
    )

    assert set(registry.jobs) == {analyze, sourcing, sync}


def test_nav_item_roles_are_not_an_access_check() -> None:
    """Роли в пункте меню — про удобство, а не про доступ.

    Тест закрепляет намерение: `NavItem.roles` ничего не проверяет. Прятать
    кнопку и оставлять открытым эндпоинт — самый распространённый способ
    отдать себестоимость наружу, и полагаться на это поле нельзя.
    """
    item = NavItem(title="Закупки", path="/tender/cases", roles=("analyst",))

    assert item.roles == ("analyst",)
    assert not hasattr(item, "check")


def test_fail_sessiya_ploshchadki_ne_perekryvaet_sessiyu_platformy() -> None:
    """В обработчике две базы, и называть их одинаково нельзя.

    Модуль ходит и в базу платформы (`db: Db`), и в базу подключённого ядра
    (`core.session()`). Записанные под одним именем, вторая перекрывает
    первую — и запрос к таблице платформы уходит в базу площадки, где её нет.

    Типы этого не ловят: обе переменные сессии, подписи совпадают. Разбор
    лота так и падал пятисотой на каждом открытии, а тесты проходили — они
    зовут сборку напрямую, минуя обработчик.
    """
    import re
    from pathlib import Path

    import platform_api

    корень = Path(platform_api.__file__).parent / "modules"
    перекрыто: list[str] = []
    for файл in sorted(корень.rglob("*.py")):
        текст = файл.read_text(encoding="utf-8")
        for найдено in re.finditer(r"^def (\w+)\(([\s\S]*?)\) ->", текст, re.M):
            имя, подпись = найдено.group(1), найдено.group(2)
            if "db: Db" not in подпись:
                continue
            конец = текст.find("\ndef ", найдено.end())
            тело = текст[найдено.end() : конец if конец > 0 else len(текст)]
            if "core.session() as db" in тело:
                перекрыто.append(f"{файл.name}:{имя}")

    assert not перекрыто, (
        "Сессия площадки названа `db` там, где уже есть сессия платформы — "
        "запросы к таблицам платформы уйдут в чужую базу: " + ", ".join(перекрыто)
    )


def test_fail_menyu_sovpadaet_s_pravami() -> None:
    """Пункт меню не должен вести в отказ.

    Правило строгое в одну сторону, и это не небрежность. Показать пункт, за
    которым эндпоинт откажет, — ошибка: человек нажимает один раз, а потом
    перестаёт верить всему меню. Скрыть пункт при живом доступе — наоборот,
    рабочее решение: снабжению открыт тендерный отбор, но без сумм он пуст, и
    показывать его незачем.

    Поэтому проверяется только первое. Второе — выбор, и он записан ролями
    рядом с самим пунктом.
    """
    from platform_api.auth.dependencies import CRM, READS, REMARKS
    from platform_api.db.models import Role
    from platform_api.modules import discover_modules

    доступ: dict[str, tuple[Role, ...]] = {
        "/skstore/bargains": READS,
        "/skstore/analytics": READS,
        "/omarket/preorders": READS,
        "/omarket/analytics": READS,
        "/tender/worklist": READS,
        "/tender/works": READS,
        "/tender/analytics": READS,
        "/goszakup/lots": READS,
        "/goszakup/codes": READS,
        "/goszakup/remarks": REMARKS,
        "/work/lots": CRM,
        "/work/discussion": CRM,
        "/work/analysis": CRM,
        "/work/supply": CRM,
        "/work/legal": CRM,
        "/work/approval": CRM,
        # Журнал действий — только администратору. Он отвечает на вопрос «кто
        # это сделал», и человек, о котором спрашивают, не должен видеть, что
        # именно о нём записано.
        "/work/audit": (Role.ADMIN,),
        # Уведомления — тоже только администратору: за экраном почты всех
        # сотрудников и то, кто из них что себе отключил.
        "/work/notifications": (Role.ADMIN,),
        "/work/submit": CRM,
    }
    расхождения: list[str] = []
    for модуль in discover_modules():
        for пункт in модуль.nav:
            assert пункт.path in доступ, f"Новый пункт «{пункт.title}» не описан в тесте"
            for роль in Role:
                виден = not пункт.roles or роль.value in пункт.roles
                можно = роль in доступ[пункт.path]
                if виден and not можно:
                    расхождения.append(f"{роль.value} видит «{пункт.title}», а доступа нет")

    assert not расхождения, "Меню ведёт в отказ: " + "; ".join(расхождения)


def test_goszakup_urgency_matches_its_legend() -> None:
    """Плитка «Горит» и цвет строки считают по одному порогу.

    На экране портала слово «Горит» стоит дважды: большим числом в плитке и
    подписью к цвету строки. Плитка считала по своим трём часам, цвет — по
    суткам ядра, и рядом стояли «Горит 2» и «Горит 6». Порог теперь один и
    приходит с сервера; тест держит цвет и порог вместе.
    """
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from platform_api.modules.goszakup import core

    now = datetime.now(UTC)
    inside = SimpleNamespace(end_date=now + timedelta(hours=core.URGENT_HOURS - 1))
    outside = SimpleNamespace(end_date=now + timedelta(hours=core.URGENT_HOURS + 1))

    assert core.tone_of(inside) == "warning"
    assert core.tone_of(outside) == "good"

    burning = [item for item in core.legend() if item[0] == "warning"]
    assert burning, "Цвет горящего есть, а слова к нему нет"


def test_harvest_ne_pryachet_polnyy_proval() -> None:
    """Прогон, где упали все коды, обязан считаться неудачным.

    Такой записывался успешным с «found: 0», раздел тихо оставался вчерашним,
    и замечали это через сутки по пустому списку. Частичная неудача успехом
    остаётся: один код из тридцати не повод выбрасывать двадцать девять.
    """
    from types import SimpleNamespace
    from unittest.mock import patch

    import pytest as _pytest
    from platform_api.modules.goszakup.jobs import harvest

    ctx = SimpleNamespace(advance=lambda *args, **kwargs: None)

    def outcome(codes: int, failed: tuple[str, ...]) -> SimpleNamespace:
        return SimpleNamespace(
            codes=codes,
            found=0,
            added=0,
            updated=0,
            failed=failed,
            broken=(),
            interrupted="",
        )

    with (
        patch("platform_api.modules.goszakup.core.session"),
        patch("goszakup.application.harvest.HarvestService") as service,
    ):
        service.return_value.run.return_value = outcome(2, ("a", "b"))
        with _pytest.raises(RuntimeError, match="ни по одному коду"):
            harvest(ctx)  # type: ignore[arg-type]

        service.return_value.run.return_value = outcome(2, ("a",))
        assert harvest(ctx)["failed"] == ["a"]  # type: ignore[arg-type]


def test_loty_odnogo_obyavleniya_otmecheny() -> None:
    """Лоты, пришедшие из одного объявления, помечаются общим ключом.

    В объявлении бывает четыре лота, а берём мы их по своим кодам ЕНС ТРУ
    вразнобой — и в списке они выглядят четырьмя разными закупками. Между тем
    это одна: срок один, документы общие, заявка подаётся сразу на всё.

    Объявление с одним нашим лотом не отмечается: пометка «1 лот» ничего не
    сообщает, а строку в таблице сворачивает.
    """
    from types import SimpleNamespace

    from platform_api.modules.goszakup.router import _mark_announces
    from platform_api.modules.schemas import RowOut

    rows = [RowOut(cells=[]) for _ in range(4)]
    source = [
        SimpleNamespace(announce_id=100),
        SimpleNamespace(announce_id=100),
        SimpleNamespace(announce_id=100),
        SimpleNamespace(announce_id=200),
    ]

    _mark_announces(rows, source)

    assert [row.lot.key if row.lot else None for row in rows] == [
        "100",
        "100",
        "100",
        None,
    ]
    assert rows[0].lot is not None and rows[0].lot.positions == 3


def test_fail_klyuch_stroki_goszakupok_nomer_lota() -> None:
    """Строка госзакупок открывается номером лота, а не номером закупки.

    У объявления с четырьмя лотами номер закупки один на всех. На нём разбор
    открывал случайный лот из четырёх, устойчивые коды выдавались двумя рядами
    — в списке лот звался одним номером, в карточке другим, — а счётчики
    обсуждений искались не по тому ключу и не находили ничего.
    """
    from types import SimpleNamespace

    from platform_api.modules.goszakup import core

    lot = SimpleNamespace(lot_number="81808572-ОК3", purchase_number="17544221-1")

    assert core.row_id(lot) == "81808572-ОК3"


def test_fail_slova_gruppy_prihodyat_ot_modulya() -> None:
    """Группу называет модуль: у отбора это позиции лота, здесь лоты объявления.

    Зашитое в браузере слово подписывало бы лоты объявления как «позиций», а
    подсказка «поставить придётся все» врала бы: на лоты объявления заявка
    подаётся по каждому отдельно.
    """
    from types import SimpleNamespace

    from platform_api.modules.goszakup.router import _mark_announces
    from platform_api.modules.schemas import RowOut

    rows = [RowOut(cells=[]), RowOut(cells=[])]
    _mark_announces(rows, [SimpleNamespace(announce_id=7), SimpleNamespace(announce_id=7)])

    mark = rows[0].lot
    assert mark is not None
    assert mark.unit == ("лот", "лота", "лотов")
    assert mark.whole == "объявление"
    assert "по каждому лоту отдельно" in mark.hint


def test_fail_lot_otbora_obyazyvayet_postavit_vsyo() -> None:
    """У лота тендерного отбора подсказка своя, и она про обязательство.

    Позиция с заработком сорок процентов может лежать в лоте, который целиком
    в минусе: поставить придётся все позиции. Общая с госзакупками подсказка
    сняла бы это предупреждение с того раздела, где оно и нужно.
    """
    from platform_api.modules.schemas import RowLotOut

    default = RowLotOut(key="x", positions=2)
    assert default.unit == ("позиция", "позиции", "позиций")
    assert default.whole == "лот"


def test_fail_obryv_ne_provalivayet_progon_s_sobrannym() -> None:
    """Обход прервался посреди — прогон не красный, собранное уже в базе.

    Портал отдал 500 на пяти карточках подряд, сторож остановил обход на 260
    лоте из 400, и прогон записался неудачей. Человек, увидев красное, нажимал
    кнопку заново и платил порталу теми же пятью минутами — а двести шестьдесят
    прочитанных карточек к тому моменту уже лежали в базе.

    Ноль собранного — другое дело: тогда обход не дал ничего, и молчать об
    этом нельзя.
    """
    from types import SimpleNamespace
    from unittest.mock import patch

    from platform_api.modules.goszakup.jobs import harvest

    ctx = SimpleNamespace(advance=lambda *args, **kwargs: None)
    прервано = "Портал не отвечает: подряд не удалось 5 запросов"

    with (
        patch("platform_api.modules.goszakup.core.session"),
        patch("goszakup.application.harvest.HarvestService") as service,
    ):
        service.return_value.run.return_value = SimpleNamespace(
            codes=34,
            found=260,
            added=12,
            updated=248,
            failed=(),
            broken=("лот 60570709",),
            interrupted=прервано,
        )
        итог = harvest(ctx)  # type: ignore[arg-type]

    assert итог["added"] == 12
    assert итог["broken"] == 1
    assert итог["interrupted"] == прервано


def test_fail_progress_idyot_chislami() -> None:
    """Прогресс несёт числа, а не только текст.

    Полоса показывала ноль процентов все пять минут прогона: обход сообщал
    «карточки лотов: 260 из 400» словами, а `done` и `total` оставались нулём
    и единицей. По такой полосе не отличить работающий обход от зависшего — а
    смотрят на неё ровно за этим.
    """
    from types import SimpleNamespace
    from unittest.mock import patch

    from platform_api.modules.goszakup.jobs import harvest

    шаги: list[tuple[int, int | None, str]] = []

    def advance(done: int, *, total: int | None = None, note: str = "") -> None:
        шаги.append((done, total, note))

    ctx = SimpleNamespace(advance=advance)

    with (
        patch("platform_api.modules.goszakup.core.session"),
        patch("goszakup.application.harvest.HarvestService") as service,
    ):

        def run(_db: object, **kwargs: object) -> SimpleNamespace:
            сообщить = kwargs["on_progress"]
            assert callable(сообщить)
            сообщить("карточки лотов: 260 из 400", 260, 400)
            return SimpleNamespace(
                codes=1, found=0, added=0, updated=0, failed=(), broken=(), interrupted=""
            )

        service.return_value.run = run
        harvest(ctx)  # type: ignore[arg-type]

    assert (260, 400, "карточки лотов: 260 из 400") in шаги


def test_fail_sosedi_berutsya_iz_svoyey_bazy_kogda_portal_molchit() -> None:
    """Лоты объявления видны в карточке, даже когда портал их не отдаёт.

    Связь между лотами известна нам самим — по `announce_id`, и в списке они
    уже стоят рядом и сворачиваются в одну строку. Карточка же спрашивала
    портал, а он на объявления, выгруженные до переезда, отвечает 404: их
    внутренние номера сменились. Получалось, что в списке человек видит два
    лота, открывает карточку и не находит ни одного.
    """
    from types import SimpleNamespace
    from unittest.mock import patch

    from platform_api.modules.goszakup import detail

    наши = (
        detail._Neighbour(
            number="81754016-ОК4",
            name="Ноутбук",
            extra="",
            count=None,
            unit="штука",
            amount=None,
            status="Опубликован",
            ours=True,
        ),
        detail._Neighbour(
            number="81754292-ОК4",
            name="Компьютер",
            extra="",
            count=None,
            unit="штука",
            amount=None,
            status="Опубликован",
            ours=True,
        ),
    )

    with (
        patch.object(detail, "_from_base", return_value=наши),
        patch.object(detail, "_from_portal", return_value=((), "Портал ответил 404")),
    ):
        found, trouble = detail._announce_neighbours(SimpleNamespace(announce_id=17542735))

    assert [item.number for item in found] == ["81754016-ОК4", "81754292-ОК4"]
    # Раздел не пуст — жаловаться на портал нечего.
    assert trouble == ""


def test_fail_chuzhiye_loty_obyavleniya_otlichayutsya_ot_nashih() -> None:
    """Лот с портала, которого нет у нас, отмечен как не наш.

    Разница важна: наш лежит в рабочем списке и его можно взять в работу, а
    чужой под наши коды ЕНС ТРУ не подошёл. Одна подпись на оба случая
    оставляла бы человека гадать, почему половины строк он в списке не
    находит.
    """
    from types import SimpleNamespace
    from unittest.mock import patch

    from platform_api.modules.goszakup import detail

    наш = detail._Neighbour(
        number="A-1",
        name="Ноутбук",
        extra="",
        count=None,
        unit="",
        amount=None,
        status="",
        ours=True,
    )
    чужой = detail._Neighbour(
        number="A-2",
        name="Кресло",
        extra="",
        count=None,
        unit="",
        amount=None,
        status="",
        ours=False,
    )

    with (
        patch.object(detail, "_from_base", return_value=(наш,)),
        patch.object(detail, "_from_portal", return_value=((чужой,), "")),
    ):
        found, _ = detail._announce_neighbours(SimpleNamespace(announce_id=1))

    assert {item.number: item.ours for item in found} == {"A-1": True, "A-2": False}
    assert "под нашими кодами" not in detail._note(2, 1)
