"""Tests for agent tool description composition."""

from __future__ import annotations

from hof.agent.policy import AgentPolicy, configure_agent
from hof.agent.tooling import AGENT_TOOL_DESCRIPTION_MAX_CHARS, compose_agent_tool_description, openai_tool_specs
from hof.core.registry import registry
from hof.functions import function


class TestComposeAgentToolDescription:
    def test_includes_policy_when_to_use_and_related(self):
        @function
        def ledger_list() -> dict:
            """List rows."""
            return {}

        configure_agent(
            AgentPolicy(
                allowlist_read=frozenset({"ledger_list"}),
                allowlist_mutation=frozenset(),
                system_prompt_intro="x",
                tool_when_to_use={"ledger_list": "Use before updates."},
                tool_related_tools={"ledger_list": ["ledger_get", "ledger_update"]},
            ),
        )
        meta = registry.get_function("ledger_list")
        assert meta is not None
        text = compose_agent_tool_description("ledger_list", meta)
        assert "List rows." in text
        assert "When to use: Use before updates." in text
        assert "Typical next steps: ledger_get, ledger_update" in text

    def test_decorator_metadata_overrides_empty_policy_lists(self):
        @function(
            when_to_use="From decorator.",
            when_not_to_use="Never for deletes.",
            related_tools=("a", "b"),
        )
        def decorated_list() -> dict:
            """Body."""
            return {}

        configure_agent(
            AgentPolicy(
                allowlist_read=frozenset({"decorated_list"}),
                allowlist_mutation=frozenset(),
                system_prompt_intro="x",
            ),
        )
        meta = registry.get_function("decorated_list")
        assert meta is not None
        text = compose_agent_tool_description("decorated_list", meta)
        assert "When to use: From decorator." in text
        assert "When not to use: Never for deletes." in text
        assert "Typical next steps: a, b" in text

    def test_openai_tool_specs_uses_composed_description(self):
        @function
        def spec_fn() -> dict:
            """Hello."""
            return {}

        configure_agent(
            AgentPolicy(
                allowlist_read=frozenset({"spec_fn"}),
                allowlist_mutation=frozenset(),
                system_prompt_intro="x",
                tool_when_to_use={"spec_fn": "Always."},
            ),
        )
        specs = openai_tool_specs(frozenset({"spec_fn"}))
        assert len(specs) == 1
        desc = specs[0]["function"]["description"]
        assert "Hello." in desc
        assert "When to use: Always." in desc

    def test_truncates_long_description(self):
        @function
        def long_doc_fn() -> dict:
            """X."""
            return {}

        configure_agent(
            AgentPolicy(
                allowlist_read=frozenset({"long_doc_fn"}),
                allowlist_mutation=frozenset(),
                system_prompt_intro="x",
                tool_when_to_use={"long_doc_fn": "W" * AGENT_TOOL_DESCRIPTION_MAX_CHARS},
            ),
        )
        meta = registry.get_function("long_doc_fn")
        assert meta is not None
        text = compose_agent_tool_description("long_doc_fn", meta)
        assert len(text) <= AGENT_TOOL_DESCRIPTION_MAX_CHARS
