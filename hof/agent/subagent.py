"""Scoped sub-agent loop primitive.

A *sub-agent* is a child agent run with its own ``AgentPolicy`` snapshot
(focused system prompt, smaller tool allowlist, no further sub-agents)
that is driven entirely from a background thread by a host application
(e.g. hof-os' ``dispatch_office_agent``). It re-uses the same NDJSON
event contract as the top-level ``iter_agent_chat_stream`` loop so the
host can persist + fan out events as it sees fit.

The host is expected to:

  1. Build an ``AgentPolicy`` whose ``allowlist_*`` is restricted to the
     sub-agent's tool palette and whose ``system_prompt_intro`` is the
     focused worker prompt (NOT the top-level routing prompt).
  2. Spawn a daemon thread.
  3. Inside the thread, iterate ``run_scoped_subagent_loop(...)`` and
     forward every event to its session row + an SSE channel so a
     side-canvas can render the live progress.

This module deliberately stays small: the heavy lifting still lives in
``hof.agent.stream._run_agent_chat_stream`` (which already takes an
explicit ``policy`` kwarg). All we add here is a public entry point so
hosts don't have to reach into private symbols.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from hof.agent.policy import AgentPolicy


def iter_subagent_chat_stream(
    messages: list[dict[str, Any]],
    *,
    policy: AgentPolicy,
    attachments: list[dict[str, Any]] | None = None,
    mode: str | None = None,
    max_rounds: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Run a scoped agent loop and yield NDJSON events.

    Equivalent to :func:`hof.agent.iter_agent_chat_stream` but takes an
    **explicit** ``policy`` instead of reading the global one set via
    :func:`hof.agent.configure_agent`. This is what makes a *sub-agent*
    safe to run inside the same process as the parent agent: the parent
    keeps using the global policy (full tool palette + routing prompt)
    while the sub-agent gets its own snapshot (small palette + focused
    worker prompt) without touching global state.

    The caller is responsible for:
      - constructing ``policy`` with the desired ``allowlist_*``,
        ``system_prompt_intro``, ``sandbox`` config (a sub-agent that
        runs ``office-agent`` CLI must enable the sandbox) and an empty
        ``browser`` (sub-agents shouldn't recurse into browse).
      - draining the iterator on a background thread (this function is
        synchronous and blocks until the sub-agent reaches a final
        reply, an error, or a halt event).
      - persisting events / publishing SSE.

    ``max_rounds`` lets a host pin a per-sub-agent tool-round budget
    that overrides the process-wide ``Config.agent_max_rounds`` (which
    defaults to 10 and is sized for the parent router agent). Granular
    sub-agents — e.g. an Office sub-agent that runs ``office-agent``
    CLI calls per paragraph + per style + a final S3 upload — typically
    need 30-50 rounds; without an override they would hit the parent
    cap before finishing. Pass ``None`` (the default) to use the
    process-wide value.

    The yielded event shapes are the same NDJSON dicts the top-level
    stream emits: ``run_start``, ``phase``, ``content_delta``,
    ``tool_call``, ``tool_result``, ``final``, ``error``, etc.
    """
    # Late import: ``hof.agent.stream`` pulls in the model providers and
    # the full sandbox stack, which is heavy. Importing it lazily keeps
    # ``hof.agent.subagent`` cheap to import for callers that only want
    # to type-check against the symbol.
    from hof.agent.stream import _run_agent_chat_stream

    yield from _run_agent_chat_stream(
        messages,
        attachments,
        policy=policy,
        mode=mode,
        max_rounds=max_rounds,
    )
