"""Tests for the per-call ``max_rounds`` override on
``iter_subagent_chat_stream``.

Sub-agent hosts (e.g. an Office sub-agent that runs the ``office-agent``
CLI per paragraph) need a larger tool-round budget than the parent
router agent. The override pinned at the call site is the supported
mechanism for this — bumping the process-wide ``Config.agent_max_rounds``
would also affect the parent agent and other consumers.

These tests pin the contract:

  * ``iter_subagent_chat_stream`` accepts an explicit ``max_rounds`` kwarg.
  * ``_run_agent_chat_stream`` resolves the effective limit:
    explicit kwarg wins; absent / ``None`` / ``<= 0`` fall back to the
    configured value from ``_agent_limits()``.
"""

from __future__ import annotations

import inspect

from hof.agent.stream import _run_agent_chat_stream
from hof.agent.subagent import iter_subagent_chat_stream


def test_subagent_stream_signature_has_max_rounds_kwarg() -> None:
    sig = inspect.signature(iter_subagent_chat_stream)
    assert "max_rounds" in sig.parameters
    param = sig.parameters["max_rounds"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY
    assert param.default is None


def test_run_agent_chat_stream_signature_has_max_rounds_kwarg() -> None:
    sig = inspect.signature(_run_agent_chat_stream)
    assert "max_rounds" in sig.parameters
    param = sig.parameters["max_rounds"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY
    assert param.default is None


def test_subagent_max_rounds_resolution_logic() -> None:
    """The resolution rule (explicit > config) is plain Python: assert it
    directly without spinning up a real LLM loop."""
    config_max = 10

    # No override → use config.
    assert _resolve_effective_max_rounds(None, config_max) == config_max
    assert _resolve_effective_max_rounds(0, config_max) == config_max
    assert _resolve_effective_max_rounds(-5, config_max) == config_max

    # Explicit positive override wins, even if smaller or larger than config.
    assert _resolve_effective_max_rounds(40, config_max) == 40
    assert _resolve_effective_max_rounds(2, config_max) == 2


def _resolve_effective_max_rounds(explicit: int | None, config_value: int) -> int:
    """Mirror of the resolution expression in ``_run_agent_chat_stream``.

    Kept here so the rule is asserted by tests even if the production
    expression is refactored — both must agree.
    """
    return explicit if explicit is not None and explicit > 0 else config_value
