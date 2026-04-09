"""Tests for agent tool description composition."""

from __future__ import annotations

import json

from hof.agent.policy import AgentPolicy, configure_agent
from hof.agent.sandbox.constants import HOF_BUILTIN_TERMINAL_EXEC
from hof.agent.tooling import (
    AGENT_TOOL_DESCRIPTION_MAX_CHARS,
    AGENT_TOOL_DISPLAY_TITLE_KEY,
    ToolExecResult,
    compose_agent_tool_description,
    execute_tool,
    format_cli_line,
    format_tool_result_for_model,
    openai_tool_specs,
    split_agent_tool_display_metadata,
    structured_agent_tool_for_ui,
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
        props = specs[0]["function"]["parameters"]["properties"]
        assert AGENT_TOOL_DISPLAY_TITLE_KEY in props
        assert props[AGENT_TOOL_DISPLAY_TITLE_KEY]["type"] == "string"

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


class TestStructuredAgentToolForUi:
    def test_separate_fields_match_policy_merge(self):
        @function
        def ui_list_fn() -> dict:
            """List rows."""
            return {}

        pol = AgentPolicy(
            allowlist_read=frozenset({"ui_list_fn"}),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
            tool_when_to_use={"ui_list_fn": "Use before updates."},
            tool_related_tools={"ui_list_fn": ["ledger_get", "ledger_update"]},
        )
        meta = registry.get_function("ui_list_fn")
        assert meta is not None
        row = structured_agent_tool_for_ui(
            "ui_list_fn",
            meta,
            pol,
            mutation=False,
            parameters={"type": "object", "properties": {}},
        )
        assert row["name"] == "ui_list_fn"
        assert row["mutation"] is False
        assert row["description"] == "List rows."
        assert row["when_to_use"] == "Use before updates."
        assert row["related_tools"] == ["ledger_get", "ledger_update"]


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


def test_tool_result_status_for_ui_terminal_exec_exit_zero_ignores_vacuous_error() -> None:
    raw = json.dumps(
        {"exit_code": 0, "output": '{"result":{"rows":[]}}', "error": ""},
    )
    assert tool_result_status_for_ui(raw) == (True, 200)


def test_tool_result_status_for_ui_terminal_exec_nonzero() -> None:
    raw = json.dumps({"exit_code": 2, "output": "stderr"})
    assert tool_result_status_for_ui(raw) == (False, 500)


def test_tool_result_status_for_ui_terminal_nested_result_string() -> None:
    inner = json.dumps({"exit_code": 0, "output": '{"result":{"rows":[]}}'})
    raw = json.dumps({"result": inner, "duration_ms": 0, "error": ""})
    assert tool_result_status_for_ui(raw) == (True, 200)


def test_tool_result_status_for_ui_validation() -> None:
    raw = '{"error":"validation failed","detail":[]}'
    assert tool_result_status_for_ui(raw) == (False, 422)


def test_tool_result_status_for_ui_rejected() -> None:
    assert tool_result_status_for_ui(
        '{"rejected":true,"message":"no"}',
    ) == (False, 499)


def test_format_cli_line_nested_payload_uses_flags() -> None:
    args = json.dumps({"rows": [{"description": "x", "amount": 1.0}]})
    line = format_cli_line("bulk_create_expenses", args, max_cli_line_chars=800)
    assert line.startswith("hof fn bulk_create_expenses ")
    assert "POST /api/functions/" not in line
    assert "--rows" in line


def test_format_cli_line_flat_args_uses_flags() -> None:
    line = format_cli_line("list_expenses", '{"page":1}', max_cli_line_chars=200)
    assert line.startswith("hof fn list_expenses ")
    assert "--page" in line


def test_split_agent_tool_display_metadata_strips_title() -> None:
    raw = json.dumps(
        {"file_name": "invoice_72.pdf", AGENT_TOOL_DISPLAY_TITLE_KEY: "Uploading invoice_72.pdf"},
    )
    wire, title = split_agent_tool_display_metadata(raw)
    assert title == "Uploading invoice_72.pdf"
    parsed = json.loads(wire)
    assert AGENT_TOOL_DISPLAY_TITLE_KEY not in parsed
    assert parsed["file_name"] == "invoice_72.pdf"


def test_format_cli_line_omits_display_title() -> None:
    raw = json.dumps({"page": 1, AGENT_TOOL_DISPLAY_TITLE_KEY: "List page 1"})
    line = format_cli_line("list_expenses", raw, max_cli_line_chars=200)
    assert AGENT_TOOL_DISPLAY_TITLE_KEY not in line
    assert "List page" not in line
    assert "--page" in line


def test_format_cli_line_terminal_exec_hof_fn_json_to_flags() -> None:
    """Sandbox ``hof fn name '<json>'`` is shown as pseudo-CLI flags (same as direct calls)."""
    wire = json.dumps(
        {
            "command": (
                "hof fn create_expense "
                '\'{"description":"Coffee","amount":12.5,"date":"2026-03-29","category":"Food"}\''
            ),
        },
    )
    line = format_cli_line(HOF_BUILTIN_TERMINAL_EXEC, wire, max_cli_line_chars=500)
    assert "hof fn create_expense" in line
    assert "--description" in line
    assert "Coffee" in line
    assert "--amount" in line
    assert "'{\\" not in line


class TestExecuteToolTruncation:
    """Status/data must be computed before truncation so large outputs keep correct ok/status."""

    def test_truncated_terminal_exec_keeps_ok_status(self) -> None:
        big_output = "x" * 50_000

        @function
        def _trunc_test_fn() -> dict:
            return {"exit_code": 0, "output": big_output}

        configure_agent(
            AgentPolicy(
                allowlist_read=frozenset({"_trunc_test_fn"}),
                allowlist_mutation=frozenset(),
                system_prompt_intro="x",
            ),
        )
        result = execute_tool(
            "_trunc_test_fn",
            "{}",
            frozenset({"_trunc_test_fn"}),
            max_tool_output_chars=1000,
        )
        assert isinstance(result, ToolExecResult)
        assert result.ok is True
        assert result.status_code == 200
        assert result.parsed_data is not None
        assert result.parsed_data["exit_code"] == 0
        assert "…(truncated)" in result.raw_json

    def test_truncated_output_parsed_data_is_from_full_json(self) -> None:
        @function
        def _trunc_rows_fn() -> dict:
            return {"rows": [{"v": "a" * 5000}], "total": 1}

        configure_agent(
            AgentPolicy(
                allowlist_read=frozenset({"_trunc_rows_fn"}),
                allowlist_mutation=frozenset(),
                system_prompt_intro="x",
            ),
        )
        result = execute_tool(
            "_trunc_rows_fn",
            "{}",
            frozenset({"_trunc_rows_fn"}),
            max_tool_output_chars=500,
        )
        assert result.ok is True
        assert result.status_code == 200
        assert isinstance(result.parsed_data, dict)
        assert result.parsed_data["total"] == 1
        assert "…(truncated)" in result.raw_json
