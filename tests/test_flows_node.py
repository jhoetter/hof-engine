"""Tests for hof.flows.node."""

from __future__ import annotations

import functools
from typing import Any

import pytest

from hof.flows.node import (
    NodeMetadata,
    _filter_kwargs,
    _get_real_signature,
    _resolve_dep_names,
    node,
)


class TestNodeDecorator:
    def test_bare_decorator(self):
        @node
        def my_step(x: int) -> dict:
            return {"x": x}

        assert hasattr(my_step, "_hof_node")
        meta = my_step._hof_node
        assert meta.name == "my_step"
        assert meta.depends_on == []
        assert meta.retries == 0
        assert meta.is_async is False

    def test_decorator_with_args(self):
        @node(retries=3, timeout=120, tags=["important"])
        def my_step(x: int) -> dict:
            return {"x": x}

        meta = my_step._hof_node
        assert meta.retries == 3
        assert meta.timeout == 120
        assert meta.tags == ["important"]

    def test_decorator_with_depends_on_strings(self):
        @node(depends_on=["step_a", "step_b"])
        def my_step() -> dict:
            return {}

        assert my_step._hof_node.depends_on == ["step_a", "step_b"]

    def test_decorator_with_depends_on_functions(self):
        @node
        def step_a() -> dict:
            return {}

        @node(depends_on=[step_a])
        def step_b() -> dict:
            return {}

        assert step_b._hof_node.depends_on == ["step_a"]

    def test_async_function_detected(self):
        @node
        async def async_step(x: int) -> dict:
            return {"x": x}

        assert async_step._hof_node.is_async is True

    def test_sync_function_detected(self):
        @node
        def sync_step(x: int) -> dict:
            return {"x": x}

        assert sync_step._hof_node.is_async is False

    def test_preserves_function_name(self):
        @node
        def original_name() -> dict:
            return {}

        assert original_name.__name__ == "original_name"

    def test_function_still_callable(self):
        @node
        def add(a: int, b: int) -> dict:
            return {"sum": a + b}

        result = add(a=1, b=2)
        assert result == {"sum": 3}


class TestNodeMetadataExecute:
    def test_execute_sync(self):
        def fn(x: int) -> dict:
            return {"result": x * 2}

        meta = NodeMetadata(name="fn", fn=fn)
        assert meta.execute(x=5) == {"result": 10}

    def test_execute_filters_extra_kwargs(self):
        def fn(x: int) -> dict:
            return {"x": x}

        meta = NodeMetadata(name="fn", fn=fn)
        result = meta.execute(x=3, extra_ignored=99)
        assert result == {"x": 3}

    def test_execute_async(self):
        async def async_fn(x: int) -> dict:
            return {"x": x}

        meta = NodeMetadata(name="async_fn", fn=async_fn, is_async=True)
        result = meta.execute(x=7)
        assert result == {"x": 7}

    def test_to_dict(self):
        def fn() -> dict:
            return {}

        meta = NodeMetadata(
            name="my_node",
            fn=fn,
            depends_on=["dep1"],
            retries=2,
            timeout=30,
            tags=["t1"],
            is_human=False,
        )
        d = meta.to_dict()
        assert d["name"] == "my_node"
        assert d["depends_on"] == ["dep1"]
        assert d["retries"] == 2
        assert d["timeout"] == 30
        assert d["tags"] == ["t1"]
        assert d["is_human"] is False


class TestFilterKwargs:
    def test_keeps_accepted_params(self):
        def fn(a: int, b: str) -> None:
            pass

        result = _filter_kwargs(fn, {"a": 1, "b": "x", "c": 99})
        assert result == {"a": 1, "b": "x"}

    def test_passes_all_for_var_keyword(self):
        def fn(**kwargs: Any) -> None:
            pass

        data = {"a": 1, "b": 2, "c": 3}
        assert _filter_kwargs(fn, data) == data

    def test_empty_kwargs(self):
        def fn(a: int) -> None:
            pass

        assert _filter_kwargs(fn, {}) == {}

    def test_no_matching_params(self):
        def fn(a: int) -> None:
            pass

        assert _filter_kwargs(fn, {"x": 1, "y": 2}) == {}


class TestGetRealSignature:
    def test_plain_function(self):
        def fn(a: int, b: str) -> None:
            pass

        sig = _get_real_signature(fn)
        assert list(sig.parameters.keys()) == ["a", "b"]

    def test_wrapped_function(self):
        def original(x: int, y: int) -> int:
            return x + y

        @functools.wraps(original)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return original(*args, **kwargs)

        wrapper.__wrapped__ = original
        sig = _get_real_signature(wrapper)
        assert list(sig.parameters.keys()) == ["x", "y"]

    def test_generic_wrapper_without_wrapped(self):
        def original(x: int) -> int:
            return x

        @functools.wraps(original)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return original(*args, **kwargs)

        sig = _get_real_signature(wrapper)
        # Falls back to wrapper signature if no __wrapped__
        params = list(sig.parameters.keys())
        assert len(params) > 0


class TestResolveDepNames:
    def test_string_deps(self):
        assert _resolve_dep_names(["a", "b"]) == ["a", "b"]

    def test_function_deps(self):
        @node
        def step_a() -> dict:
            return {}

        result = _resolve_dep_names([step_a])
        assert result == ["step_a"]

    def test_callable_without_hof_node(self):
        def plain_fn() -> None:
            pass

        result = _resolve_dep_names([plain_fn])
        assert result == ["plain_fn"]

    def test_mixed_deps(self):
        @node
        def step_a() -> dict:
            return {}

        result = _resolve_dep_names([step_a, "step_b"])
        assert result == ["step_a", "step_b"]

    def test_invalid_dep_raises(self):
        with pytest.raises(ValueError, match="Invalid dependency"):
            _resolve_dep_names([42])  # type: ignore[list-item]

    def test_empty_deps(self):
        assert _resolve_dep_names([]) == []
