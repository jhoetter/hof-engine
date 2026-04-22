"""Tests for ``merge_extensions`` aggregation logic.

Focuses on the ``terminal_only_passthrough_tools`` field used by domains to
expose first-class LLM tools (sub-agent dispatchers) in
``terminal_only_dispatch`` mode without bloating the platform default
``builtins_when_terminal_only`` set.
"""

from __future__ import annotations

from hof.agent.extensions import (
    AgentExtension,
    merge_extensions,
)


def _empty_merge_kwargs() -> dict:
    return dict(
        base_read=frozenset(),
        base_mutation=frozenset(),
        base_rationale={},
        base_when_to_use={},
        base_related_tools={},
        base_param_hints={},
        base_mutation_preview={},
        base_mutation_post_apply={},
        base_mutation_inbox_watches={},
    )


def test_passthrough_tools_default_empty() -> None:
    merged = merge_extensions(extensions=[], **_empty_merge_kwargs())
    assert merged.terminal_only_passthrough_tools == frozenset()


def test_passthrough_tools_unions_across_extensions() -> None:
    """Each extension contributes its own dispatch surface; the merge must
    union them so the SandboxConfig sees the full set."""
    merged = merge_extensions(
        extensions=[
            AgentExtension(
                name="officeai",
                terminal_only_passthrough_tools=frozenset(
                    {
                        "dispatch_office_agent",
                        "list_office_agent_sessions",
                    }
                ),
            ),
            AgentExtension(
                name="webagent",
                terminal_only_passthrough_tools=frozenset(
                    {
                        "dispatch_web_agent",
                        "list_web_agent_sessions",
                    }
                ),
            ),
            # Extension that contributes nothing must not affect the union.
            AgentExtension(name="other"),
        ],
        **_empty_merge_kwargs(),
    )
    assert merged.terminal_only_passthrough_tools == frozenset(
        {
            "dispatch_office_agent",
            "list_office_agent_sessions",
            "dispatch_web_agent",
            "list_web_agent_sessions",
        }
    )


def test_passthrough_tools_dedupes_across_extensions() -> None:
    """Two extensions declaring the same tool should still produce one entry."""
    merged = merge_extensions(
        extensions=[
            AgentExtension(
                name="a",
                terminal_only_passthrough_tools=frozenset({"shared_tool"}),
            ),
            AgentExtension(
                name="b",
                terminal_only_passthrough_tools=frozenset(
                    {"shared_tool", "b_only"}
                ),
            ),
        ],
        **_empty_merge_kwargs(),
    )
    assert merged.terminal_only_passthrough_tools == frozenset(
        {"shared_tool", "b_only"}
    )
