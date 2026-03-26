"""Versioned JSON shape for persisting Hof agent UI state (thread + outcomes + draft).

Apps store this document in their own DB (e.g. JSONB column). Validate on save with
``validate_conversation_state`` and normalize with ``normalize_conversation_state_for_storage``.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_CONVERSATION_STATE_BYTES = 2_000_000  # ~2 MiB


class AgentConversationDraftV1(BaseModel):
    """In-progress stream + mutation gate (optional)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    live_blocks: list[Any] = Field(default_factory=list, alias="liveBlocks")
    approval_barrier: dict[str, Any] | None = Field(default=None, alias="approvalBarrier")
    approval_decisions: dict[str, bool | None] = Field(
        default_factory=dict,
        alias="approvalDecisions",
    )


class AgentConversationPlanV1(BaseModel):
    """Plan-mode state persisted alongside the conversation."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    phase: str | None = None
    text: str = ""
    run_id: str | None = Field(default=None, alias="runId")
    clarification_barrier: dict[str, Any] | None = Field(
        default=None,
        alias="clarificationBarrier",
    )
    plan_todo_done_indices: list[int] = Field(
        default_factory=list,
        alias="planTodoDoneIndices",
    )


class AgentConversationStateV1(BaseModel):
    """Full assistant transcript for one conversation."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    version: int = 1
    thread: list[Any] = Field(default_factory=list)
    mutation_outcomes: dict[str, bool] = Field(default_factory=dict, alias="mutationOutcomes")
    draft: AgentConversationDraftV1 | None = None
    plan: AgentConversationPlanV1 | None = None

    @field_validator("version")
    @classmethod
    def _version_supported(cls, v: int) -> int:
        if v != 1:
            msg = f"unsupported conversation state version: {v}"
            raise ValueError(msg)
        return v


def validate_conversation_state(raw: dict[str, Any]) -> AgentConversationStateV1:
    """Parse and validate client-supplied state."""
    return AgentConversationStateV1.model_validate(raw)


def normalize_conversation_state_for_storage(model: AgentConversationStateV1) -> dict[str, Any]:
    """JSON-serializable dict using camelCase aliases (matches TS ``AgentConversationStateV1``)."""
    return model.model_dump(mode="json", by_alias=True)


def conversation_state_json_size(raw: dict[str, Any]) -> int:
    return len(json.dumps(raw, default=str, ensure_ascii=False).encode("utf-8"))


def enforce_max_conversation_state_bytes(raw: dict[str, Any]) -> None:
    n = conversation_state_json_size(raw)
    if n > MAX_CONVERSATION_STATE_BYTES:
        msg = f"conversation state too large ({n} bytes; max {MAX_CONVERSATION_STATE_BYTES})"
        raise ValueError(msg)
