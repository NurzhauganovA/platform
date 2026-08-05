"""Пароли.

Argon2id — не «модный выбор», а требование к задаче: за формой входа лежат
коммерческие данные тендерного отдела и ключи к платным моделям. Argon2id
устойчив к перебору на видеокартах, чего нельзя сказать ни о SHA, ни о
быстрых KDF без параметра памяти.

Хэши перепроверяются при каждом входе: параметры со временем ужесточаются, и
старый хэш нужно молча пересчитать, а не оставлять слабым навсегда.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Параметры по рекомендации OWASP: 64 МБ памяти, три прохода. Проверка занимает
# порядка сотни миллисекунд — незаметно человеку и дорого перебору.
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)

MIN_PASSWORD_LENGTH = 12
"""Нижняя граница длины.

Двенадцать, а не восемь: восьмизначный пароль перебирается по словарю быстрее,
чем человек успевает заметить попытку."""


class WeakPasswordError(ValueError):
    """Пароль не проходит по требованиям."""


def hash_password(password: str) -> str:
    validate_password(password)
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Проверяет пароль. На неверном не бросает — возвращает `False`.

    Битый хэш в базе трактуется как несовпадение: это состояние, из которого
    нельзя пускать внутрь, но и падать пятисоткой на форме входа незачем.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    except (UnicodeEncodeError, ValueError, TypeError):
        # Хэш из базы уходит в си-библиотеку и обязан быть ASCII. Испорченная
        # запись — например, с кириллицей — роняла бы форму входа пятисоткой,
        # хотя ответ здесь очевиден: не пускать.
        return False


def needs_rehash(password_hash: str) -> bool:
    """Пора ли пересчитать хэш под текущие параметры."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def validate_password(password: str) -> None:
    """Требования к паролю.

    Намеренно скромные и об одном: длина. Правила вида «заглавная, цифра и
    спецсимвол» дают предсказуемые пароли («Пароль123!») и ничего не
    добавляют к стойкости, зато гарантированно приводят к записке под
    клавиатурой.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Пароль короче {MIN_PASSWORD_LENGTH} символов — такой подбирается по словарю"
        )
    if password.strip() != password:
        raise WeakPasswordError("Пароль начинается или заканчивается пробелом — это опечатка")


__all__ = [
    "MIN_PASSWORD_LENGTH",
    "WeakPasswordError",
    "hash_password",
    "needs_rehash",
    "validate_password",
    "verify_password",
]
