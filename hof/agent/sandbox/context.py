"""Context for the active agent run (terminal session binding)."""

from __future__ import annotations

import contextvars
import threading
from dataclasses import dataclass
from typing import Any

_lock = threading.Lock()


@dataclass
class SandboxRunState:
    run_id: str
    user_id: str
    policy_snapshot: Any
    terminal_session: Any | None = None
    #: Normalized chat attachments (S3 keys) for staging into ``/workspace`` on first terminal use.
    chat_attachments: list[dict[str, str]] | None = None
    sandbox_attachments_staged: bool = False


# ``ContextVar`` does not propagate into Starlette/uvicorn worker threads that iterate the
# agent stream; ``_sandbox_by_run_id`` mirrors the same :class:`SandboxRunState` for lookup
# during ``execute_tool`` (see ``hof.agent.tooling``).
_sandbox_by_run_id: dict[str, SandboxRunState] = {}

_sandbox_run: contextvars.ContextVar[SandboxRunState | None] = contextvars.ContextVar(
    "hof_sandbox_run",
    default=None,
)


def get_sandbox_run() -> SandboxRunState | None:
    return _sandbox_run.get()


def bind_sandbox_run(run_id: str, state: SandboxRunState) -> None:
    """Register ``state`` for ``run_id`` (same object as in the ContextVar)."""
    with _lock:
        _sandbox_by_run_id[run_id] = state


def unbind_sandbox_run(run_id: str) -> None:
    with _lock:
        _sandbox_by_run_id.pop(run_id, None)


def get_sandbox_run_for_bind(run_id: str) -> SandboxRunState | None:
    with _lock:
        return _sandbox_by_run_id.get(run_id)


def resolve_sandbox_run_state(run_id: str | None) -> SandboxRunState | None:
    """Prefer run-id table (streaming/thread-safe), then ContextVar."""
    if run_id:
        bound = get_sandbox_run_for_bind(run_id)
        if bound is not None:
            return bound
    return get_sandbox_run()


def set_sandbox_run(
    *,
    run_id: str,
    user_id: str,
    policy: Any,
    chat_attachments: list[dict[str, str]] | None = None,
) -> contextvars.Token[SandboxRunState | None]:
    return _sandbox_run.set(
        SandboxRunState(
            run_id=run_id,
            user_id=user_id,
            policy_snapshot=policy,
            chat_attachments=chat_attachments,
        ),
    )


def adopt_sandbox_run(state: SandboxRunState) -> contextvars.Token[SandboxRunState | None]:
    """Bind ``state`` to the current ContextVar without creating a new state.

    Used on resume: after a turn paused on ``awaiting_confirmation`` we deferred the
    release of the terminal session for the next turn. The next turn must reuse the
    *same* :class:`SandboxRunState` object (the one carrying ``terminal_session``)
    rather than allocate a fresh one which would discard the bound container.
    """
    return _sandbox_run.set(state)


def reset_sandbox_run(token: contextvars.Token[SandboxRunState | None]) -> None:
    _sandbox_run.reset(token)


def release_bound_terminal_session(*, run_id: str | None = None) -> None:
    """Release pooled container if a :class:`TerminalSession` was created for this run."""
    run = resolve_sandbox_run_state(run_id)
    if run is None or run.terminal_session is None:
        return
    try:
        run.terminal_session.release()
    finally:
        run.terminal_session = None
