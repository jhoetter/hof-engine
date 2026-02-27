"""Tests for hof.db.engine."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

import hof.db.engine as engine_module
from hof.db.engine import Base, get_engine, get_session, get_session_factory, init_engine


@pytest.fixture(autouse=True)
def reset_engine(monkeypatch):
    """Reset the global engine state before and after each test."""
    monkeypatch.setattr(engine_module, "_engine", None)
    monkeypatch.setattr(engine_module, "_SessionLocal", None)
    yield
    monkeypatch.setattr(engine_module, "_engine", None)
    monkeypatch.setattr(engine_module, "_SessionLocal", None)


class TestInitEngine:
    def test_init_creates_engine(self):
        init_engine("sqlite:///:memory:", pool_size=1)
        assert engine_module._engine is not None
        assert engine_module._SessionLocal is not None

    def test_init_with_echo(self):
        init_engine("sqlite:///:memory:", pool_size=1, echo=True)
        assert engine_module._engine.echo is True

    def test_init_without_echo(self):
        init_engine("sqlite:///:memory:", pool_size=1, echo=False)
        assert engine_module._engine.echo is False


class TestGetEngine:
    def test_raises_when_not_initialized(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            get_engine()

    def test_returns_engine_after_init(self):
        init_engine("sqlite:///:memory:", pool_size=1)
        engine = get_engine()
        assert engine is not None


class TestGetSession:
    def test_raises_when_not_initialized(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            with get_session():
                pass

    def test_provides_session_after_init(self):
        init_engine("sqlite:///:memory:", pool_size=1)
        with get_session() as session:
            assert session is not None

    def test_commits_on_success(self):
        init_engine("sqlite:///:memory:", pool_size=1)
        Base.metadata.create_all(engine_module._engine)

        # Create a simple in-memory table for testing
        with get_session() as session:
            session.execute(sa.text("CREATE TABLE IF NOT EXISTS _test_tbl (id INTEGER PRIMARY KEY)"))

        with get_session() as session:
            session.execute(sa.text("INSERT INTO _test_tbl VALUES (1)"))

        with get_session() as session:
            result = session.execute(sa.text("SELECT COUNT(*) FROM _test_tbl")).scalar()
            assert result == 1

    def test_rolls_back_on_exception(self):
        init_engine("sqlite:///:memory:", pool_size=1)

        with get_session() as session:
            session.execute(sa.text("CREATE TABLE IF NOT EXISTS _rollback_tbl (id INTEGER PRIMARY KEY)"))

        with pytest.raises(Exception):
            with get_session() as session:
                session.execute(sa.text("INSERT INTO _rollback_tbl VALUES (1)"))
                raise RuntimeError("intentional rollback")

        with get_session() as session:
            result = session.execute(sa.text("SELECT COUNT(*) FROM _rollback_tbl")).scalar()
            assert result == 0


class TestGetSessionFactory:
    def test_raises_when_not_initialized(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            get_session_factory()

    def test_returns_factory_after_init(self):
        init_engine("sqlite:///:memory:", pool_size=1)
        factory = get_session_factory()
        assert factory is not None


class TestBase:
    def test_base_is_declarative_base(self):
        from sqlalchemy.orm import DeclarativeBase
        assert issubclass(Base, DeclarativeBase)
