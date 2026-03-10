"""Admin API routes for the dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from hof.api.auth import verify_auth
from hof.core.registry import registry
from hof.flows.state import execution_store

router = APIRouter()


@router.get("/overview")
async def admin_overview(user: str = Depends(verify_auth)) -> dict:
    """Dashboard overview: counts of all registered components and recent activity."""
    recent_executions = execution_store.list_executions(limit=10)

    return {
        "registry": registry.summary(),
        "tables": list(registry.tables.keys()),
        "functions": list(registry.functions.keys()),
        "flows": list(registry.flows.keys()),
        "cron_jobs": list(registry.cron_jobs.keys()),
        "recent_executions": [e.to_dict() for e in recent_executions],
    }


@router.get("/flows/{flow_name}/dag")
async def flow_dag(
    flow_name: str,
    user: str = Depends(verify_auth),
) -> dict:
    """Get the DAG structure for rendering in the flow viewer."""
    flow = registry.get_flow(flow_name)
    if flow is None:
        return {"error": f"Flow '{flow_name}' not found"}

    nodes = []
    edges = []

    for name, meta in flow.nodes.items():
        nodes.append(
            {
                "id": name,
                "label": name,
                "description": meta.fn.__doc__ or "",
                "is_human": meta.is_human,
                "human_ui": meta.human_ui,
                "tags": meta.tags,
            }
        )
        for dep in meta.depends_on:
            edges.append({"source": dep, "target": name})

    execution_order = flow.get_execution_order()

    return {
        "name": flow_name,
        "nodes": nodes,
        "edges": edges,
        "execution_order": execution_order,
    }


@router.get("/pending-actions")
async def pending_actions(user: str = Depends(verify_auth)) -> list[dict]:
    """List all pending human-in-the-loop actions."""
    executions = execution_store.list_executions(status="waiting_for_human", limit=50)
    actions = []

    for execution in executions:
        for ns in execution.node_states:
            if ns.status == "waiting_for_human":
                flow = registry.get_flow(execution.flow_name)
                node_meta = flow.nodes.get(ns.node_name) if flow else None

                actions.append(
                    {
                        "execution_id": execution.id,
                        "flow_name": execution.flow_name,
                        "node_name": ns.node_name,
                        "ui_component": node_meta.human_ui if node_meta else None,
                        "input_data": ns.input_data,
                        "started_at": ns.started_at.isoformat() if ns.started_at else None,
                    }
                )

    return actions
