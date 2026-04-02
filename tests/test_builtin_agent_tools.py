"""Tests for framework built-in agent tools (plan builtins, terminal exec)."""

from __future__ import annotations

import importlib

from hof.agent.policy import (
    BUILTIN_AGENT_TOOL_NAMES,
    AgentPolicy,
    configure_agent,
    get_agent_policy,
)


def _reload() -> None:
    importlib.reload(importlib.import_module("hof.agent.builtin_tools"))


def test_builtin_names_match_policy_constant() -> None:
    from hof.core.registry import registry

    _reload()
    assert BUILTIN_AGENT_TOOL_NAMES == frozenset(
        {
            "hof_builtin_present_plan",
            "hof_builtin_present_plan_clarification",
            "hof_builtin_update_plan_todo_state",
        },
    )
    for name in BUILTIN_AGENT_TOOL_NAMES:
        assert registry.get_function(name) is not None


def test_removed_builtins_not_registered() -> None:
    """Removed builtins must not exist in the registry or policy constant."""
    from hof.core.registry import registry

    _reload()
    removed = {
        "hof_builtin_server_time",
        "hof_builtin_runtime_info",
        "hof_builtin_http_get",
        "hof_builtin_calculate",
    }
    for name in removed:
        assert name not in BUILTIN_AGENT_TOOL_NAMES
        assert registry.get_function(name) is None


def test_plan_builtins_are_present() -> None:
    """Plan-related builtins must still be registered."""
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="test ",
        ),
    )
    eff = get_agent_policy().effective_allowlist()
    for name in (
        "hof_builtin_present_plan",
        "hof_builtin_present_plan_clarification",
        "hof_builtin_update_plan_todo_state",
    ):
        assert name in eff
