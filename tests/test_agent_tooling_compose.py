"""Tests for agent tool description composition."""

from __future__ import annotations

from hof.agent.policy import AgentPolicy, configure_agent
from hof.agent.tooling import (
    AGENT_TOOL_DESCRIPTION_MAX_CHARS,
    compose_agent_tool_description,
    format_tool_result_for_model,
    openai_tool_specs,
    tool_result_status_for_ui,
)
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


def test_format_tool_result_for_model_marks_complete() -> None:
    raw = '{"rows":[]}'
    out = format_tool_result_for_model("list_expenses", raw)
    assert out.startswith("[hof:list_expenses · complete]\n")
    assert out.endswith(raw)


def test_format_tool_result_for_model_marks_truncated() -> None:
    raw = '{"rows":[]}\n…(truncated)'
    out = format_tool_result_for_model("list_expenses", raw)
    assert "[hof:list_expenses · truncated]\n" in out
    assert raw in out


def test_tool_result_status_for_ui_success() -> None:
    assert tool_result_status_for_ui('{"rows":[],"total":0}') == (True, 200)


def test_tool_result_status_for_ui_error_payload() -> None:
    assert tool_result_status_for_ui('{"error":"boom"}') == (False, 500)


def test_tool_result_status_for_ui_validation() -> None:
    raw = '{"error":"validation failed","detail":[]}'
    assert tool_result_status_for_ui(raw) == (False, 422)


def test_tool_result_status_for_ui_rejected() -> None:
    assert tool_result_status_for_ui(
        '{"rejected":true,"message":"no"}',
    ) == (False, 499)
