"""Написание замечания: стиль, основания и отказ модели."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from platform_api.modules import writing
from platform_api.modules.goszakup import grounds


def _закупка(**замены: object) -> writing.Subject:
    поля: dict[str, object] = {
        "code": "GZ000001",
        "purchase_number": "15785315-1",
        "title": "Компьютер (моноблок)",
        "customer": 'ГУ "Управление по государственным закупкам"',
        "amount": Decimal("8660625"),
        "count": Decimal("10"),
        "unit": "штук",
        "enstru_code": "262013.000.000011",
        "enstru_name": "Компьютер",
        "lot_number": "81468165-ЗЦП1",
        "spec_text": "Моноблок HP, архитектура Meteor Lake",
    }
    поля.update(замены)
    return writing.Subject(**поля)  # type: ignore[arg-type]


def test_fail_zapreshchyonnye_znaki_ubirayutsya_kodom() -> None:
    """Тире, двоеточия, значки списков и отступы не доходят до заказчика.

    Просьба «пиши без тире» выполняется моделью через раз, а замечание уходит
    официальным обращением: список с дефисами читается в нём как черновик.
    """
    итог = writing.shape(
        "**Замечание**\n\n"
        "1. Заказчиком указан бренд: Моноблок HP.\n"
        "   - Архитектура Meteor Lake принадлежит Intel.\n"
        "   * Требование ограничивает конкуренцию — других вариантов нет.\n\n"
        "Это нарушает пункт 412 Правил осуществления государственных закупок. "
        "Просим внести изменения в техническую спецификацию либо отменить закупку."
    )
    assert итог.text
    for знак in ("—", "–", ":", "**", "•"):
        assert знак not in итог.text, f"в тексте остался {знак}"
    for строка in итог.text.split("\n"):
        assert строка == строка.lstrip(), "остался отступ в начале строки"
        assert not строка.startswith(("-", "*", "1.", "2.")), "остался значок списка"


def test_fail_defis_vnutri_slova_ostayotsya() -> None:
    """Вычищать дефис из слов значит портить слова ради вида.

    «Из-за» и «Санкт-Петербург» пишутся через дефис, и замечание с «изза»
    выглядит написанным наспех — ровно то впечатление, которого избегаем.
    """
    итог = writing.shape(
        "Заказчик ограничил конкуренцию из-за указания бренда. "
        "Это нарушает пункт 412 Правил осуществления государственных закупок "
        "и лишает поставщиков возможности предложить равноценный товар. "
        "Просим внести изменения в техническую спецификацию."
    )
    assert "из-за" in итог.text


def test_fail_osnovaniya_uznayutsya_po_slovam_a_ne_po_nomeram() -> None:
    """Номер пункта не годится в признак: они повторяются.

    «Пункт 3 статьи 6» стоит и у программного обеспечения, и у сборного лота,
    а «412» встречается внутри кода ЕНС ТРУ. По числам применёнными
    отмечались все шесть оснований разом, и список переставал что-либо
    значить.
    """
    итог = writing.shape(
        "Заказчик установил срок поставки 15 календарных дней. "
        "Для закупок с изъятием из национального режима он не может быть меньше "
        "60 календарных дней согласно пункту 569 Правил. "
        "Просим внести изменения в техническую спецификацию либо отменить закупку."
    )
    assert итог.grounds == ("delivery",)


def test_fail_otkaz_modeli_ne_pustoy_tekst() -> None:
    """«Нарушений нет» это решение, а не поломка.

    Пустое поле в интерфейсе выглядит недоделкой платформы, и менеджер идёт
    выяснять, почему не сработало. Причина должна быть написана словами.
    """
    отказ = writing.shape("НЕТ")
    assert отказ.text == ""
    assert "не нашла" in отказ.trouble

    пустое = writing.shape("Замечаний нет.")
    assert пустое.text == ""
    assert пустое.trouble


def test_fail_dlinnoe_obrezaetsya_po_granitse_abzatsa() -> None:
    """Обрыв на полуслове ссылки на норму хуже отсутствующей ссылки.

    Заказчик отвечает, что такого пункта нет, и замечание закрыто по форме.
    """
    абзац = "Заказчик указал конкретный бренд в нарушение пункта 412 Правил. " * 12
    длинное = "\n\n".join([абзац] * 20)
    итог = writing.shape(длинное)
    assert len(итог.text) <= writing.MAX_LENGTH
    assert итог.text.endswith("Правил.")


def test_fail_porog_privoditsya_tolko_kogda_izvesten() -> None:
    """Порог тысячекратного МРП меняется законом о бюджете каждый год.

    Посчитанный «на память» он расходится с настоящим ровно тогда, когда на
    нём держится весь довод о бренде, и замечание отклоняют по существу.
    """
    подсказка = writing.prompt(_закупка(), today=date(2025, 6, 1))
    assert "3 932 000" in подсказка

    неизвестный = writing.prompt(_закупка(), today=date(2031, 6, 1))
    assert "тысячекратный" not in неизвестный

    дешёвая = writing.prompt(_закупка(amount=Decimal("500000")), today=date(2025, 6, 1))
    assert "тысячекратный" not in дешёвая


def test_fail_v_podskazku_ne_popadayut_pustye_svedeniya() -> None:
    """«Заказчик .» модель принимает за настоящее имя и переписывает в текст."""
    подсказка = writing.prompt(_закупка(customer="", lot_number=""), today=date(2026, 1, 1))
    assert "Заказчик ." not in подсказка
    assert "Лот ." not in подсказка


def test_fail_model_ne_sochinyaet_normy() -> None:
    """Все ссылки, которые модель вправе привести, перечислены в подсказке.

    Выдуманный «пункт 415 Правил» выглядит убедительно, и ошибку видит только
    заказчик, который на этом основании замечание и отклонит.
    """
    подсказка = writing.prompt(_закупка(), today=date(2026, 1, 1))
    assert "Другие пункты и статьи не приводи" in подсказка
    for ground in grounds.GROUNDS:
        assert ground.law in подсказка


def test_fail_spetsifikatsiya_popadaet_v_podskazku_tselikom() -> None:
    """Требования под одного поставщика лежат в файле, а не в названии лота."""
    подсказка = writing.prompt(
        _закупка(spec_text="Гнездо процессора Socket 1151"), today=date(2026, 1, 1)
    )
    assert "Socket 1151" in подсказка


def test_fail_nezapolnennyy_klyuch_obyasnyaetsya_po_russki() -> None:
    """Длинная английская фраза SDK выглядит поломкой платформы.

    Чинится она одной строкой в `.env`, и чинит её администратор, а не тот,
    кто нажал кнопку. Значит, сказать надо именно это.
    """
    from platform_api.modules.writer import _spoken

    беда = _spoken(
        RuntimeError(
            "Missing key inputs argument! To use the Google AI API, provide "
            "an api_key argument or set GOOGLE_API_KEY."
        )
    )
    assert "GEMINI_API_KEY" in беда
    assert "Missing key" not in беда


def test_fail_zanyataya_model_i_konchivshiysya_klyuch_eto_raznoe() -> None:
    """Занятость лечится повтором, кончившийся ключ — правкой `.env`.

    Одинаковое сообщение на оба случая заставляет менеджера нажимать кнопку
    до вечера там, где чинить должен администратор.
    """
    from platform_api.modules.writer import _spoken, _worth_retrying

    занята = RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded for this model")
    assert "квота" in _spoken(занята).lower() or "занята" in _spoken(занята).lower()
    # Запасной моделью пробовать стоит: квота считается по модели.
    assert _worth_retrying(занята)

    без_ключа = RuntimeError("Missing key inputs argument! Provide an api_key argument.")
    assert "GEMINI_API_KEY" in _spoken(без_ключа)
    # А здесь перебор моделей — это втрое больше времени на тот же отказ.
    assert not _worth_retrying(без_ключа)


def test_fail_v_kartochke_stoit_ta_model_chto_otvetila() -> None:
    """У основной модели кончается квота посреди дня, и дописывает запасная.

    Если в карточке останется та, что в настройках, разбор отказа через
    полгода пойдёт по ложному следу: искать будут в ответах модели, которая
    это замечание не писала.
    """
    from platform_api.config import Settings
    from platform_api.modules import writer

    настройки = Settings(environment="dev")
    звонки: list[str] = []

    def занята_первая(prompt: str, model: str, _: Settings, **__: object) -> tuple[str, bool]:
        """Подмена похода к модели. Ответ парой: текст и признак обрыва по
        объёму — обрезанный ответ приходит непустым, и по одному тексту его не
        отличить."""
        звонки.append(model)
        if model == настройки.writer.model:
            raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")
        return (
            "Заказчик указал конкретный бренд в нарушение пункта 412 Правил "
            "осуществления государственных закупок. Требование ограничивает круг "
            "участников и не даёт предложить равноценное оборудование. "
            "Просим внести изменения в техническую спецификацию либо отменить закупку."
        ), False

    писатель = writer.__dict__
    прежний = писатель["_ask"]
    писатель["_ask"] = занята_первая
    try:
        итог = writer.write(_закупка(), настройки, today=date(2026, 1, 1))
    finally:
        писатель["_ask"] = прежний

    assert звонки == [настройки.writer.model, настройки.writer.model_backups[0]]
    assert итог.model == настройки.writer.model_backups[0]
    assert итог.text
