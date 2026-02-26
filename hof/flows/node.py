"""Flow node definition and decorator."""

from __future__ import annotations

import asyncio
import functools
from dataclasses import dataclass, field
from typing import Any, Callable


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
        """Execute the node function, handling async transparently."""
        if self.is_async:
            return asyncio.run(self.fn(**kwargs))
        return self.fn(**kwargs)

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
