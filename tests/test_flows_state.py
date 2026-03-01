"""Tests for hof.flows.state — dataclass layer (no DB required)."""

from __future__ import annotations

from datetime import UTC, datetime

from hof.flows.state import (
    ExecutionStatus,
    FlowExecution,
    NodeState,
    NodeStatus,
)


class TestNodeState:
    def test_default_values(self):
        ns = NodeState(node_name="my_node")
        assert ns.status == NodeStatus.PENDING
        assert ns.input_data == {}
        assert ns.output_data == {}
        assert ns.error is None
        assert ns.started_at is None
        assert ns.completed_at is None
        assert ns.duration_ms is None
        assert ns.retries_used == 0

    def test_to_dict(self):
        now = datetime.now(UTC)
        ns = NodeState(
            node_name="test_node",
            status=NodeStatus.COMPLETED,
            input_data={"x": 1},
            output_data={"y": 2},
            started_at=now,
            completed_at=now,
            duration_ms=100,
        )
        d = ns.to_dict()
        assert d["node_name"] == "test_node"
        assert d["status"] == NodeStatus.COMPLETED
        assert d["input_data"] == {"x": 1}
        assert d["output_data"] == {"y": 2}
        assert d["duration_ms"] == 100
        assert d["started_at"] is not None
        assert d["completed_at"] is not None

    def test_to_dict_none_datetimes(self):
        ns = NodeState(node_name="n")
        d = ns.to_dict()
        assert d["started_at"] is None
        assert d["completed_at"] is None


class TestFlowExecution:
    def test_default_values(self):
        ex = FlowExecution()
        assert ex.status == ExecutionStatus.PENDING
        assert ex.input_data == {}
        assert ex.output_data == {}
        assert ex.node_states == []
        assert ex.error is None
        assert ex.id  # auto-generated UUID

    def test_auto_id_is_unique(self):
        ex1 = FlowExecution()
        ex2 = FlowExecution()
        assert ex1.id != ex2.id

    def test_set_node_state_creates_new(self):
        ex = FlowExecution()
        ns = ex.set_node_state("node_a", status=NodeStatus.RUNNING)
        assert ns.node_name == "node_a"
        assert ns.status == NodeStatus.RUNNING
        assert len(ex.node_states) == 1

    def test_set_node_state_updates_existing(self):
        ex = FlowExecution()
        ex.set_node_state("node_a", status=NodeStatus.RUNNING)
        ex.set_node_state("node_a", status=NodeStatus.COMPLETED, output_data={"r": 1})
        assert len(ex.node_states) == 1
        ns = ex.get_node_state("node_a")
        assert ns.status == NodeStatus.COMPLETED
        assert ns.output_data == {"r": 1}

    def test_get_node_state_returns_none_for_missing(self):
        ex = FlowExecution()
        assert ex.get_node_state("nonexistent") is None

    def test_get_node_state_returns_correct_node(self):
        ex = FlowExecution()
        ex.set_node_state("node_a", status=NodeStatus.RUNNING)
        ex.set_node_state("node_b", status=NodeStatus.COMPLETED)
        ns = ex.get_node_state("node_b")
        assert ns.status == NodeStatus.COMPLETED

    def test_to_dict_structure(self):
        ex = FlowExecution(
            id="test-id",
            flow_name="my_flow",
            status=ExecutionStatus.RUNNING,
            input_data={"x": 1},
        )
        ex.set_node_state("step_a", status=NodeStatus.COMPLETED)
        d = ex.to_dict()
        assert d["id"] == "test-id"
        assert d["flow_name"] == "my_flow"
        assert d["status"] == ExecutionStatus.RUNNING
        assert d["input_data"] == {"x": 1}
        assert len(d["node_states"]) == 1
        assert d["node_states"][0]["node_name"] == "step_a"

    def test_to_dict_with_datetimes(self):
        now = datetime.now(UTC)
        ex = FlowExecution(started_at=now, completed_at=now, duration_ms=500)
        d = ex.to_dict()
        assert d["started_at"] is not None
        assert d["completed_at"] is not None
        assert d["duration_ms"] == 500

    def test_to_dict_none_datetimes(self):
        ex = FlowExecution()
        d = ex.to_dict()
        assert d["started_at"] is None
        assert d["completed_at"] is None


class TestExecutionStatusEnum:
    def test_all_statuses_exist(self):
        assert ExecutionStatus.PENDING == "pending"
        assert ExecutionStatus.RUNNING == "running"
        assert ExecutionStatus.WAITING_FOR_HUMAN == "waiting_for_human"
        assert ExecutionStatus.COMPLETED == "completed"
        assert ExecutionStatus.FAILED == "failed"
        assert ExecutionStatus.CANCELLED == "cancelled"


class TestNodeStatusEnum:
    def test_all_statuses_exist(self):
        assert NodeStatus.PENDING == "pending"
        assert NodeStatus.RUNNING == "running"
        assert NodeStatus.WAITING_FOR_HUMAN == "waiting_for_human"
        assert NodeStatus.COMPLETED == "completed"
        assert NodeStatus.FAILED == "failed"
        assert NodeStatus.SKIPPED == "skipped"
