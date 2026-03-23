"""Function decorator for registering backend functions."""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Callable, Iterator
from typing import Any

from hof.core.registry import registry


def function(
    fn: Callable | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    tool_summary: str | None = None,
    when_to_use: str | None = None,
    when_not_to_use: str | None = None,
    related_tools: list[str] | tuple[str, ...] | None = None,
    tags: list[str] | None = None,
    timeout: int = 60,
    retries: int = 0,
    public: bool = False,
    stream: Callable[..., Iterator[dict[str, Any]]] | None = None,
) -> Callable:
    """Register a function in the hof registry.

    Can be used as a bare decorator or with arguments:
        @function
        def my_fn(): ...

        @function(tags=["ai"])
        def my_fn(): ...

        @function(public=True)
        def my_public_fn(): ...

    Set ``public=True`` to allow unauthenticated access via the API.

    Optional agent/CLI metadata (also surfaced in OpenAI tool descriptions when configured):
    ``tool_summary`` (one line, e.g. for ``hof fn list``), ``when_to_use``, ``when_not_to_use``,
    ``related_tools`` (ordered names for typical follow-up tools).

    Optional ``stream``: a **sync generator** with the same parameters as ``fn`` that yields
    JSON-serializable dicts (e.g. NDJSON lines for ``POST /api/functions/<name>/stream``).
    """

    def decorator(fn: Callable) -> Callable:
        fn_name = name or fn.__name__
        fn_description = description or fn.__doc__ or ""
        rt: tuple[str, ...] = ()
        if related_tools:
            rt = tuple(related_tools)

        metadata = FunctionMetadata(
            name=fn_name,
            description=fn_description.strip(),
            tool_summary=(tool_summary.strip() if tool_summary else None),
            when_to_use=(when_to_use.strip() if when_to_use else None),
            when_not_to_use=(when_not_to_use.strip() if when_not_to_use else None),
            related_tools=rt,
            tags=tags or [],
            timeout=timeout,
            retries=retries,
            fn=fn,
            is_async=asyncio.iscoroutinefunction(fn),
            parameters=_extract_parameters(fn),
            return_type=inspect.signature(fn).return_annotation,
            public=public,
            stream_fn=stream,
        )

        registry.register_function(metadata)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await fn(*args, **kwargs)

        chosen = async_wrapper if metadata.is_async else wrapper
        chosen._hof_function = metadata  # type: ignore[attr-defined]
        return chosen

    if fn is not None:
        return decorator(fn)
    return decorator


class FunctionMetadata:
    """Metadata about a registered function."""

    __slots__ = (
        "name",
        "description",
        "tool_summary",
        "when_to_use",
        "when_not_to_use",
        "related_tools",
        "tags",
        "timeout",
        "retries",
        "fn",
        "is_async",
        "parameters",
        "return_type",
        "public",
        "stream_fn",
    )

    def __init__(
        self,
        *,
        name: str,
        description: str,
        tool_summary: str | None = None,
        when_to_use: str | None = None,
        when_not_to_use: str | None = None,
        related_tools: tuple[str, ...] = (),
        tags: list[str],
        timeout: int,
        retries: int,
        fn: Callable,
        is_async: bool,
        parameters: list[ParameterInfo],
        return_type: Any,
        public: bool = False,
        stream_fn: Callable[..., Iterator[dict[str, Any]]] | None = None,
    ):
        self.name = name
        self.description = description
        self.tool_summary = tool_summary
        self.when_to_use = when_to_use
        self.when_not_to_use = when_not_to_use
        self.related_tools = related_tools
        self.tags = tags
        self.timeout = timeout
        self.retries = retries
        self.fn = fn
        self.is_async = is_async
        self.parameters = parameters
        self.return_type = return_type
        self.public = public
        self.stream_fn = stream_fn

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "timeout": self.timeout,
            "retries": self.retries,
            "is_async": self.is_async,
            "public": self.public,
            "has_stream": self.stream_fn is not None,
            "parameters": [p.to_dict() for p in self.parameters],
        }
        if self.tool_summary:
            d["tool_summary"] = self.tool_summary
        if self.when_to_use:
            d["when_to_use"] = self.when_to_use
        if self.when_not_to_use:
            d["when_not_to_use"] = self.when_not_to_use
        if self.related_tools:
            d["related_tools"] = list(self.related_tools)
        return d


class ParameterInfo:
    """Metadata about a function parameter."""

    __slots__ = ("name", "type_annotation", "default", "required")

    def __init__(self, *, name: str, type_annotation: Any, default: Any, required: bool):
        self.name = name
        self.type_annotation = type_annotation
        self.default = default
        self.required = required

    def to_dict(self) -> dict:
        type_name = (
            getattr(self.type_annotation, "__name__", str(self.type_annotation))
            if self.type_annotation is not inspect.Parameter.empty
            else "Any"
        )
        return {
            "name": self.name,
            "type": type_name,
            "required": self.required,
            "default": None if self.default is inspect.Parameter.empty else repr(self.default),
        }


def _extract_parameters(fn: Callable) -> list[ParameterInfo]:
    sig = inspect.signature(fn)
    params = []
    for param_name, param in sig.parameters.items():
        params.append(
            ParameterInfo(
                name=param_name,
                type_annotation=param.annotation,
                default=param.default,
                required=param.default is inspect.Parameter.empty,
            )
        )
    return params
