"""Defer HTTP function execution when a terminal sandbox agent correlates a mutation.

See ``hof.agent.sandbox.mutation_bridge`` — curl must send ``X-Hof-Agent-Run-Id`` (and
``X-Hof-Agent-Tool-Call-Id``) so POST /api/functions/<mutation> returns a pending placeholder
without writing, matching the in-process ``mutation_pending`` contract.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from hof.agent.policy import (
    AgentPolicy,
    MutationPreviewResult,
    mutation_preview_to_wire,
    try_get_agent_policy,
)
from hof.agent.sandbox.mutation_bridge import (
    AGENT_RUN_HEADER_NAME,
    AGENT_TOOL_CALL_HEADER_NAME,
)
from hof.agent.state import load_agent_run, save_pending

logger = logging.getLogger(__name__)


def _preview_for_mutation(
    policy: AgentPolicy,
    function_name: str,
    kwargs: dict[str, Any],
) -> dict[str, Any] | None:
    fn = policy.mutation_preview.get(function_name)
    if fn is None:
        return None
    try:
        out = fn(kwargs)
        if out is None:
            return None
        if isinstance(out, MutationPreviewResult):
            wire = mutation_preview_to_wire(out)
        elif isinstance(out, dict):
            wire = mutation_preview_to_wire(out)
        else:
            return None
        json.dumps(wire, default=str)
        return wire
    except Exception:
        logger.debug(
            "http_mutation_gate: mutation_preview failed for %s",
            function_name,
            exc_info=True,
        )
        return None


def defer_mutation_if_terminal_agent_http(
    *,
    function_name: str,
    kwargs: dict[str, Any],
    agent_run_id: str,
    tool_call_id: str,
) -> dict[str, Any] | None:
    """Return the inner ``result`` object for a deferred mutation, or ``None`` to execute normally.

    Caller wraps as ``{"result": <dict>, "duration_ms": 0, "function": name}``.
    """
    policy = try_get_agent_policy()
    if policy is None:
        return None
    sc = policy.sandbox.with_env_overrides() if policy.sandbox is not None else None
    if sc is None or not sc.enabled or not sc.terminal_only_dispatch:
        return None
    if function_name not in policy.allowlist_mutation:
        return None
    rid = agent_run_id.strip()
    if not rid or load_agent_run(rid) is None:
        return None
    tcid = (tool_call_id or "").strip() or "terminal"

    args_json = json.dumps(kwargs, default=str)
    pid = str(uuid.uuid4())
    preview_wire = _preview_for_mutation(policy, function_name, kwargs)

    save_pending(
        pid,
        {
            "run_id": rid,
            "tool_call_id": tcid,
            "function_name": function_name,
            "arguments_json": args_json,
        },
    )
    inner: dict[str, Any] = {
        "pending_confirmation": True,
        "pending_id": pid,
        "function": function_name,
    }
    if preview_wire is not None:
        inner["preview"] = preview_wire
    logger.info(
        "http_mutation_gate: deferred %s pending_id=%s run_id=%s",
        function_name,
        pid,
        rid,
    )
    return inner


__all__ = [
    "AGENT_RUN_HEADER_NAME",
    "AGENT_TOOL_CALL_HEADER_NAME",
    "defer_mutation_if_terminal_agent_http",
]
