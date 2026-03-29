"""Mutation + human-in-the-loop when domain tools are terminal-only (CLI → HTTP).

In **terminal-only** dispatch the LLM never calls ``execute_tool`` for mutations. Mutations run
only when a CLI inside the sandbox calls ``POST /api/functions/<name>`` with the same auth as a
normal API client.

**Contract (application responsibility)**

1. **Preferred:** Extend the FastAPI (or proxy) layer so that when a request is part of an active
   agent chat run, mutation responses match the same JSON shape the in-process agent path expects
   (e.g. ``pending_confirmation``, ``pending_id``), and the client still uses
   ``agent_resume_mutations``. Typical mechanisms: a header (see
   :data:`AGENT_RUN_HEADER_NAME`) or a scoped short-lived token tied to ``run_id`` issued when the
   sandbox session starts.

2. **Alternative:** A small ``hof`` or ``curl`` wrapper in the skill image that calls an
   **internal** route that delegates to the same code path as ``agent_chat`` mutation preview
   (not documented here; product-specific).

3. **Implemented in hof-engine:** ``POST /api/functions/<name>`` calls
   ``defer_mutation_if_terminal_agent_http`` when ``X-Hof-Agent-Run-Id`` matches an active
   ``agent_chat`` run (and ``terminal_only_dispatch`` is on). The agent stream then parses
   terminal stdout and emits ``mutation_pending`` (see ``_try_coerce_terminal_exec_mutation_events``).
   Curl in the sandbox must still send both correlation headers; env
   ``HOF_AGENT_RUN_ID`` / ``HOF_AGENT_TOOL_CALL_ID`` are injected per ``docker exec``.
"""

from __future__ import annotations

# HTTP header name apps may use to correlate sandbox CLI calls with the active agent run.
# Values are product-specific; the engine only documents the conventional name.
AGENT_RUN_HEADER_NAME = "X-Hof-Agent-Run-Id"
# Optional second header: OpenAI tool_call id for the ``hof_builtin_terminal_exec`` row (pending UI).
AGENT_TOOL_CALL_HEADER_NAME = "X-Hof-Agent-Tool-Call-Id"

# Keys often present on mutation responses when chat confirmation is required (same as in-process
# tool path). Apps aligning HTTP with agent_chat should return compatible shapes.
PENDING_CONFIRMATION_KEY = "pending_confirmation"
PENDING_ID_KEY = "pending_id"

__all__ = [
    "AGENT_RUN_HEADER_NAME",
    "AGENT_TOOL_CALL_HEADER_NAME",
    "PENDING_CONFIRMATION_KEY",
    "PENDING_ID_KEY",
]
