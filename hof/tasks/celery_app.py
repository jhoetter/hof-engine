"""Celery application factory and task definitions."""

from __future__ import annotations

from celery import Celery

from hof.config import get_config


def create_celery_app() -> Celery:
    """Create and configure the Celery application."""
    config = get_config()

    app = Celery(
        "hof",
        broker=config.redis_url,
        backend=config.redis_url,
    )

    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
    )

    return app


celery = create_celery_app()


@celery.task(name="hof.execute_node", bind=True, max_retries=3)
def execute_node_task(self, execution_id: str, node_name: str, input_data: dict) -> dict:
    """Celery task that executes a single flow node."""
    from hof.core.registry import registry
    from hof.flows.executor import _normalize_result
    from hof.flows.state import execution_store, NodeStatus
    from datetime import datetime, timezone

    execution = execution_store.get_execution(execution_id)
    if execution is None:
        raise ValueError(f"Execution {execution_id} not found")

    flow = registry.get_flow(execution.flow_name)
    if flow is None:
        raise ValueError(f"Flow {execution.flow_name} not found")

    meta = flow.nodes.get(node_name)
    if meta is None:
        raise ValueError(f"Node {node_name} not found in flow {execution.flow_name}")

    ns = execution.set_node_state(
        node_name,
        status=NodeStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )

    try:
        result = meta.execute(**input_data)
        result = _normalize_result(result)

        ns.output_data = result
        ns.status = NodeStatus.COMPLETED
        ns.completed_at = datetime.now(timezone.utc)
        if ns.started_at:
            delta = ns.completed_at - ns.started_at
            ns.duration_ms = int(delta.total_seconds() * 1000)

        execution_store.save_execution(execution)
        return result

    except Exception as exc:
        ns.status = NodeStatus.FAILED
        ns.error = str(exc)
        execution_store.save_execution(execution)
        if self.request.retries < meta.retries:
            raise self.retry(exc=exc, countdown=meta.retry_delay)
        raise


@celery.task(name="hof.run_flow")
def run_flow_task(flow_name: str, input_data: dict) -> str:
    """Celery task that orchestrates a full flow execution."""
    from hof.core.registry import registry
    from hof.flows.executor import FlowExecutor

    flow = registry.get_flow(flow_name)
    if flow is None:
        raise ValueError(f"Flow {flow_name} not found")

    executor = FlowExecutor(flow)
    execution = executor.start(input_data)
    return execution.id
