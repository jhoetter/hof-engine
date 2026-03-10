"""Tests for hof.flows.executor."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hof.flows.executor import FlowExecutor, _normalize_result
from hof.flows.flow import Flow
from hof.flows.state import (
    ExecutionStatus,
    FlowExecution,
    NodeStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_execution(flow_name: str = "test_flow", input_data: dict | None = None) -> FlowExecution:
    ex = FlowExecution(
        id="exec-001",
        flow_name=flow_name,
        status=ExecutionStatus.PENDING,
        input_data=input_data or {},
    )
    return ex


def _patch_store(execution: FlowExecution):
    """Return a context manager that patches execution_store with a mock."""
    store = MagicMock()
    store.create_execution.return_value = execution
    store.get_execution.return_value = execution
    store.save_execution.return_value = None
    store.submit_human_input.return_value = True
    return patch("hof.flows.executor.execution_store", store), store


# ---------------------------------------------------------------------------
# _normalize_result
# ---------------------------------------------------------------------------


class TestNormalizeResult:
    def test_dict_passthrough(self):
        assert _normalize_result({"a": 1}) == {"a": 1}

    def test_pydantic_model(self):
        from pydantic import BaseModel

        class MyModel(BaseModel):
            x: int
            y: str

        result = _normalize_result(MyModel(x=1, y="hello"))
        assert result == {"x": 1, "y": "hello"}

    def test_object_with_dict(self):
        class Obj:
            def __init__(self):
                self.a = 1
                self.b = 2
                self._private = "skip"

        result = _normalize_result(Obj())
        assert result == {"a": 1, "b": 2}

    def test_scalar_wrapped(self):
        assert _normalize_result(42) == {"result": 42}
        assert _normalize_result("hello") == {"result": "hello"}
        assert _normalize_result(None) == {"result": None}

    def test_list_wrapped(self):
        result = _normalize_result([1, 2, 3])
        assert result == {"result": [1, 2, 3]}


# ---------------------------------------------------------------------------
# FlowExecutor.start
# ---------------------------------------------------------------------------


class TestFlowExecutorStart:
    def test_simple_linear_flow(self, simple_flow):
        execution = _make_execution("test_simple_flow", {"x": 5})
        ctx, store = _patch_store(execution)

        with ctx:
            executor = FlowExecutor(simple_flow)
            result = executor.start({"x": 5})

        assert result.status == ExecutionStatus.COMPLETED
        assert result.output_data.get("final") is not None

    def test_invalid_flow_raises(self):
        flow = Flow("invalid_flow")
        # No nodes — validation will fail
        execution = _make_execution("invalid_flow")
        ctx, store = _patch_store(execution)

        with ctx:
            executor = FlowExecutor(flow)
            with pytest.raises(ValueError, match="Invalid flow"):
                executor.start({})

    def test_node_failure_marks_execution_failed(self, simple_flow):
        execution = _make_execution("test_simple_flow", {"x": 5})
        ctx, store = _patch_store(execution)

        # Patch step_a to raise
        original_fn = simple_flow.nodes["step_a"].fn
        simple_flow.nodes["step_a"].fn = MagicMock(side_effect=RuntimeError("node error"))

        with ctx:
            executor = FlowExecutor(simple_flow)
            result = executor.start({"x": 5})

        assert result.status == ExecutionStatus.FAILED
        assert "node error" in (result.error or "")

        # Restore
        simple_flow.nodes["step_a"].fn = original_fn

    def test_branching_flow_completes(self, branching_flow):
        execution = _make_execution("test_branching_flow", {"value": 10})
        ctx, store = _patch_store(execution)

        with ctx:
            executor = FlowExecutor(branching_flow)
            result = executor.start({"value": 10})

        assert result.status == ExecutionStatus.COMPLETED
        # merge node: a=20, b=30 → merged=50
        assert result.output_data.get("merged") == 50

    def test_human_node_pauses_execution(self):
        flow = Flow("human_flow")

        @flow.node
        def before_human(x: int) -> dict:
            return {"x": x}

        @flow.node(depends_on=[before_human])
        def human_review(x: int) -> dict:
            return {"approved": True}

        # Mark as human node
        flow.nodes["human_review"].is_human = True

        @flow.node(depends_on=[human_review])
        def after_human(approved: bool) -> dict:
            return {"done": approved}

        execution = _make_execution("human_flow", {"x": 1})
        ctx, store = _patch_store(execution)

        with ctx:
            executor = FlowExecutor(flow)
            result = executor.start({"x": 1})

        assert result.status == ExecutionStatus.WAITING_FOR_HUMAN


class TestFlowExecutorRetries:
    def test_retry_on_failure(self):
        call_count = 0

        flow = Flow("retry_flow")

        @flow.node(retries=2, retry_delay=0)
        def flaky_step(x: int) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("transient error")
            return {"x": x}

        execution = _make_execution("retry_flow", {"x": 1})
        ctx, store = _patch_store(execution)

        with ctx:
            executor = FlowExecutor(flow)
            result = executor.start({"x": 1})

        assert call_count == 3
        assert result.status == ExecutionStatus.COMPLETED

    def test_exhausted_retries_fails(self):
        flow = Flow("always_fail_flow")

        @flow.node(retries=1, retry_delay=0)
        def always_fails(x: int) -> dict:
            raise RuntimeError("always fails")

        execution = _make_execution("always_fail_flow", {"x": 1})
        ctx, store = _patch_store(execution)

        with ctx:
            executor = FlowExecutor(flow)
            result = executor.start({"x": 1})

        assert result.status == ExecutionStatus.FAILED


class TestFlowExecutorGatherInput:
    def test_entry_node_gets_flow_input(self, simple_flow):
        execution = _make_execution("test_simple_flow", {"x": 42})
        ctx, store = _patch_store(execution)

        captured_inputs = {}
        original_fn = simple_flow.nodes["step_a"].fn

        def capturing_fn(**kwargs):
            captured_inputs.update(kwargs)
            return original_fn(**kwargs)

        simple_flow.nodes["step_a"].fn = capturing_fn

        with ctx:
            executor = FlowExecutor(simple_flow)
            executor.start({"x": 42})

        assert captured_inputs.get("x") == 42
        simple_flow.nodes["step_a"].fn = original_fn

    def test_downstream_node_gets_ancestor_output(self, simple_flow):
        execution = _make_execution("test_simple_flow", {"x": 5})
        ctx, store = _patch_store(execution)

        captured_inputs = {}
        original_fn = simple_flow.nodes["step_b"].fn

        def capturing_fn(**kwargs):
            captured_inputs.update(kwargs)
            return original_fn(**kwargs)

        simple_flow.nodes["step_b"].fn = capturing_fn

        with ctx:
            executor = FlowExecutor(simple_flow)
            executor.start({"x": 5})

        # step_a returns {"a_result": 10}, step_b should receive a_result=10
        assert captured_inputs.get("a_result") == 10
        simple_flow.nodes["step_b"].fn = original_fn


class TestFlowExecutorResume:
    def test_resume_after_human_completes_flow(self):
        flow = Flow("resume_flow")

        @flow.node
        def step_a(x: int) -> dict:
            return {"x": x}

        @flow.node(depends_on=[step_a])
        def human_step(x: int) -> dict:
            return {"approved": True}

        flow.nodes["human_step"].is_human = True

        @flow.node(depends_on=[human_step])
        def step_c(approved: bool) -> dict:
            return {"done": approved}

        # Simulate a paused execution with step_a completed, human_step waiting
        execution = _make_execution("resume_flow", {"x": 1})
        execution.status = ExecutionStatus.WAITING_FOR_HUMAN
        execution.set_node_state("step_a", status=NodeStatus.COMPLETED, output_data={"x": 1})
        execution.set_node_state("human_step", status=NodeStatus.WAITING_FOR_HUMAN)
        execution.set_node_state("step_c", status=NodeStatus.PENDING)

        store = MagicMock()
        store.get_execution.return_value = execution
        store.submit_human_input.return_value = True
        store.save_execution.return_value = None

        with patch("hof.flows.executor.execution_store", store):
            executor = FlowExecutor(flow)
            result = executor.resume_after_human("exec-001", "human_step", {"approved": True})

        assert result is not None
        # After resume, step_c should be completed and the flow should be done
        step_c_state = result.get_node_state("step_c")
        assert step_c_state is not None
        assert step_c_state.status == NodeStatus.COMPLETED

    def test_resume_returns_none_for_missing_execution(self):
        flow = Flow("resume_flow_2")

        @flow.node
        def step() -> dict:
            return {}

        store = MagicMock()
        store.get_execution.return_value = None

        with patch("hof.flows.executor.execution_store", store):
            executor = FlowExecutor(flow)
            result = executor.resume_after_human("bad-id", "step", {})

        assert result is None
