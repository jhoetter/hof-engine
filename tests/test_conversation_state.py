"""Tests for persisted agent conversation JSON schema (``hof.agent.conversation_state``)."""

from __future__ import annotations

import pytest

from hof.agent import (
    MAX_CONVERSATION_STATE_BYTES,
    enforce_max_conversation_state_bytes,
    normalize_conversation_state_for_storage,
    validate_conversation_state,
)


def test_validate_minimal_round_trip() -> None:
    raw = {"version": 1, "thread": [], "mutationOutcomes": {}}
    model = validate_conversation_state(raw)
    stored = normalize_conversation_state_for_storage(model)
    assert stored["version"] == 1
    assert stored["thread"] == []
    assert stored["mutationOutcomes"] == {}


def test_validate_accepts_camel_case_alias() -> None:
    raw = {
        "version": 1,
        "thread": [{"kind": "user", "id": "1", "content": "hi"}],
        "mutationOutcomes": {"p1": True},
    }
    model = validate_conversation_state(raw)
    assert model.thread == raw["thread"]
    assert model.mutation_outcomes == {"p1": True}


def test_validate_rejects_bad_version() -> None:
    with pytest.raises(ValueError, match="unsupported conversation state version"):
        validate_conversation_state(
            {"version": 2, "thread": [], "mutationOutcomes": {}}
        )


def test_enforce_max_bytes() -> None:
    big = {"x": "a" * (MAX_CONVERSATION_STATE_BYTES + 10)}
    with pytest.raises(ValueError, match="conversation state too large"):
        enforce_max_conversation_state_bytes(big)
