"""SQLAlchemy models for persisting flow execution state."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hof.db.engine import Base


class FlowExecutionRow(Base):
    __tablename__ = "hof_flow_executions"

    id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    flow_name: Mapped[str] = mapped_column(sa.String(255), index=True)
    status: Mapped[str] = mapped_column(sa.String(50), index=True, default="pending")
    input_data: Mapped[dict] = mapped_column(postgresql.JSONB, default=dict)
    output_data: Mapped[dict] = mapped_column(postgresql.JSONB, default=dict)
    flow_snapshot: Mapped[dict] = mapped_column(postgresql.JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    node_states: Mapped[list[NodeStateRow]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="NodeStateRow.created_at",
    )


class NodeStateRow(Base):
    __tablename__ = "hof_node_states"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    execution_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("hof_flow_executions.id", ondelete="CASCADE"),
        index=True,
    )
    node_name: Mapped[str] = mapped_column(sa.String(255))
    status: Mapped[str] = mapped_column(sa.String(50), default="pending")
    input_data: Mapped[dict] = mapped_column(postgresql.JSONB, default=dict)
    output_data: Mapped[dict] = mapped_column(postgresql.JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    retries_used: Mapped[int] = mapped_column(sa.Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    execution: Mapped[FlowExecutionRow] = relationship(back_populates="node_states")
