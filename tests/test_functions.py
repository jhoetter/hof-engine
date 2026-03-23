"""Tests for hof.functions."""

from __future__ import annotations

import inspect

from hof.core.registry import registry
from hof.functions import FunctionMetadata, ParameterInfo, _extract_parameters, function


class TestFunctionDecorator:
    def test_bare_decorator_registers(self):
        @function
        def my_fn(x: int) -> dict:
            """My function."""
            return {"x": x}

        assert registry.get_function("my_fn") is not None

    def test_decorator_with_args_registers(self):
        @function(tags=["test"], timeout=30)
        def tagged_fn() -> dict:
            return {}

        meta = registry.get_function("tagged_fn")
        assert meta is not None
        assert meta.tags == ["test"]
        assert meta.timeout == 30

    def test_custom_name(self):
        @function(name="custom_name")
        def original_name() -> dict:
            return {}

        assert registry.get_function("custom_name") is not None
        assert registry.get_function("original_name") is None

    def test_description_from_docstring(self):
        @function
        def documented_fn() -> dict:
            """This is the description."""
            return {}

        meta = registry.get_function("documented_fn")
        assert meta.description == "This is the description."

    def test_custom_description(self):
        @function(description="Custom description")
        def fn_with_desc() -> dict:
            """Docstring ignored."""
            return {}

        meta = registry.get_function("fn_with_desc")
        assert meta.description == "Custom description"

    def test_sync_function_detected(self):
        @function
        def sync_fn() -> dict:
            return {}

        meta = registry.get_function("sync_fn")
        assert meta.is_async is False

    def test_async_function_detected(self):
        @function
        async def async_fn() -> dict:
            return {}

        meta = registry.get_function("async_fn")
        assert meta.is_async is True

    def test_function_still_callable(self):
        @function
        def add(a: int, b: int) -> dict:
            return {"sum": a + b}

        assert add(a=1, b=2) == {"sum": 3}

    def test_async_function_still_callable(self):
        import asyncio

        @function
        async def async_add(a: int, b: int) -> dict:
            return {"sum": a + b}

        result = asyncio.run(async_add(a=3, b=4))
        assert result == {"sum": 7}

    def test_hof_function_attribute(self):
        @function
        def attr_fn() -> dict:
            return {}

        assert hasattr(attr_fn, "_hof_function")
        assert isinstance(attr_fn._hof_function, FunctionMetadata)

    def test_retries_default(self):
        @function
        def default_fn() -> dict:
            return {}

        meta = registry.get_function("default_fn")
        assert meta.retries == 0

    def test_retries_custom(self):
        @function(retries=3)
        def retry_fn() -> dict:
            return {}

        meta = registry.get_function("retry_fn")
        assert meta.retries == 3

    def test_stream_fn_registers(self):
        def _stream_gen(n: int):
            yield {"type": "item", "n": n}

        @function(stream=_stream_gen)
        def with_stream(n: int) -> dict:
            return {"n": n}

        meta = registry.get_function("with_stream")
        assert meta is not None
        assert meta.stream_fn is not None
        assert meta.to_dict()["has_stream"] is True

    def test_agent_metadata_on_decorator(self):
        @function(
            tool_summary="One line.",
            when_to_use="When needed.",
            when_not_to_use="Not for X.",
            related_tools=["b", "c"],
        )
        def meta_fn() -> dict:
            """Full doc."""
            return {}

        meta = registry.get_function("meta_fn")
        assert meta is not None
        assert meta.tool_summary == "One line."
        assert meta.when_to_use == "When needed."
        assert meta.when_not_to_use == "Not for X."
        assert meta.related_tools == ("b", "c")
        d = meta.to_dict()
        assert d["tool_summary"] == "One line."
        assert d["when_to_use"] == "When needed."
        assert d["when_not_to_use"] == "Not for X."
        assert d["related_tools"] == ["b", "c"]


class TestFunctionMetadataToDict:
    def test_to_dict_structure(self):
        @function(tags=["a", "b"], timeout=45)
        def structured_fn(x: int, y: str = "default") -> dict:
            """Structured function."""
            return {}

        meta = registry.get_function("structured_fn")
        d = meta.to_dict()
        assert d["name"] == "structured_fn"
        assert d["description"] == "Structured function."
        assert d["tags"] == ["a", "b"]
        assert d["timeout"] == 45
        assert d["is_async"] is False
        assert d.get("has_stream") is False
        assert isinstance(d["parameters"], list)

    def test_parameters_in_to_dict(self):
        @function
        def param_fn(required_param: int, optional_param: str = "hi") -> dict:
            return {}

        meta = registry.get_function("param_fn")
        d = meta.to_dict()
        params = {p["name"]: p for p in d["parameters"]}
        assert params["required_param"]["required"] is True
        assert params["optional_param"]["required"] is False


class TestExtractParameters:
    def test_required_parameter(self):
        def fn(x: int) -> None:
            pass

        params = _extract_parameters(fn)
        assert len(params) == 1
        assert params[0].name == "x"
        assert params[0].required is True

    def test_optional_parameter(self):
        def fn(x: int = 5) -> None:
            pass

        params = _extract_parameters(fn)
        assert params[0].required is False
        assert params[0].default == 5

    def test_no_parameters(self):
        def fn() -> None:
            pass

        params = _extract_parameters(fn)
        assert params == []

    def test_multiple_parameters(self):
        def fn(a: int, b: str, c: float = 1.0) -> None:
            pass

        params = _extract_parameters(fn)
        assert len(params) == 3
        names = [p.name for p in params]
        assert names == ["a", "b", "c"]


class TestParameterInfoToDict:
    def test_to_dict_required(self):
        p = ParameterInfo(
            name="x", type_annotation=int, default=inspect.Parameter.empty, required=True
        )
        d = p.to_dict()
        assert d["name"] == "x"
        assert d["type"] == "int"
        assert d["required"] is True
        assert d["default"] is None

    def test_to_dict_optional(self):
        p = ParameterInfo(name="y", type_annotation=str, default="hello", required=False)
        d = p.to_dict()
        assert d["required"] is False
        assert d["default"] == repr("hello")
