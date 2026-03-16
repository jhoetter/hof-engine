"""Flow management and execution routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from hof.api.auth import verify_auth
from hof.core.registry import registry
from hof.flows.state import execution_store

router = APIRouter()


@router.get("")
async def list_flows(user: str = Depends(verify_auth)) -> list[dict]:
    """List all registered flow definitions."""
    return [flow.to_dict() for flow in registry.flows.values()]


@router.post("/{flow_name}/run")
def run_flow(
    flow_name: str,
    body: dict[str, Any] | None = None,
    user: str = Depends(verify_auth),
) -> dict:
    """Trigger a new flow execution.

    This is a sync def (not async) so FastAPI runs it in a thread pool,
    avoiding event-loop blocking from the sync database operations in
    the flow executor.
    """
    flow = registry.get_flow(flow_name)
    if flow is None:
        raise HTTPException(404, f"Flow '{flow_name}' not found")

    input_data = body or {}
    execution = flow.run(**input_data)
    return execution.to_dict()


@router.get("/{flow_name}/executions")
def list_executions(
    flow_name: str,
    status: str | None = None,
    limit: int = 20,
    user: str = Depends(verify_auth),
) -> list[dict]:
    """List executions for a flow."""
    flow = registry.get_flow(flow_name)
    if flow is None:
        raise HTTPException(404, f"Flow '{flow_name}' not found")

    executions = execution_store.list_executions(flow_name=flow_name, status=status, limit=limit)
    return [e.to_dict() for e in executions]


@router.get("/executions/{execution_id}")
def get_execution(
    execution_id: str,
    user: str = Depends(verify_auth),
) -> dict:
    """Get details of a flow execution."""
    execution = execution_store.get_execution(execution_id)
    if execution is None:
        raise HTTPException(404, f"Execution '{execution_id}' not found")
    return execution.to_dict()


@router.post("/executions/{execution_id}/cancel")
def cancel_execution(
    execution_id: str,
    user: str = Depends(verify_auth),
) -> dict:
    """Cancel a running execution."""
    execution_store.update_status(execution_id, "cancelled")
    return {"cancelled": True, "id": execution_id}


@router.post("/executions/{execution_id}/nodes/{node_name}/submit")
def submit_human_input(
    execution_id: str,
    node_name: str,
    body: dict[str, Any],
    user: str = Depends(verify_auth),
) -> dict:
    """Submit human input for a waiting node.

    Sync def so FastAPI runs it in a thread pool, avoiding event-loop
    blocking from the sync database operations in resume_after_human.
    """
    execution = execution_store.get_execution(execution_id)
    if execution is None:
        raise HTTPException(404, f"Execution '{execution_id}' not found")

    flow = registry.get_flow(execution.flow_name)
    if flow is None:
        raise HTTPException(404, f"Flow '{execution.flow_name}' not found")

    from hof.flows.executor import FlowExecutor

    executor = FlowExecutor(flow)
    result = executor.resume_after_human(execution_id, node_name, body)

    if result is None:
        raise HTTPException(400, "Could not submit input (node may not be waiting)")

    return result.to_dict()
