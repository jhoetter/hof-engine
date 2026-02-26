"""Human-in-the-loop node decorator."""

from __future__ import annotations

import functools
from typing import Any, Callable

from hof.flows.node import NodeMetadata


def human_node(
    fn: Callable | None = None,
    *,
    ui: str = "",
    timeout: str = "24h",
    assignee_field: str | None = None,
) -> Callable:
    """Mark a node as human-in-the-loop.

    When the flow reaches this node, execution pauses and the specified React
    component is rendered in the admin UI. The flow resumes when the human
    submits their response.

    Args:
        ui: Name of the React component (from ui/components/) to render.
        timeout: How long to wait for human input (e.g., "24h", "7d").
        assignee_field: Optional field in the input that specifies who should review.
    """

    def decorator(fn: Callable) -> Callable:
        existing_meta: NodeMetadata | None = getattr(fn, "_hof_node", None)

        if existing_meta:
            existing_meta.is_human = True
            existing_meta.human_ui = ui
            existing_meta.human_timeout = timeout
        else:
            metadata = NodeMetadata(
                name=fn.__name__,
                fn=fn,
                is_human=True,
                human_ui=ui,
                human_timeout=timeout,
            )

            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                return fn(*args, **kwargs)

            wrapper._hof_node = metadata  # type: ignore[attr-defined]
            wrapper._hof_human_assignee_field = assignee_field  # type: ignore[attr-defined]
            return wrapper

        fn._hof_human_assignee_field = assignee_field  # type: ignore[attr-defined]
        return fn

    if fn is not None:
        return decorator(fn)
    return decorator
