"""Tests for hof.core.registry."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hof.core.registry import _Registry, registry


def _make_table(name: str):
    t = MagicMock()
    t.__tablename__ = name
    return t


def _make_function(name: str):
    meta = MagicMock()
    meta.name = name
    return meta


def _make_flow(name: str):
    f = MagicMock()
    f.name = name
    return f


def _make_cron(name: str):
    c = MagicMock()
    c.name = name
    return c


class TestRegistryIsolation:
    def test_starts_empty(self):
        assert registry.summary() == {"tables": 0, "functions": 0, "flows": 0, "cron_jobs": 0}

    def test_clear_resets_all(self):
        registry.register_table(_make_table("t1"))
        registry.register_function(_make_function("f1"))
        registry.clear()
        assert registry.summary() == {"tables": 0, "functions": 0, "flows": 0, "cron_jobs": 0}


class TestTableRegistration:
    def test_register_and_get(self):
        t = _make_table("my_table")
        registry.register_table(t)
        assert registry.get_table("my_table") is t

    def test_get_missing_returns_none(self):
        assert registry.get_table("nonexistent") is None

    def test_tables_property_returns_copy(self):
        t = _make_table("t1")
        registry.register_table(t)
        tables = registry.tables
        assert "t1" in tables
        # Mutating the copy doesn't affect registry
        tables["extra"] = MagicMock()
        assert "extra" not in registry.tables

    def test_overwrite_same_name(self):
        t1 = _make_table("shared")
        t2 = _make_table("shared")
        registry.register_table(t1)
        registry.register_table(t2)
        assert registry.get_table("shared") is t2


class TestFunctionRegistration:
    def test_register_and_get(self):
        f = _make_function("my_fn")
        registry.register_function(f)
        assert registry.get_function("my_fn") is f

    def test_get_missing_returns_none(self):
        assert registry.get_function("nope") is None

    def test_functions_property_returns_copy(self):
        f = _make_function("fn1")
        registry.register_function(f)
        fns = registry.functions
        assert "fn1" in fns
        fns["extra"] = MagicMock()
        assert "extra" not in registry.functions


class TestFlowRegistration:
    def test_register_and_get(self):
        f = _make_flow("my_flow")
        registry.register_flow(f)
        assert registry.get_flow("my_flow") is f

    def test_get_missing_returns_none(self):
        assert registry.get_flow("nope") is None

    def test_flows_property_returns_copy(self):
        f = _make_flow("flow1")
        registry.register_flow(f)
        flows = registry.flows
        assert "flow1" in flows


class TestCronRegistration:
    def test_register_and_get(self):
        c = _make_cron("my_cron")
        registry.register_cron(c)
        assert registry.get_cron("my_cron") is c

    def test_get_missing_returns_none(self):
        assert registry.get_cron("nope") is None

    def test_cron_jobs_property_returns_copy(self):
        c = _make_cron("cron1")
        registry.register_cron(c)
        jobs = registry.cron_jobs
        assert "cron1" in jobs


class TestSummary:
    def test_summary_counts_all_types(self):
        registry.register_table(_make_table("t1"))
        registry.register_table(_make_table("t2"))
        registry.register_function(_make_function("f1"))
        registry.register_flow(_make_flow("fl1"))
        registry.register_cron(_make_cron("c1"))
        registry.register_cron(_make_cron("c2"))

        s = registry.summary()
        assert s == {"tables": 2, "functions": 1, "flows": 1, "cron_jobs": 2}

    def test_summary_empty(self):
        assert registry.summary()["tables"] == 0


class TestThreadSafety:
    def test_concurrent_registration(self):
        import threading

        results = []

        def register_fn(i):
            f = _make_function(f"fn_{i}")
            registry.register_function(f)
            results.append(i)

        threads = [threading.Thread(target=register_fn, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(registry.functions) == 20
