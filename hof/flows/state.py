"""Flow execution state management.

Tracks the status of flow executions and individual node runs. Persists to
the database for durability and queryability.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_HUMAN = "waiting_for_human"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_HUMAN = "waiting_for_human"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class NodeState:
    """State of a single node within an execution."""

    node_name: str
    status: str = NodeStatus.PENDING
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    retries_used: int = 0

    def to_dict(self) -> dict:
        return {
            "node_name": self.node_name,
            "status": self.status,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
            "retries_used": self.retries_used,
        }


@dataclass
class FlowExecution:
    """State of a complete flow execution."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    flow_name: str = ""
    status: str = ExecutionStatus.PENDING
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    node_states: list[NodeState] = field(default_factory=list)
    flow_snapshot: dict[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    error: str | None = None

    def get_node_state(self, node_name: str) -> NodeState | None:
        for ns in self.node_states:
            if ns.node_name == node_name:
                return ns
        return None

    def set_node_state(self, node_name: str, **updates: Any) -> NodeState:
        ns = self.get_node_state(node_name)
        if ns is None:
            ns = NodeState(node_name=node_name)
            self.node_states.append(ns)
        for key, value in updates.items():
            setattr(ns, key, value)
        return ns

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "flow_name": self.flow_name,
            "status": self.status,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "node_states": [ns.to_dict() for ns in self.node_states],
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


class ExecutionStore:
    """In-memory execution store (will be backed by PostgreSQL in production).

    This provides the interface that the executor and API use. The in-memory
    implementation is suitable for development; the DB-backed implementation
    shares the same interface.
    """

    _executions: dict[str, FlowExecution] = {}

    def create_execution(self, flow_name: str, input_data: dict, flow_snapshot: dict) -> FlowExecution:
        execution = FlowExecution(
            flow_name=flow_name,
            input_data=input_data,
            flow_snapshot=flow_snapshot,
            started_at=datetime.now(timezone.utc),
        )
        self._executions[execution.id] = execution
        return execution

    def get_execution(self, execution_id: str) -> FlowExecution | None:
        return self._executions.get(execution_id)

    def update_execution(self, execution_id: str, **updates: Any) -> FlowExecution | None:
        execution = self._executions.get(execution_id)
        if execution is None:
            return None
        for key, value in updates.items():
            setattr(execution, key, value)
        return execution

    def update_status(self, execution_id: str, status: str) -> None:
        execution = self._executions.get(execution_id)
        if execution:
            execution.status = status
            if status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED):
                execution.completed_at = datetime.now(timezone.utc)
                if execution.started_at:
                    delta = execution.completed_at - execution.started_at
                    execution.duration_ms = int(delta.total_seconds() * 1000)

    def list_executions(
        self,
        *,
        flow_name: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[FlowExecution]:
        results = list(self._executions.values())
        if flow_name:
            results = [e for e in results if e.flow_name == flow_name]
        if status:
            results = [e for e in results if e.status == status]
        results.sort(key=lambda e: e.started_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return results[:limit]

    def submit_human_input(self, execution_id: str, node_name: str, data: dict) -> bool:
        """Submit human input for a waiting node."""
        execution = self._executions.get(execution_id)
        if execution is None:
            return False

        ns = execution.get_node_state(node_name)
        if ns is None or ns.status != NodeStatus.WAITING_FOR_HUMAN:
            return False

        ns.output_data = data
        ns.status = NodeStatus.COMPLETED
        ns.completed_at = datetime.now(timezone.utc)
        if ns.started_at:
            delta = ns.completed_at - ns.started_at
            ns.duration_ms = int(delta.total_seconds() * 1000)

        return True


execution_store = ExecutionStore()
