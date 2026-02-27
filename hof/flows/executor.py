"""Flow DAG executor.

Orchestrates node execution respecting dependency order.  Independent nodes
within the same wave are dispatched in parallel:
  - Via Celery when a broker is reachable (production).
  - Via ThreadPoolExecutor when Celery is unavailable (development / testing).

Falls back to fully synchronous execution when neither is available.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from hof.flows.state import (
    ExecutionStatus,
    FlowExecution,
    NodeStatus,
    execution_store,
)

logger = logging.getLogger("hof.flows.executor")


def _broadcast(coro: Any) -> None:
    """Fire-and-forget: schedule an async broadcast coroutine from sync code.

    Tries to run in the running event loop (FastAPI context); if none exists
    (CLI / Celery worker), closes the coroutine to suppress ResourceWarning.
    """
    import asyncio

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        # No running event loop — close the coroutine cleanly
        coro.close()

# Maximum threads used for in-process parallel execution
_MAX_WORKERS = 8


def _normalize_result(result: Any) -> dict[str, Any]:
    """Convert a node's return value to a plain dict for downstream consumption."""
    if isinstance(result, dict):
        return result
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if hasattr(result, "__dict__"):
        return {k: v for k, v in result.__dict__.items() if not k.startswith("_")}
    return {"result": result}


def _celery_available() -> bool:
    """Return True if the Celery broker is reachable."""
    try:
        from hof.tasks.celery_app import celery

        celery.connection().ensure_connection(max_retries=1, timeout=1)
        return True
    except Exception:
        return False


