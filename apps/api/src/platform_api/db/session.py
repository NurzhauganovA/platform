"""Движок и сессии.

Синхронный SQLAlchemy, а не асинхронный, и это выбор, а не упущение. Ядро
тендерного разбора синхронное — оно читает PDF, гоняет OCR и ходит в модель
блокирующими вызовами. Асинхронная сессия в вебе поверх синхронного ядра дала
бы два разных способа работать с данными и постоянный риск позвать одно из
другого. FastAPI выполняет синхронные обработчики в пуле потоков, и на нашей
нагрузке — несколько человек в тендерном отделе — это не узкое место.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from platform_api.config import DatabaseSettings


def create_db_engine(settings: DatabaseSettings) -> Engine:
    return create_engine(
        settings.url,
        echo=settings.echo,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        # Соединение, простоявшее без дела, может быть закрыто с той стороны:
        # обрыв тогда всплывает первым запросом после затишья.
        pool_pre_ping=True,
        future=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Сессия с фиксацией по выходу и откатом при ошибке."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
