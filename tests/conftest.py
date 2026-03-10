"""Shared pytest fixtures for hof-engine tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from hof.core.registry import registry
from hof.db.engine import Base
from hof.flows.flow import Flow
from hof.flows.state import ExecutionStatus, FlowExecution

# ---------------------------------------------------------------------------
# Registry isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear the global registry before each test to prevent state leakage."""
    registry.clear()
    yield
    registry.clear()


# ---------------------------------------------------------------------------
# Temporary project directory
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal project directory structure for discovery tests."""
    for d in ("tables", "functions", "flows", "cron"):
        (tmp_path / d).mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# In-memory SQLite engine (avoids PostgreSQL dependency)
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_engine():
    """Create an in-memory SQLite engine with all hof tables."""
    import hof.flows.models  # noqa: F401 — register ORM models

    engine = sa.create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def sqlite_session(sqlite_engine):
    """Provide a transactional SQLite session that rolls back after each test."""
    session_factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    session = session_factory()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def mock_db(sqlite_engine, monkeypatch):
    """Patch hof.db.engine to use the in-memory SQLite engine."""
    import hof.db.engine as engine_module

    session_factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)

    monkeypatch.setattr(engine_module, "_engine", sqlite_engine)
    monkeypatch.setattr(engine_module, "_SessionLocal", session_factory)
    yield sqlite_engine


# ---------------------------------------------------------------------------
# Sample Flow fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_flow():
    """A minimal 3-node linear flow for executor tests."""
    flow = Flow("test_simple_flow")

    @flow.node
    def step_a(x: int) -> dict:
        return {"a_result": x * 2}

    @flow.node(depends_on=[step_a])
    def step_b(a_result: int) -> dict:
        return {"b_result": a_result + 1}

    @flow.node(depends_on=[step_b])
    def step_c(b_result: int) -> dict:
        return {"final": b_result}

    return flow


@pytest.fixture
def branching_flow():
    """A flow with two parallel branches merging into a final node."""
    flow = Flow("test_branching_flow")

    @flow.node
    def start(value: int) -> dict:
        return {"value": value}

    @flow.node(depends_on=[start])
    def branch_a(value: int) -> dict:
        return {"a": value + 10}

    @flow.node(depends_on=[start])
    def branch_b(value: int) -> dict:
        return {"b": value + 20}

    @flow.node(depends_on=[branch_a, branch_b])
    def merge(a: int, b: int) -> dict:
        return {"merged": a + b}

    return flow


# ---------------------------------------------------------------------------
# Pre-built FlowExecution dataclass (no DB required)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_execution():
    """A FlowExecution dataclass instance for unit testing state operations."""
    ex = FlowExecution(
        id="test-exec-001",
        flow_name="test_flow",
        status=ExecutionStatus.PENDING,
        input_data={"x": 1},
    )
    return ex
