"""SQLAlchemy engine and session management.

Two engines are maintained:
- Sync engine: used by CLI commands, Celery workers, and Table ORM class methods.
- Async engine: used by FastAPI route handlers to avoid blocking the event loop.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager

import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# ---------------------------------------------------------------------------
# Sync engine (CLI / Celery workers)
# ---------------------------------------------------------------------------

_engine = None
_SessionLocal: sessionmaker | None = None

# ---------------------------------------------------------------------------
# Async engine (FastAPI route handlers)
# ---------------------------------------------------------------------------

_async_engine = None
_AsyncSessionLocal: async_sessionmaker | None = None


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all hof tables."""

    pass


def _make_async_url(database_url: str) -> str:
    """Convert a sync PostgreSQL URL to an asyncpg-compatible one."""
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    return database_url


def init_engine(database_url: str, *, pool_size: int = 10, echo: bool = False) -> None:
    """Initialize both the sync and async SQLAlchemy engines and session factories."""
    global _engine, _SessionLocal, _async_engine, _AsyncSessionLocal

    # Sync engine — used by CLI, Celery, and Table class methods
    _engine = create_engine(
        database_url,
        pool_size=pool_size,
        pool_pre_ping=True,
        echo=echo,
    )
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)

    # Async engine — used by FastAPI route handlers
    async_url = _make_async_url(database_url)
    # SQLite (used in tests) doesn't support asyncpg; fall back to sync-only
    if "sqlite" not in async_url:
        _async_engine = create_async_engine(
            async_url,
            pool_size=pool_size,
            pool_pre_ping=True,
            echo=echo,
        )
        _AsyncSessionLocal = async_sessionmaker(
            bind=_async_engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )


# ---------------------------------------------------------------------------
# Sync session helpers (CLI / Celery / Table ORM methods)
# ---------------------------------------------------------------------------


def get_engine() -> sa.Engine:
    """Get the current sync SQLAlchemy engine."""
    if _engine is None:
        raise RuntimeError("Database engine not initialized. Call init_engine() first.")
    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Provide a transactional sync session scope."""
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
    """Get the sync session factory."""
    if _SessionLocal is None:
        raise RuntimeError("Database engine not initialized. Call init_engine() first.")
    return _SessionLocal


# ---------------------------------------------------------------------------
# Async session helpers (FastAPI route handlers)
# ---------------------------------------------------------------------------


def get_async_engine():
    """Get the async engine, falling back to None when unavailable (e.g. SQLite tests)."""
    return _async_engine


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional async session scope."""
    if _AsyncSessionLocal is None:
        raise RuntimeError(
            "Async database engine not initialized. Call init_engine() with a PostgreSQL URL first."
        )
    async with _AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a per-request async session.

    Usage in route handlers:
        async def my_route(session: AsyncSession = Depends(get_db_session)):
            ...
    """
    async with get_async_session() as session:
        yield session
