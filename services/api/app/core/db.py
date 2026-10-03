"""Lazy synchronous PostgreSQL connections; command services own commits."""

from collections.abc import Iterator
from threading import Lock

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


_engine: Engine | None = None
_factory: sessionmaker | None = None
_lock = Lock()


def get_engine() -> Engine:
    global _engine, _factory
    with _lock:
        if _engine is None:
            if settings.database_url is None:
                raise RuntimeError("DATABASE_URL is required for database operations")
            _engine = create_engine(
                settings.database_url.get_secret_value(), pool_pre_ping=True
            )
            _factory = sessionmaker(_engine, autoflush=False, expire_on_commit=False)
        return _engine


def dispose_engine() -> None:
    global _engine, _factory
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = _factory = None


def get_db() -> Iterator[Session]:
    get_engine()
    session = _factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
