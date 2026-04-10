"""Browser tool registration (no cloud calls)."""

from __future__ import annotations

import importlib
import os

from hof.core.registry import registry


def test_hof_builtin_browse_web_registered() -> None:
    import hof.agent.builtin_tools as bt
    import hof.browser.tools as brt

    importlib.reload(bt)
    importlib.reload(brt)
    meta = registry.get_function("hof_builtin_browse_web")
    assert meta is not None
    assert meta.name == "hof_builtin_browse_web"


def test_browser_policy_adds_tool_to_allowlist() -> None:
    from hof.agent.policy import AgentPolicy, configure_agent, get_agent_policy
    from hof.browser.config import BrowserConfig
    from hof.browser.constants import HOF_BUILTIN_BROWSE_WEB

    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset({"x"}),
            allowlist_mutation=frozenset(),
            system_prompt_intro="",
            browser=BrowserConfig(api_key="test-key"),
        ),
    )
    assert HOF_BUILTIN_BROWSE_WEB in get_agent_policy().effective_allowlist()


def test_browser_in_allowlist_when_terminal_only_dispatch() -> None:
    """Sandbox terminal-only must still expose browse (Cloud), not only shell + plan builtins."""
    from hof.agent.policy import AgentPolicy, configure_agent, get_agent_policy
    from hof.agent.sandbox.config import SandboxConfig
    from hof.browser.config import BrowserConfig
    from hof.browser.constants import HOF_BUILTIN_BROWSE_WEB

    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset({"x"}),
            allowlist_mutation=frozenset(),
            system_prompt_intro="",
            browser=BrowserConfig(api_key="test-key"),
            sandbox=SandboxConfig(
                enabled=True,
                terminal_only_dispatch=True,
                builtins_when_terminal_only=frozenset(),
                api_base_url="http://host.docker.internal:8001",
            ),
        ),
    )
    assert HOF_BUILTIN_BROWSE_WEB in get_agent_policy().effective_allowlist()


def test_resolve_browser_api_key_value_interpolates_env() -> None:
    from hof.browser.config import resolve_browser_api_key_value

    os.environ["HOF_BROWSER_TEST_KEY"] = "secret-from-env"
    try:
        assert resolve_browser_api_key_value("${HOF_BROWSER_TEST_KEY}") == "secret-from-env"
        assert resolve_browser_api_key_value("  bu_literal  ") == "bu_literal"
    finally:
        os.environ.pop("HOF_BROWSER_TEST_KEY", None)
