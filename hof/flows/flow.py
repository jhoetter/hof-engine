"""Flow class: DAG definition and execution trigger."""

from __future__ import annotations

import asyncio
import copy
import functools
import logging
from collections.abc import Callable
from typing import Any

from hof.core.registry import registry
from hof.flows.node import NodeMetadata, _resolve_dep_names

logger = logging.getLogger("hof.flows")


class Flow:
    """A directed acyclic graph of nodes defining a workflow.

    Usage:
        pipeline = Flow("my_pipeline")

        @pipeline.node
        def step_a(data: str) -> dict:
            return {"result": data}

        @pipeline.node(depends_on=[step_a])
        def step_b(result: str) -> dict:
            return {"final": result}

        execution = pipeline.run(data="hello")
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.nodes: dict[str, NodeMetadata] = {}
        registry.register_flow(self)

    def node(
        self,
        fn: Callable | None = None,
        *,
        depends_on: list[Callable | str] | None = None,
        retries: int = 0,
        retry_delay: int = 30,
        timeout: int = 60,
        tags: list[str] | None = None,
        when: Callable | None = None,
        when_label: str = "",
    ) -> Callable:
        """Register a function as a node in this flow.

        Can be used as a bare decorator or with arguments:
            @flow.node
            def my_step(): ...

            @flow.node(depends_on=[other_step], retries=3)
            def my_step(): ...

            @flow.node(
                depends_on=[gate],
                when=lambda ctx: ctx.get("flag"),
                when_label="flag == true",
            )
            def conditional_step(): ...
        """

        def decorator(fn: Callable) -> Callable:
            existing_meta: NodeMetadata | None = getattr(fn, "_hof_node", None)

            if existing_meta:
                meta = existing_meta
                if depends_on:
                    meta.depends_on = _resolve_dep_names(depends_on)
                if retries:
                    meta.retries = retries
                if retry_delay != 30:
                    meta.retry_delay = retry_delay
                if timeout != 60:
                    meta.timeout = timeout
                if tags:
                    meta.tags = tags
                if when is not None:
                    meta.when = when
                if when_label:
                    meta.when_label = when_label
            else:
                dep_names = _resolve_dep_names(depends_on or [])
                meta = NodeMetadata(
                    name=fn.__name__,
                    fn=fn,
                    depends_on=dep_names,
                    retries=retries,
                    retry_delay=retry_delay,
                    timeout=timeout,
                    tags=tags or [],
                    is_async=asyncio.iscoroutinefunction(fn),
                    when=when,
                    when_label=when_label,
                )

            self.nodes[meta.name] = meta

            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                return fn(*args, **kwargs)

            wrapper._hof_node = meta  # type: ignore[attr-defined]
            return wrapper

        if fn is not None:
            return decorator(fn)
        return decorator

    def add_node(
        self,
        fn: Callable,
        *,
        depends_on: list[Callable | str] | None = None,
    ) -> None:
        """Programmatically add an existing function as a node.

        Useful for reusing functions across multiple flows:
            flow_a.add_node(shared_function)
            flow_b.add_node(shared_function, depends_on=[other_node])
        """
        existing_meta: NodeMetadata | None = getattr(fn, "_hof_node", None)
        if existing_meta:
            meta = copy.copy(existing_meta)
            if depends_on:
                meta.depends_on = _resolve_dep_names(depends_on)
        else:
            meta = NodeMetadata(
                name=fn.__name__,
                fn=fn,
                depends_on=_resolve_dep_names(depends_on or []),
                is_async=asyncio.iscoroutinefunction(fn),
            )

        self.nodes[meta.name] = meta

    def validate(self) -> list[str]:
        """Validate the DAG structure. Returns a list of errors (empty if valid)."""
        errors: list[str] = []
        node_names = set(self.nodes.keys())

        for name, meta in self.nodes.items():
            for dep in meta.depends_on:
                if dep not in node_names:
                    errors.append(f"Node '{name}' depends on unknown node '{dep}'")

        if self._has_cycle():
            errors.append("Flow contains a cycle")

        if not self.nodes:
            errors.append("Flow has no nodes")

        return errors

    def get_entry_nodes(self) -> list[NodeMetadata]:
        """Get nodes with no dependencies (starting points)."""
        return [n for n in self.nodes.values() if not n.depends_on]

    def get_execution_order(self) -> list[list[str]]:
        """Get nodes grouped by execution wave (topological layers).

        Returns a list of lists: each inner list contains node names that can
        run in parallel.
        """
        remaining = dict(self.nodes)
        completed: set[str] = set()
        waves: list[list[str]] = []

        while remaining:
            wave = [
                name
                for name, meta in remaining.items()
                if all(dep in completed for dep in meta.depends_on)
            ]
            if not wave:
                raise ValueError(f"Cycle detected in flow '{self.name}'")
            waves.append(wave)
            completed.update(wave)
            for name in wave:
                del remaining[name]

        return waves

    def to_dict(self) -> dict:
        """Serialize the flow definition."""
        return {
            "name": self.name,
            "nodes": {name: meta.to_dict() for name, meta in self.nodes.items()},
            "execution_order": self.get_execution_order(),
        }

    def run(self, **kwargs: Any) -> Any:
        """Trigger a new execution of this flow.

        In production, this dispatches to Celery. For simple cases or testing,
        it can run synchronously.
        """
        from hof.flows.executor import FlowExecutor

        executor = FlowExecutor(self)
        return executor.start(kwargs)

    def _has_cycle(self) -> bool:
        """Detect cycles using DFS."""
        white, gray, black = 0, 1, 2
        color = {name: white for name in self.nodes}

        def dfs(name: str) -> bool:
            color[name] = gray
            for dep_name in self.nodes[name].depends_on:
                if dep_name not in color:
                    continue
                if color[dep_name] == gray:
                    return True
                if color[dep_name] == white and dfs(dep_name):
                    return True
            color[name] = black
            return False

        return any(color[name] == white and dfs(name) for name in self.nodes)
