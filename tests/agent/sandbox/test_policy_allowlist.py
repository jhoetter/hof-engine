"""AgentPolicy + SandboxConfig effective allowlist."""

from __future__ import annotations

from hof.agent.policy import (
    BUILTIN_AGENT_TOOL_NAMES,
    HOF_BUILTIN_TERMINAL_EXEC,
    AgentPolicy,
)
from hof.agent.sandbox.config import SandboxConfig


def test_effective_allowlist_default_no_sandbox() -> None:
    p = AgentPolicy(
        allowlist_read=frozenset({"read_fn"}),
        allowlist_mutation=frozenset({"mut_fn"}),
        system_prompt_intro="x",
    )
    assert "read_fn" in p.effective_allowlist()
    assert "mut_fn" in p.effective_allowlist()
    assert HOF_BUILTIN_TERMINAL_EXEC not in p.effective_allowlist()


def test_effective_allowlist_sandbox_additive_terminal_tool() -> None:
    p = AgentPolicy(
        allowlist_read=frozenset({"read_fn"}),
        allowlist_mutation=frozenset({"mut_fn"}),
        system_prompt_intro="x",
        sandbox=SandboxConfig(enabled=True, terminal_only_dispatch=False),
    )
    eff = p.effective_allowlist()
    assert HOF_BUILTIN_TERMINAL_EXEC in eff
    assert "read_fn" in eff


def test_effective_allowlist_terminal_only_strips_domain() -> None:
    p = AgentPolicy(
        allowlist_read=frozenset({"read_fn"}),
        allowlist_mutation=frozenset({"mut_fn"}),
        system_prompt_intro="x",
        sandbox=SandboxConfig(
            enabled=True,
            terminal_only_dispatch=True,
            builtins_when_terminal_only=frozenset({"hof_builtin_present_plan"}),
        ),
    )
    eff = p.effective_allowlist()
    assert eff == frozenset({"hof_builtin_present_plan", HOF_BUILTIN_TERMINAL_EXEC})
    assert "read_fn" not in eff
    assert "mut_fn" not in eff
    assert not eff.intersection(BUILTIN_AGENT_TOOL_NAMES - {"hof_builtin_present_plan"})


def test_sandbox_config_env_override_terminal_only(monkeypatch) -> None:
    monkeypatch.setenv("HOF_SANDBOX_ENABLED", "true")
    monkeypatch.setenv("HOF_SANDBOX_TERMINAL_ONLY", "true")
    monkeypatch.setenv("HOF_SANDBOX_BUILTINS", "hof_builtin_present_plan")
    sc = SandboxConfig(enabled=False, terminal_only_dispatch=False).with_env_overrides()
    assert sc.enabled is True
    assert sc.terminal_only_dispatch is True
    assert sc.builtins_when_terminal_only == frozenset({"hof_builtin_present_plan"})
