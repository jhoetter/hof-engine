"""Tests for ``AgentPolicy.tool_pre_call_validators`` (pre-dispatch refusal hook).

These guards exist for routing decisions that the system prompt + tool
descriptions cannot reliably enforce — e.g. blocking
``hof_builtin_browse_web`` for office-document tasks. The contract is:

1. Validator returns ``None`` → call dispatches normally.
2. Validator returns a non-empty string → call is refused. The stream emits
   a ``tool_result`` event with ``ok=False, status_code=400`` and a ``data``
   payload of ``{"error": "tool_call_refused", "message": <reason>, ...}``,
   plus a matching ``role=tool`` message into ``oa_messages`` so the LLM
   sees the refusal on its next turn and re-routes.
3. The underlying tool is **not** invoked.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from typing import Any
from unittest.mock import patch

from llm_markdown.agent_stream import (
    AgentMessageFinish,
    AgentToolCallDelta,
)

from hof.agent.policy import (
    AgentPolicy,
    configure_agent,
)
from hof.agent.stream import iter_agent_chat_stream


def _refuse_office_browse(args: Mapping[str, Any]) -> str | None:
    task = str(args.get("task") or "").lower()
    if "docx" in task or "lorem ipsum" in task:
        return (
            "Refused: this task is an Office document creation/edit. "
            "Call dispatch_office_agent instead."
        )
    return None


def test_validator_refuses_call_and_surfaces_error_to_model(monkeypatch) -> None:
    """A validator that returns a string aborts dispatch and feeds the
    refusal back to the LLM as a tool error result."""
    importlib.reload(importlib.import_module("hof.agent.builtin_tools"))

    from hof.functions import function as hof_function
    from hof.functions import registry

    if registry.get_function("noop_read") is None:

        @hof_function(name="noop_read", tool_summary="No-op read")
        def _noop_read() -> dict:
            return {"ok": True}

    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset({"noop_read"}),
            allowlist_mutation=frozenset(),
            system_prompt_intro="test ",
            confirmation_summary_mode="none",
            tool_pre_call_validators={"noop_read": [_refuse_office_browse]},
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AGENT_REASONING_MODE", raising=False)

    def fake_stream(*_a, **_kw):
        yield AgentToolCallDelta(
            index=0,
            tool_call_id="call_r",
            name="noop_read",
            arguments=json.dumps({"task": "create lorem ipsum docx"}),
        )
        yield AgentMessageFinish(finish_reason="tool_calls", usage=None)

    def fake_stream_followup(*_a, **_kw):
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    side_effects = [fake_stream(), fake_stream_followup()]

    with patch(
        "hof.agent.stream.stream_agent_turn",
        side_effect=lambda *a, **kw: side_effects.pop(0),
    ):
        events = list(
            iter_agent_chat_stream([{"role": "user", "content": "run"}], None),
        )

    tool_results = [e for e in events if e.get("type") == "tool_result"]
    assert tool_results, "expected a tool_result event for the refused call"
    refusal = tool_results[0]
    assert refusal["name"] == "noop_read"
    assert refusal["tool_call_id"] == "call_r"
    assert refusal["ok"] is False
    assert refusal["status_code"] == 400
    data = refusal.get("data")
    assert isinstance(data, dict)
    assert data.get("error") == "tool_call_refused"
    assert "Office document" in (data.get("message") or "")

    assert all(
        e.get("type") != "tool_call_dispatch" for e in events
    ), "underlying tool must not have dispatched"

    assert any(e.get("type") == "run_start" for e in events)


def test_validator_returning_none_allows_dispatch(monkeypatch) -> None:
    """A validator that returns ``None`` does not interfere with the call."""
    importlib.reload(importlib.import_module("hof.agent.builtin_tools"))

    from hof.functions import function as hof_function
    from hof.functions import registry

    if registry.get_function("noop_read") is None:

        @hof_function(name="noop_read", tool_summary="No-op read")
        def _noop_read() -> dict:
            return {"ok": True}

    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset({"noop_read"}),
            allowlist_mutation=frozenset(),
            system_prompt_intro="test ",
            confirmation_summary_mode="none",
            tool_pre_call_validators={"noop_read": [_refuse_office_browse]},
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AGENT_REASONING_MODE", raising=False)

    def fake_stream(*_a, **_kw):
        yield AgentToolCallDelta(
            index=0,
            tool_call_id="call_a",
            name="noop_read",
            arguments=json.dumps({"task": "what is the current weather"}),
        )
        yield AgentMessageFinish(finish_reason="tool_calls", usage=None)

    def fake_stream_followup(*_a, **_kw):
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    side_effects = [fake_stream(), fake_stream_followup()]

    with patch(
        "hof.agent.stream.stream_agent_turn",
        side_effect=lambda *a, **kw: side_effects.pop(0),
    ):
        events = list(
            iter_agent_chat_stream([{"role": "user", "content": "run"}], None),
        )

    tool_results = [e for e in events if e.get("type") == "tool_result"]
    assert tool_results, "expected the tool to actually run"
    result = tool_results[0]
    assert result["name"] == "noop_read"
    assert result.get("ok") is True
    data = result.get("data")
    if isinstance(data, dict):
        assert data.get("error") != "tool_call_refused"


def test_validator_first_non_none_wins(monkeypatch) -> None:
    """When several validators are registered for the same tool, the first
    non-None refusal short-circuits the rest."""
    importlib.reload(importlib.import_module("hof.agent.builtin_tools"))

    from hof.functions import function as hof_function
    from hof.functions import registry

    if registry.get_function("noop_read") is None:

        @hof_function(name="noop_read", tool_summary="No-op read")
        def _noop_read() -> dict:
            return {"ok": True}

    seen: list[str] = []

    def first(_: Mapping[str, Any]) -> str | None:
        seen.append("first")
        return "blocked by first"

    def second(_: Mapping[str, Any]) -> str | None:
        seen.append("second")
        return "blocked by second"

    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset({"noop_read"}),
            allowlist_mutation=frozenset(),
            system_prompt_intro="test ",
            confirmation_summary_mode="none",
            tool_pre_call_validators={"noop_read": [first, second]},
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AGENT_REASONING_MODE", raising=False)

    def fake_stream(*_a, **_kw):
        yield AgentToolCallDelta(
            index=0,
            tool_call_id="call_b",
            name="noop_read",
            arguments="{}",
        )
        yield AgentMessageFinish(finish_reason="tool_calls", usage=None)

    def fake_stream_followup(*_a, **_kw):
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    side_effects = [fake_stream(), fake_stream_followup()]

    with patch(
        "hof.agent.stream.stream_agent_turn",
        side_effect=lambda *a, **kw: side_effects.pop(0),
    ):
        events = list(
            iter_agent_chat_stream([{"role": "user", "content": "run"}], None),
        )

    tool_results = [e for e in events if e.get("type") == "tool_result"]
    assert tool_results
    refusal = tool_results[0]
    assert refusal.get("ok") is False
    data = refusal.get("data") or {}
    assert data.get("message") == "blocked by first"
    assert seen == ["first"], "second validator must not run when first refuses"
