"""Celery application factory and task definitions."""

from __future__ import annotations

from datetime import UTC

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
        worker_prefetch_multiplier=4,
    )

    return app


celery = create_celery_app()


@celery.on_after_finalize.connect
def _setup_beat_schedule(sender: Celery, **kwargs: object) -> None:
    """Populate Celery Beat schedule from registered cron jobs after app is ready."""
    from hof.cron.scheduler import get_celery_beat_schedule

    schedule = get_celery_beat_schedule()
    sender.conf.beat_schedule = schedule


@celery.task(name="hof.execute_node", bind=True, max_retries=3)
def execute_node_task(self, execution_id: str, node_name: str, input_data: dict) -> dict:
    """Celery task that executes a single flow node."""
    from datetime import datetime

    from hof.core.registry import registry
    from hof.flows.executor import _normalize_result
    from hof.flows.state import NodeStatus, execution_store

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
        started_at=datetime.now(UTC),
    )

    try:
        result = meta.execute(**input_data)
        result = _normalize_result(result)

        ns.output_data = result
        ns.status = NodeStatus.COMPLETED
        ns.completed_at = datetime.now(UTC)
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


@celery.task(name="hof.compute_bulk")
def compute_bulk_task(
    compute_fn_name: str,
    record_ids: list[str],
    sse_channel: str | None = None,
) -> dict:
    """Background task: run a registered function for each record and stream results via SSE.

    The named function receives ``record_id`` and ``sse_channel`` and must
    return a dict of computed field values.
    """
    from pathlib import Path

    from hof.api.routes.sse import publish_computation_event
    from hof.config import load_config
    from hof.core.discovery import discover_all
    from hof.core.registry import registry
    from hof.db.engine import init_engine

    config = load_config()
    init_engine(
        config.database_url,
        pool_size=config.database_pool_size,
        echo=config.database_echo,
    )
    discover_all(Path.cwd(), config.discovery_dirs)

    meta = registry.get_function(compute_fn_name)
    if meta is None:
        if sse_channel:
            publish_computation_event(sse_channel, {"status": "done"})
        raise ValueError(f"Compute function '{compute_fn_name}' not found")

    computed_count = 0
    errors: list[dict] = []

    try:
        for record_id in record_ids:
            try:
                result = meta.fn(record_id=record_id, sse_channel=sse_channel)
                computed_count += 1
                if sse_channel and isinstance(result, dict):
                    for field, value in result.get("computed", {}).items():
                        publish_computation_event(sse_channel, {
                            "step": "completed",
                            "row_id": record_id,
                            "field": field,
                            "value": value,
                        })
            except Exception as exc:
                errors.append({"record_id": record_id, "error": str(exc)})
    finally:
        if sse_channel:
            publish_computation_event(sse_channel, {"status": "done"})

    return {"computed": computed_count, "errors": errors}


@celery.task(name="hof.execute_cron", bind=True, max_retries=3)
def execute_cron_task(self, cron_name: str) -> None:
    """Celery task that executes a registered cron job by name."""
    from pathlib import Path

    from hof.config import load_config
    from hof.core.discovery import discover_all
    from hof.core.registry import registry

    config = load_config()
    discover_all(Path.cwd(), config.discovery_dirs)

    meta = registry.get_cron(cron_name)
    if meta is None:
        raise ValueError(f"Cron job '{cron_name}' not found")

    if not meta.enabled:
        return

    try:
        meta.fn()
    except Exception as exc:
        if self.request.retries < meta.retries:
            raise self.retry(exc=exc, countdown=60)
        raise
