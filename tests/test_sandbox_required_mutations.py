"""Regression: sandbox-required mutations defer terminal release across HITL pause.

When the agent loop yields ``awaiting_confirmation`` for a mutation that depends
on the sandbox (e.g. ``upload_workspace_file_to_s3`` reading from
``/workspace``), ``_maybe_wrap_sandbox.finally`` must NOT release the bound
terminal session — otherwise the workspace is wiped before the user resumes
via ``agent_resume_mutations``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from hof.agent.policy import AgentPolicy
from hof.agent.sandbox.config import SandboxConfig
from hof.agent.sandbox.context import (
    SandboxRunState,
    bind_sandbox_run,
    get_sandbox_run_for_bind,
    unbind_sandbox_run,
)
from hof.agent.state import (
    delete_agent_run,
    delete_pending,
    save_agent_run,
    save_pending,
)
from hof.agent.stream import _has_sandbox_required_pendings, _maybe_wrap_sandbox


@dataclass
class _FakeTerminalSession:
    released: bool = False

    def release(self, *, reset_workspace: bool = True) -> None:
        self.released = True


def _make_policy(
    sandbox_required: frozenset[str] = frozenset(),
) -> AgentPolicy:
    return AgentPolicy(
        allowlist_read=frozenset(),
        allowlist_mutation=frozenset({"upload_workspace_file_to_s3"}),
        system_prompt_intro="x",
        sandbox=SandboxConfig(enabled=True),
        sandbox_required=sandbox_required,
    )


def _bind_fake_sandbox(run_id: str) -> _FakeTerminalSession:
    sess = _FakeTerminalSession()
    state = SandboxRunState(
        run_id=run_id,
        user_id=run_id,
        policy_snapshot=None,
        terminal_session=sess,
    )
    bind_sandbox_run(run_id, state)
    return sess


def _empty_loop() -> Iterator[dict[str, Any]]:
    if False:
        yield {}


def test_has_sandbox_required_pendings_true_for_matching_mutation():
    run_id = "r-test-defer-true"
    pid = "p-test-defer-true"
    save_agent_run(run_id, {"open_pending_ids": [pid]})
    save_pending(
        pid,
        {
            "run_id": run_id,
            "tool_call_id": "tc1",
            "function_name": "upload_workspace_file_to_s3",
            "arguments_json": "{}",
        },
    )
    try:
        policy = _make_policy(frozenset({"upload_workspace_file_to_s3"}))
        assert _has_sandbox_required_pendings(run_id, policy) is True
    finally:
        delete_pending(pid)
        delete_agent_run(run_id)


def test_has_sandbox_required_pendings_false_for_unrelated_mutation():
    run_id = "r-test-defer-false"
    pid = "p-test-defer-false"
    save_agent_run(run_id, {"open_pending_ids": [pid]})
    save_pending(
        pid,
        {
            "run_id": run_id,
            "tool_call_id": "tc1",
            "function_name": "create_widget",
            "arguments_json": "{}",
        },
    )
    try:
        policy = _make_policy(frozenset({"upload_workspace_file_to_s3"}))
        assert _has_sandbox_required_pendings(run_id, policy) is False
    finally:
        delete_pending(pid)
        delete_agent_run(run_id)


def test_has_sandbox_required_pendings_false_when_set_empty():
    run_id = "r-test-defer-empty"
    pid = "p-test-defer-empty"
    save_agent_run(run_id, {"open_pending_ids": [pid]})
    save_pending(
        pid,
        {
            "run_id": run_id,
            "tool_call_id": "tc1",
            "function_name": "upload_workspace_file_to_s3",
            "arguments_json": "{}",
        },
    )
    try:
        policy = _make_policy(frozenset())
        assert _has_sandbox_required_pendings(run_id, policy) is False
    finally:
        delete_pending(pid)
        delete_agent_run(run_id)


def test_maybe_wrap_sandbox_defers_release_when_required_pending_exists():
    """Pause with a sandbox-required pending: terminal session must survive."""
    run_id = "r-test-wrap-defer"
    pid = "p-test-wrap-defer"
    sess = _bind_fake_sandbox(run_id)
    save_agent_run(run_id, {"open_pending_ids": [pid]})
    save_pending(
        pid,
        {
            "run_id": run_id,
            "tool_call_id": "tc1",
            "function_name": "upload_workspace_file_to_s3",
            "arguments_json": "{}",
        },
    )
    try:
        policy = _make_policy(frozenset({"upload_workspace_file_to_s3"}))
        list(_maybe_wrap_sandbox(policy, run_id, _empty_loop()))
        # Bound state must still be present and session must NOT have been released.
        assert get_sandbox_run_for_bind(run_id) is not None
        assert sess.released is False
    finally:
        delete_pending(pid)
        delete_agent_run(run_id)
        unbind_sandbox_run(run_id)


def test_maybe_wrap_sandbox_releases_when_no_pending_required():
    """No pendings → original behaviour (release container)."""
    run_id = "r-test-wrap-release"
    sess = _bind_fake_sandbox(run_id)
    try:
        policy = _make_policy(frozenset({"upload_workspace_file_to_s3"}))
        list(_maybe_wrap_sandbox(policy, run_id, _empty_loop()))
        assert get_sandbox_run_for_bind(run_id) is None
        assert sess.released is True
    finally:
        unbind_sandbox_run(run_id)


def test_maybe_wrap_sandbox_resume_reuses_existing_state():
    """On resume the wrapper must reuse the already-bound state object so that
    the deferred terminal session (and its container's ``/workspace``) survives.
    Verified by observing the bound session being released by THIS wrapper —
    if a fresh ``SandboxRunState`` were created the original session would
    leak instead of being released.
    """
    run_id = "r-test-wrap-reuse"
    sess = _bind_fake_sandbox(run_id)
    try:
        policy = _make_policy(frozenset())
        list(_maybe_wrap_sandbox(policy, run_id, _empty_loop()))
        # No pendings: wrapper should release at the end (post-resume cleanup).
        # The originally-bound session was released → the wrapper reused the
        # same state object rather than creating a fresh one.
        assert sess.released is True
        assert get_sandbox_run_for_bind(run_id) is None
    finally:
        unbind_sandbox_run(run_id)
