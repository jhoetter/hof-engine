"""Flow execution state management.

Tracks the status of flow executions and individual node runs.
Persisted to PostgreSQL via SQLAlchemy for durability and cross-process visibility.
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
    """Database-backed execution store.

    All mutations are immediately persisted to PostgreSQL so that the API
    server, CLI, Celery workers, and admin dashboard share the same state.
    """

    def _row_to_execution(self, row: Any) -> FlowExecution:
        """Convert a FlowExecutionRow ORM object to a FlowExecution dataclass."""
        node_states = [
            NodeState(
                node_name=ns.node_name,
                status=ns.status,
                input_data=ns.input_data or {},
                output_data=ns.output_data or {},
                error=ns.error,
                started_at=ns.started_at,
                completed_at=ns.completed_at,
                duration_ms=ns.duration_ms,
                retries_used=ns.retries_used,
            )
            for ns in row.node_states
        ]
        return FlowExecution(
            id=row.id,
            flow_name=row.flow_name,
            status=row.status,
            input_data=row.input_data or {},
            output_data=row.output_data or {},
            node_states=node_states,
            flow_snapshot=row.flow_snapshot or {},
            started_at=row.started_at,
            completed_at=row.completed_at,
            duration_ms=row.duration_ms,
            error=row.error,
        )

    def create_execution(self, flow_name: str, input_data: dict, flow_snapshot: dict) -> FlowExecution:
        from hof.db.engine import get_session
        from hof.flows.models import FlowExecutionRow

        row = FlowExecutionRow(
            flow_name=flow_name,
            input_data=input_data,
            flow_snapshot=flow_snapshot,
            status=ExecutionStatus.PENDING,
            started_at=datetime.now(timezone.utc),
        )
        with get_session() as session:
            session.add(row)
            session.flush()
            session.refresh(row)
            return self._row_to_execution(row)

    def get_execution(self, execution_id: str) -> FlowExecution | None:
        from hof.db.engine import get_session
        from hof.flows.models import FlowExecutionRow

        with get_session() as session:
            row = session.get(FlowExecutionRow, execution_id)
            if row is None:
                return None
            return self._row_to_execution(row)

    def save_execution(self, execution: FlowExecution) -> None:
        """Persist the full in-memory execution state back to the database."""
        from hof.db.engine import get_session
        from hof.flows.models import FlowExecutionRow, NodeStateRow

        with get_session() as session:
            row = session.get(FlowExecutionRow, execution.id)
            if row is None:
                return

            row.status = execution.status
            row.input_data = execution.input_data
            row.output_data = execution.output_data
            row.error = execution.error
            row.started_at = execution.started_at
            row.completed_at = execution.completed_at
            row.duration_ms = execution.duration_ms

            existing_nodes = {ns.node_name: ns for ns in row.node_states}
            for ns in execution.node_states:
                if ns.node_name in existing_nodes:
                    db_ns = existing_nodes[ns.node_name]
                    db_ns.status = ns.status
                    db_ns.input_data = ns.input_data
                    db_ns.output_data = ns.output_data
                    db_ns.error = ns.error
                    db_ns.started_at = ns.started_at
                    db_ns.completed_at = ns.completed_at
                    db_ns.duration_ms = ns.duration_ms
                    db_ns.retries_used = ns.retries_used
                else:
                    row.node_states.append(NodeStateRow(
                        node_name=ns.node_name,
                        status=ns.status,
                        input_data=ns.input_data,
                        output_data=ns.output_data,
                        error=ns.error,
                        started_at=ns.started_at,
                        completed_at=ns.completed_at,
                        duration_ms=ns.duration_ms,
                        retries_used=ns.retries_used,
                    ))

    def update_execution(self, execution_id: str, **updates: Any) -> FlowExecution | None:
        from hof.db.engine import get_session
        from hof.flows.models import FlowExecutionRow

        with get_session() as session:
            row = session.get(FlowExecutionRow, execution_id)
            if row is None:
                return None
            for key, value in updates.items():
                setattr(row, key, value)
            session.flush()
            session.refresh(row)
            return self._row_to_execution(row)

    def update_status(self, execution_id: str, status: str) -> None:
        from hof.db.engine import get_session
        from hof.flows.models import FlowExecutionRow

        with get_session() as session:
            row = session.get(FlowExecutionRow, execution_id)
            if row is None:
                return
            row.status = status
            if status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED):
                row.completed_at = datetime.now(timezone.utc)
                if row.started_at:
                    delta = row.completed_at - row.started_at
                    row.duration_ms = int(delta.total_seconds() * 1000)

    def list_executions(
        self,
        *,
        flow_name: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[FlowExecution]:
        import sqlalchemy as sa
        from hof.db.engine import get_session
        from hof.flows.models import FlowExecutionRow

        with get_session() as session:
            stmt = sa.select(FlowExecutionRow)
            if flow_name:
                stmt = stmt.where(FlowExecutionRow.flow_name == flow_name)
            if status:
                stmt = stmt.where(FlowExecutionRow.status == status)
            stmt = stmt.order_by(FlowExecutionRow.started_at.desc()).limit(limit)
            rows = session.scalars(stmt).unique().all()
            return [self._row_to_execution(r) for r in rows]

    def submit_human_input(self, execution_id: str, node_name: str, data: dict) -> bool:
        """Submit human input for a waiting node."""
        from hof.db.engine import get_session
        from hof.flows.models import FlowExecutionRow

        with get_session() as session:
            row = session.get(FlowExecutionRow, execution_id)
            if row is None:
                return False

            for ns in row.node_states:
                if ns.node_name == node_name and ns.status == NodeStatus.WAITING_FOR_HUMAN:
                    ns.output_data = data
                    ns.status = NodeStatus.COMPLETED
                    ns.completed_at = datetime.now(timezone.utc)
                    if ns.started_at:
                        delta = ns.completed_at - ns.started_at
                        ns.duration_ms = int(delta.total_seconds() * 1000)
                    return True

            return False


execution_store = ExecutionStore()
