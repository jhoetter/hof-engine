"""Flow node definition and decorator."""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NodeMetadata:
    """Metadata for a flow node."""

    name: str
    fn: Callable
    depends_on: list[str] = field(default_factory=list)
    retries: int = 0
    retry_delay: int = 30
    timeout: int = 60
    tags: list[str] = field(default_factory=list)
    is_human: bool = False
    human_ui: str | None = None
    human_timeout: str | None = None
    is_async: bool = False

    def execute(self, **kwargs: Any) -> Any:
        """Execute the node function, filtering kwargs to only accepted params."""
        filtered = _filter_kwargs(self.fn, kwargs)
        if self.is_async:
            return asyncio.run(self.fn(**filtered))
        return self.fn(**filtered)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "depends_on": self.depends_on,
            "retries": self.retries,
            "timeout": self.timeout,
            "tags": self.tags,
            "is_human": self.is_human,
            "human_ui": self.human_ui,
        }


def _filter_kwargs(fn: Callable, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Keep only kwargs the function accepts. Pass all if it has **kwargs."""
    sig = _get_real_signature(fn)
    has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    if has_var_keyword:
        return kwargs
    accepted = set(sig.parameters.keys())
    return {k: v for k, v in kwargs.items() if k in accepted}


def _get_real_signature(fn: Callable) -> inspect.Signature:
    """Get the signature of the actual function, unwrapping decorator wrappers.

    Handles cases like llm-markdown's @prompt where the wrapper uses (*args, **kwargs)
    but the original function has a concrete signature in the closure.
    """
    if hasattr(fn, "__wrapped__"):
        return inspect.signature(fn.__wrapped__)

    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    is_generic_wrapper = (
        len(params) == 2
        and params[0].kind == inspect.Parameter.VAR_POSITIONAL
        and params[1].kind == inspect.Parameter.VAR_KEYWORD
    )

    if is_generic_wrapper and hasattr(fn, "__closure__") and fn.__closure__:
        for cell in fn.__closure__:
            try:
                obj = cell.cell_contents
                if callable(obj) and hasattr(obj, "__name__") and obj.__name__ == fn.__name__:
                    return inspect.signature(obj)
            except ValueError:
                continue

    return sig


def node(
    fn: Callable | None = None,
    *,
    depends_on: list[Callable | str] | None = None,
    retries: int = 0,
    retry_delay: int = 30,
    timeout: int = 60,
    tags: list[str] | None = None,
) -> Callable:
    """Standalone node decorator (for use outside of a Flow context).

    Typically you use @flow.node instead, but this can be used to pre-configure
    a function as a node before adding it to a flow.
    """

    def decorator(fn: Callable) -> Callable:
        dep_names = _resolve_dep_names(depends_on or [])

        metadata = NodeMetadata(
            name=fn.__name__,
            fn=fn,
            depends_on=dep_names,
            retries=retries,
            retry_delay=retry_delay,
            timeout=timeout,
            tags=tags or [],
            is_async=asyncio.iscoroutinefunction(fn),
        )

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        wrapper._hof_node = metadata  # type: ignore[attr-defined]
        return wrapper

    if fn is not None:
        return decorator(fn)
    return decorator


def _resolve_dep_names(deps: list[Callable | str]) -> list[str]:
    """Convert dependency references to node name strings."""
    names = []
    for dep in deps:
        if isinstance(dep, str):
            names.append(dep)
        elif hasattr(dep, "_hof_node"):
            names.append(dep._hof_node.name)
        elif callable(dep):
            names.append(dep.__name__)
        else:
            raise ValueError(f"Invalid dependency: {dep}")
    return names
