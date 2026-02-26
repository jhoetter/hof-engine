"""SQLAlchemy engine and session management."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker, DeclarativeBase

_engine = None
_SessionLocal: sessionmaker | None = None


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all hof tables."""

    pass


def init_engine(database_url: str, *, pool_size: int = 10, echo: bool = False) -> None:
    """Initialize the SQLAlchemy engine and session factory."""
    global _engine, _SessionLocal

    _engine = create_engine(
        database_url,
        pool_size=pool_size,
        pool_pre_ping=True,
        echo=echo,
    )
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def get_engine():
    """Get the current SQLAlchemy engine."""
    if _engine is None:
        raise RuntimeError("Database engine not initialized. Call init_engine() first.")
    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Provide a transactional session scope."""
    if _SessionLocal is None:
        raise RuntimeError("Database engine not initialized. Call init_engine() first.")

    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session_factory() -> sessionmaker:
    """Get the session factory for dependency injection."""
    if _SessionLocal is None:
        raise RuntimeError("Database engine not initialized. Call init_engine() first.")
    return _SessionLocal
