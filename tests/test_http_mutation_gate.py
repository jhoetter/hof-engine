"""HTTP mutation deferral when terminal-only agent sends correlation headers."""

from __future__ import annotations

import json

from hof.agent.http_mutation_gate import defer_mutation_if_terminal_agent_http
from hof.agent.policy import AgentPolicy, MutationPreviewResult, SandboxConfig
from hof.agent.state import (
    delete_agent_run,
    delete_pending,
    load_pending,
    save_agent_run,
)


def test_defer_mutation_skips_when_run_not_saved(monkeypatch):
    """HTTP defer requires ``save_agent_run`` (stream persists at ``run_start``)."""
    policy = AgentPolicy(
        allowlist_read=frozenset(),
        allowlist_mutation=frozenset({"create_widget"}),
        system_prompt_intro="x",
        sandbox=SandboxConfig(
            enabled=True,
            terminal_only_dispatch=True,
        ),
    )
    monkeypatch.setattr("hof.agent.http_mutation_gate.try_get_agent_policy", lambda: policy)
    out = defer_mutation_if_terminal_agent_http(
        function_name="create_widget",
        kwargs={"a": 1},
        agent_run_id="11111111-1111-1111-1111-111111111111",
        tool_call_id="tc1",
    )
    assert out is None


def test_defer_mutation_skips_without_active_run(monkeypatch):
    policy = AgentPolicy(
        allowlist_read=frozenset(),
        allowlist_mutation=frozenset({"create_widget"}),
        system_prompt_intro="x",
        sandbox=SandboxConfig(
            enabled=True,
            terminal_only_dispatch=True,
        ),
    )
    monkeypatch.setattr("hof.agent.http_mutation_gate.try_get_agent_policy", lambda: policy)
    out = defer_mutation_if_terminal_agent_http(
        function_name="create_widget",
        kwargs={"a": 1},
        agent_run_id="no-such-run",
        tool_call_id="tc1",
    )
    assert out is None


def test_defer_mutation_works_after_resume_re_save(monkeypatch):
    """After resume deletes then re-saves the run, mutations must still be deferred."""
    run_id = "r-test-resume-re-save"
    save_agent_run(
        run_id,
        {"oa_messages": [], "model": "m", "llm_backend": "openai", "rounds": 0},
    )

    policy = AgentPolicy(
        allowlist_read=frozenset(),
        allowlist_mutation=frozenset({"create_widget"}),
        system_prompt_intro="x",
        sandbox=SandboxConfig(enabled=True, terminal_only_dispatch=True),
    )
    monkeypatch.setattr("hof.agent.http_mutation_gate.try_get_agent_policy", lambda: policy)

    # Simulate resume: delete the run then re-save (as _run_agent_llm_tool_loop does).
    delete_agent_run(run_id)
    save_agent_run(
        run_id,
        {"oa_messages": [], "model": "m", "llm_backend": "openai", "rounds": 1},
    )

    pid: str | None = None
    try:
        inner = defer_mutation_if_terminal_agent_http(
            function_name="create_widget",
            kwargs={"b": 2},
            agent_run_id=run_id,
            tool_call_id="call_after_resume",
        )
        assert inner is not None, "mutation must be deferred after resume re-saves the agent run"
        assert inner["pending_confirmation"] is True
        pid = str(inner["pending_id"])
    finally:
        if pid:
            delete_pending(pid)
        delete_agent_run(run_id)


def test_defer_mutation_fails_without_re_save(monkeypatch):
    """Without re-saving after delete, mutations are NOT deferred (the pre-fix bug)."""
    run_id = "r-test-no-re-save"
    save_agent_run(
        run_id,
        {"oa_messages": [], "model": "m", "llm_backend": "openai", "rounds": 0},
    )

    policy = AgentPolicy(
        allowlist_read=frozenset(),
        allowlist_mutation=frozenset({"create_widget"}),
        system_prompt_intro="x",
        sandbox=SandboxConfig(enabled=True, terminal_only_dispatch=True),
    )
    monkeypatch.setattr("hof.agent.http_mutation_gate.try_get_agent_policy", lambda: policy)

    # Simulate resume that only deletes (the pre-fix behavior).
    delete_agent_run(run_id)

    inner = defer_mutation_if_terminal_agent_http(
        function_name="create_widget",
        kwargs={"b": 2},
        agent_run_id=run_id,
        tool_call_id="call_after_delete_only",
    )
    assert inner is None, "without re-save, mutation should NOT be deferred"


def test_defer_mutation_returns_pending_shape(monkeypatch):
    run_id = "r-test-http-gate"
    save_agent_run(run_id, {"oa_messages": [], "model": "m", "llm_backend": "openai", "rounds": 0})

    policy = AgentPolicy(
        allowlist_read=frozenset(),
        allowlist_mutation=frozenset({"create_widget"}),
        system_prompt_intro="x",
        sandbox=SandboxConfig(enabled=True, terminal_only_dispatch=True),
        mutation_preview={
            "create_widget": lambda _args: MutationPreviewResult(
                summary="Preview line",
                data={"x": 1},
            ),
        },
    )
    monkeypatch.setattr("hof.agent.http_mutation_gate.try_get_agent_policy", lambda: policy)
    pid: str | None = None
    try:
        inner = defer_mutation_if_terminal_agent_http(
            function_name="create_widget",
            kwargs={"a": 1},
            agent_run_id=run_id,
            tool_call_id="call_xyz",
        )
        assert inner is not None
        assert inner["pending_confirmation"] is True
        assert inner["function"] == "create_widget"
        pid = str(inner["pending_id"])
        assert pid
        assert "preview" in inner
        loaded = load_pending(pid)
        assert loaded is not None
        assert loaded["run_id"] == run_id
        assert loaded["tool_call_id"] == "call_xyz"
        assert loaded["function_name"] == "create_widget"
        assert json.loads(str(loaded["arguments_json"])) == {"a": 1}
    finally:
        if pid:
            delete_pending(pid)
        delete_agent_run(run_id)
