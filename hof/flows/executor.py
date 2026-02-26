"""Flow DAG executor.

Orchestrates node execution respecting dependency order. Independent nodes
are dispatched in parallel via Celery. Falls back to synchronous execution
when Celery is not available (development/testing).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from hof.flows.state import (
    ExecutionStatus,
    FlowExecution,
    NodeStatus,
    execution_store,
)

logger = logging.getLogger("hof.flows.executor")


class FlowExecutor:
    """Executes a flow's DAG, dispatching nodes in topological order."""

    def __init__(self, flow: Any) -> None:
        self.flow = flow

    def start(self, input_data: dict[str, Any]) -> FlowExecution:
        """Start a new execution of the flow."""
        errors = self.flow.validate()
        if errors:
            raise ValueError(f"Invalid flow '{self.flow.name}': {'; '.join(errors)}")

        execution = execution_store.create_execution(
            flow_name=self.flow.name,
            input_data=input_data,
            flow_snapshot=self.flow.to_dict(),
        )

        for node_name in self.flow.nodes:
            execution.set_node_state(node_name, status=NodeStatus.PENDING)

        try:
            self._execute_sync(execution)
        except Exception as exc:
            execution_store.update_status(execution.id, ExecutionStatus.FAILED)
            execution.error = str(exc)
            logger.exception("Flow '%s' execution %s failed", self.flow.name, execution.id)

        return execution

    def _execute_sync(self, execution: FlowExecution) -> None:
        """Synchronous execution: run waves sequentially, nodes within a wave sequentially.

        For production parallel execution, use _execute_celery instead.
        """
        execution_store.update_status(execution.id, ExecutionStatus.RUNNING)
        waves = self.flow.get_execution_order()
        node_outputs: dict[str, dict] = {}

        for wave in waves:
            if execution.status == ExecutionStatus.CANCELLED:
                break

            for node_name in wave:
                meta = self.flow.nodes[node_name]
                ns = execution.set_node_state(
                    node_name,
                    status=NodeStatus.RUNNING,
                    started_at=datetime.now(timezone.utc),
                )

                node_input = self._gather_input(meta, execution.input_data, node_outputs)
                ns.input_data = node_input

                if meta.is_human:
                    ns.status = NodeStatus.WAITING_FOR_HUMAN
                    execution_store.update_status(execution.id, ExecutionStatus.WAITING_FOR_HUMAN)
                    logger.info(
                        "Flow '%s' execution %s waiting for human input at node '%s'",
                        self.flow.name, execution.id, node_name,
                    )
                    node_outputs[node_name] = {}
                    continue

                try:
                    result = self._run_node_with_retries(meta, node_input)
                    if not isinstance(result, dict):
                        result = {"result": result}

                    ns.output_data = result
                    ns.status = NodeStatus.COMPLETED
                    ns.completed_at = datetime.now(timezone.utc)
                    if ns.started_at:
                        delta = ns.completed_at - ns.started_at
                        ns.duration_ms = int(delta.total_seconds() * 1000)

                    node_outputs[node_name] = result
                    logger.info("Node '%s' completed in %dms", node_name, ns.duration_ms or 0)

                except Exception as exc:
                    ns.status = NodeStatus.FAILED
                    ns.error = str(exc)
                    ns.completed_at = datetime.now(timezone.utc)
                    raise

        all_completed = all(
            ns.status in (NodeStatus.COMPLETED, NodeStatus.SKIPPED)
            for ns in execution.node_states
        )
        has_waiting = any(
            ns.status == NodeStatus.WAITING_FOR_HUMAN
            for ns in execution.node_states
        )

        if all_completed:
            last_wave = waves[-1] if waves else []
            final_output = {}
            for node_name in last_wave:
                final_output.update(node_outputs.get(node_name, {}))
            execution.output_data = final_output
            execution_store.update_status(execution.id, ExecutionStatus.COMPLETED)
        elif has_waiting:
            execution_store.update_status(execution.id, ExecutionStatus.WAITING_FOR_HUMAN)

    def _gather_input(
        self,
        meta: Any,
        flow_input: dict[str, Any],
        node_outputs: dict[str, dict],
    ) -> dict[str, Any]:
        """Build the input for a node by merging flow input and upstream outputs."""
        if not meta.depends_on:
            return dict(flow_input)

        merged: dict[str, Any] = {}
        for dep_name in meta.depends_on:
            dep_output = node_outputs.get(dep_name, {})
            merged.update(dep_output)
        return merged

    def _run_node_with_retries(self, meta: Any, input_data: dict) -> Any:
        """Run a node function with retry logic."""
        last_error: Exception | None = None

        for attempt in range(meta.retries + 1):
            try:
                return meta.execute(**input_data)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Node '%s' attempt %d/%d failed: %s",
                    meta.name, attempt + 1, meta.retries + 1, exc,
                )
                if attempt < meta.retries:
                    time.sleep(meta.retry_delay)

        raise last_error  # type: ignore[misc]

    def resume_after_human(self, execution_id: str, node_name: str, human_output: dict) -> FlowExecution | None:
        """Resume a flow after human input is submitted.

        Continues executing downstream nodes from the human node.
        """
        execution = execution_store.get_execution(execution_id)
        if execution is None:
            return None

        submitted = execution_store.submit_human_input(execution_id, node_name, human_output)
        if not submitted:
            return None

        node_outputs: dict[str, dict] = {}
        for ns in execution.node_states:
            if ns.status == NodeStatus.COMPLETED:
                node_outputs[ns.node_name] = ns.output_data

        node_outputs[node_name] = human_output

        execution_store.update_status(execution.id, ExecutionStatus.RUNNING)

        waves = self.flow.get_execution_order()
        found_human_wave = False

        for wave in waves:
            if node_name in wave:
                found_human_wave = True
                continue
            if not found_human_wave:
                continue

            for wn in wave:
                meta = self.flow.nodes[wn]
                ns = execution.get_node_state(wn)
                if ns and ns.status == NodeStatus.COMPLETED:
                    continue

                ns = execution.set_node_state(
                    wn,
                    status=NodeStatus.RUNNING,
                    started_at=datetime.now(timezone.utc),
                )

                node_input = self._gather_input(meta, execution.input_data, node_outputs)
                ns.input_data = node_input

                if meta.is_human:
                    ns.status = NodeStatus.WAITING_FOR_HUMAN
                    execution_store.update_status(execution.id, ExecutionStatus.WAITING_FOR_HUMAN)
                    continue

                try:
                    result = self._run_node_with_retries(meta, node_input)
                    if not isinstance(result, dict):
                        result = {"result": result}
                    ns.output_data = result
                    ns.status = NodeStatus.COMPLETED
                    ns.completed_at = datetime.now(timezone.utc)
                    if ns.started_at:
                        delta = ns.completed_at - ns.started_at
                        ns.duration_ms = int(delta.total_seconds() * 1000)
                    node_outputs[wn] = result
                except Exception as exc:
                    ns.status = NodeStatus.FAILED
                    ns.error = str(exc)
                    execution_store.update_status(execution.id, ExecutionStatus.FAILED)
                    execution.error = str(exc)
                    return execution

        all_done = all(
            ns.status in (NodeStatus.COMPLETED, NodeStatus.SKIPPED)
            for ns in execution.node_states
        )
        if all_done:
            execution_store.update_status(execution.id, ExecutionStatus.COMPLETED)

        return execution
