"""Agent-facing API routes (tool listing, etc.)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from hof.agent.policy import try_get_agent_policy
from hof.agent.tooling import openai_tool_specs, structured_agent_tool_for_ui
from hof.api.auth import verify_auth
from hof.core.registry import registry

router = APIRouter()


@router.get("/tools")
async def list_agent_tools(user: str = Depends(verify_auth)) -> dict[str, Any]:
    """List tools the agent may call (effective allowlist, same descriptions as ``agent_chat``)."""
    policy = try_get_agent_policy()
    if policy is None:
        return {"configured": False, "tools": []}

    specs = openai_tool_specs(policy.effective_allowlist())
    mutation_set = policy.allowlist_mutation
    tools: list[dict[str, Any]] = []
    for spec in specs:
        fn = spec.get("function") if isinstance(spec, dict) else None
        if not isinstance(fn, dict):
            continue
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        meta = registry.get_function(name)
        if meta is None:
            continue
        raw_params = fn.get("parameters")
        if isinstance(raw_params, dict):
            parameters = raw_params
        else:
            parameters = {"type": "object", "properties": {}, "required": []}
        tools.append(
            structured_agent_tool_for_ui(
                name,
                meta,
                policy,
                mutation=name in mutation_set,
                parameters=parameters,
            )
        )
    return {"configured": True, "tools": tools}