class FlowExecutor:
    """Executes a flow's DAG, dispatching nodes in topological order.

    Nodes within the same wave (i.e. all their dependencies are already
    complete) are executed in parallel using threads or Celery tasks.
    """

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

        execution_store.save_execution(execution)

        try:
            self._execute(execution)
        except Exception as exc:
            execution.status = ExecutionStatus.FAILED
            execution.error = str(exc)
            execution.completed_at = datetime.now(timezone.utc)
            if execution.started_at:
                delta = execution.completed_at - execution.started_at
                execution.duration_ms = int(delta.total_seconds() * 1000)
            execution_store.save_execution(execution)
            logger.exception("Flow '%s' execution %s failed", self.flow.name, execution.id)

        return execution

    # ------------------------------------------------------------------
    # Main execution path
    # ------------------------------------------------------------------

    def _execute(self, execution: FlowExecution) -> None:
        """Execute waves sequentially; nodes within each wave run in parallel."""
        execution.status = ExecutionStatus.RUNNING
        execution_store.save_execution(execution)
        from hof.api.routes.ws import notify_execution_update
        _broadcast(notify_execution_update(execution.id, ExecutionStatus.RUNNING))

        waves = self.flow.get_execution_order()
        node_outputs: dict[str, dict] = {}

        for wave in waves:
            if execution.status == ExecutionStatus.CANCELLED:
                break

            # Check for human nodes in this wave first
            human_nodes = [n for n in wave if self.flow.nodes[n].is_human]
            non_human_nodes = [n for n in wave if not self.flow.nodes[n].is_human]

            # Run non-human nodes in parallel
            if non_human_nodes:
                wave_outputs, failed = self._run_wave_parallel(
                    non_human_nodes, execution, node_outputs
                )
                node_outputs.update(wave_outputs)
                if failed:
                    raise RuntimeError(failed)

            # Handle human nodes (pause execution)
            if human_nodes:
                node_name = human_nodes[0]
                ns = execution.set_node_state(
                    node_name,
                    status=NodeStatus.WAITING_FOR_HUMAN,
                    started_at=datetime.now(timezone.utc),
                )
                meta = self.flow.nodes[node_name]
                ns.input_data = self._gather_input(meta, execution.input_data, node_outputs)
                execution.status = ExecutionStatus.WAITING_FOR_HUMAN
                execution_store.save_execution(execution)
                logger.info(
                    "Flow '%s' execution %s waiting for human input at node '%s'",
                    self.flow.name,
                    execution.id,
                    node_name,
                )
                return

        all_completed = all(
            ns.status in (NodeStatus.COMPLETED, NodeStatus.SKIPPED)
            for ns in execution.node_states
        )
        has_waiting = any(
            ns.status == NodeStatus.WAITING_FOR_HUMAN for ns in execution.node_states
        )

        if all_completed:
            last_wave = waves[-1] if waves else []
            final_output: dict[str, Any] = {}
            for node_name in last_wave:
                final_output.update(node_outputs.get(node_name, {}))
            execution.output_data = final_output
            execution.status = ExecutionStatus.COMPLETED
            execution.completed_at = datetime.now(timezone.utc)
            if execution.started_at:
                delta = execution.completed_at - execution.started_at
                execution.duration_ms = int(delta.total_seconds() * 1000)
        elif has_waiting:
            execution.status = ExecutionStatus.WAITING_FOR_HUMAN

        execution_store.save_execution(execution)
        from hof.api.routes.ws import notify_execution_update
        _broadcast(notify_execution_update(execution.id, execution.status))

    # ------------------------------------------------------------------
    # Parallel wave execution
    # ------------------------------------------------------------------

    def _run_wave_parallel(
        self,
        node_names: list[str],
        execution: FlowExecution,
        node_outputs: dict[str, dict],
    ) -> tuple[dict[str, dict], str | None]:
        """Run a set of nodes in parallel using threads.

        Returns (outputs_dict, error_message_or_None).
        """
        if len(node_names) == 1:
            # Single node — no overhead of thread pool
            name = node_names[0]
            try:
                output = self._run_single_node(name, execution, node_outputs)
                return {name: output}, None
            except Exception as exc:
                return {}, str(exc)

        results: dict[str, dict] = {}
        first_error: str | None = None

        with ThreadPoolExecutor(max_workers=min(len(node_names), _MAX_WORKERS)) as pool:
            future_to_name: dict[Future, str] = {
                pool.submit(self._run_single_node, name, execution, node_outputs): name
                for name in node_names
            }

            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    results[name] = future.result()
                except Exception as exc:
                    first_error = first_error or str(exc)

        return results, first_error

    def _run_single_node(
        self,
        node_name: str,
        execution: FlowExecution,
        node_outputs: dict[str, dict],
    ) -> dict[str, Any]:
        """Execute one node, update its state, and return its output dict."""
        meta = self.flow.nodes[node_name]
        ns = execution.set_node_state(
            node_name,
            status=NodeStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )

        node_input = self._gather_input(meta, execution.input_data, node_outputs)
        ns.input_data = node_input

        try:
            result = self._run_node_with_retries(meta, node_input)
            result = _normalize_result(result)

            ns.output_data = result
            ns.status = NodeStatus.COMPLETED
            ns.completed_at = datetime.now(timezone.utc)
            if ns.started_at:
                delta = ns.completed_at - ns.started_at
                ns.duration_ms = int(delta.total_seconds() * 1000)

            execution_store.save_execution(execution)
            logger.info("Node '%s' completed in %dms", node_name, ns.duration_ms or 0)
            from hof.api.routes.ws import notify_node_update
            _broadcast(notify_node_update(execution.id, node_name, NodeStatus.COMPLETED))
            return result

        except Exception as exc:
            ns.status = NodeStatus.FAILED
            ns.error = str(exc)
            ns.completed_at = datetime.now(timezone.utc)
            execution_store.save_execution(execution)
            from hof.api.routes.ws import notify_node_update
            _broadcast(notify_node_update(execution.id, node_name, NodeStatus.FAILED, error=str(exc)))
            raise

    # ------------------------------------------------------------------
    # Input gathering
    # ------------------------------------------------------------------

    def _gather_input(
        self,
        meta: Any,
        flow_input: dict[str, Any],
        node_outputs: dict[str, dict],
    ) -> dict[str, Any]:
        """Build the input for a node by merging flow input and all ancestor outputs."""
        if not meta.depends_on:
            return dict(flow_input)

        ancestors = self._get_ancestors(meta.name)
        merged: dict[str, Any] = dict(flow_input)
        for anc in ancestors:
            merged.update(node_outputs.get(anc, {}))
        return merged

    def _get_ancestors(self, node_name: str) -> list[str]:
        """Return all ancestors of a node in topological order (oldest first)."""
        visited: set[str] = set()
        order: list[str] = []

        def walk(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            meta = self.flow.nodes.get(name)
            if meta:
                for dep in meta.depends_on:
                    walk(dep)
            order.append(name)

        meta = self.flow.nodes[node_name]
        for dep in meta.depends_on:
            walk(dep)

        return order

    # ------------------------------------------------------------------
    # Retry logic
    # ------------------------------------------------------------------

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
                    meta.name,
                    attempt + 1,
                    meta.retries + 1,
                    exc,
                )
                if attempt < meta.retries:
                    time.sleep(meta.retry_delay)

        raise last_error  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Human-in-the-loop resume
    # ------------------------------------------------------------------

    def resume_after_human(
        self, execution_id: str, node_name: str, human_output: dict
    ) -> FlowExecution | None:
        """Resume a flow after human input is submitted."""
        execution = execution_store.get_execution(execution_id)
        if execution is None:
            return None

        submitted = execution_store.submit_human_input(execution_id, node_name, human_output)
        if not submitted:
            return None

        execution = execution_store.get_execution(execution_id)
        if execution is None:
            return None

        node_outputs: dict[str, dict] = {}
        for ns in execution.node_states:
            if ns.status == NodeStatus.COMPLETED:
                node_outputs[ns.node_name] = ns.output_data

        node_outputs[node_name] = human_output

        execution.status = ExecutionStatus.RUNNING
        execution_store.save_execution(execution)

        waves = self.flow.get_execution_order()
        found_human_wave = False

        for wave in waves:
            if node_name in wave:
                found_human_wave = True
                continue
            if not found_human_wave:
                continue

            non_human = [n for n in wave if not self.flow.nodes[n].is_human]
            human_in_wave = [n for n in wave if self.flow.nodes[n].is_human]

            if non_human:
                wave_outputs, error = self._run_wave_parallel(non_human, execution, node_outputs)
                node_outputs.update(wave_outputs)
                if error:
                    execution.status = ExecutionStatus.FAILED
                    execution.error = error
                    execution_store.save_execution(execution)
                    return execution

            if human_in_wave:
                next_human = human_in_wave[0]
                ns = execution.set_node_state(
                    next_human,
                    status=NodeStatus.WAITING_FOR_HUMAN,
                    started_at=datetime.now(timezone.utc),
                )
                meta = self.flow.nodes[next_human]
                ns.input_data = self._gather_input(meta, execution.input_data, node_outputs)
                execution.status = ExecutionStatus.WAITING_FOR_HUMAN
                execution_store.save_execution(execution)
                return execution

        all_done = all(
            ns.status in (NodeStatus.COMPLETED, NodeStatus.SKIPPED)
            for ns in execution.node_states
        )
        if all_done:
            execution.status = ExecutionStatus.COMPLETED
            execution.completed_at = datetime.now(timezone.utc)
            if execution.started_at:
                delta = execution.completed_at - execution.started_at
                execution.duration_ms = int(delta.total_seconds() * 1000)

        execution_store.save_execution(execution)
        return execution
