"""Tests for framework built-in agent tools (time, runtime, fetch, calculate)."""

from __future__ import annotations

import importlib
import json
from unittest.mock import MagicMock, patch

import pytest

from hof.agent.policy import (
    BUILTIN_AGENT_TOOL_NAMES,
    AgentPolicy,
    configure_agent,
    get_agent_policy,
)
from hof.agent.tooling import execute_tool


@pytest.fixture(autouse=True)
def _reload_builtin_agent_tools_after_registry_clear(clean_registry) -> None:
    """Re-apply ``@function`` registration after ``clean_registry`` (conftest autouse)."""
    importlib.reload(importlib.import_module("hof.agent.builtin_tools"))


def _allowlist() -> frozenset[str]:
    return get_agent_policy().effective_allowlist()


def _configure() -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="test ",
        ),
    )


def test_builtin_names_match_policy_constant() -> None:
    from hof.core.registry import registry

    assert BUILTIN_AGENT_TOOL_NAMES == frozenset(
        {
            "hof_builtin_server_time",
            "hof_builtin_runtime_info",
            "hof_builtin_http_get",
            "hof_builtin_calculate",
        },
    )
    for name in BUILTIN_AGENT_TOOL_NAMES:
        assert registry.get_function(name) is not None


def test_execute_server_time() -> None:
    _configure()
    raw, _summary = execute_tool(
        "hof_builtin_server_time",
        "{}",
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert "utc_iso" in data
    assert "unix_utc" in data
    assert "server_local_iso" in data


def test_execute_server_time_unknown_timezone() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_server_time",
        '{"iana_timezone": "NotA_Real_Zone_Xyz"}',
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert data.get("timezone_error") == "unknown IANA timezone"


def test_execute_runtime_info() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_runtime_info",
        "{}",
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert "hostname" in data
    assert "platform" in data
    assert "python_version" in data
    assert data.get("hof_engine_version") not in (None, "")


def test_http_get_rejects_https_loopback() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_http_get",
        '{"url": "https://127.0.0.1/"}',
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert "error" in data
    assert "SSRF" in data["error"] or "blocked" in data["error"]


def test_http_get_rejects_http_non_localhost() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_http_get",
        '{"url": "http://example.com/"}',
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert "error" in data


def test_http_get_rejects_metadata_ip_over_https() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_http_get",
        '{"url": "https://169.254.169.254/latest/meta-data/"}',
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert "error" in data


def test_http_get_success_mocked() -> None:
    _configure()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/plain"}
    mock_resp.iter_bytes.return_value = [b"hello"]

    stream_cm = MagicMock()
    stream_cm.__enter__.return_value = mock_resp
    stream_cm.__exit__.return_value = None

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = None
    mock_client.stream.return_value = stream_cm

    with (
        patch("hof.agent.builtin_tools._url_host_ips_allowed", return_value=(True, None)),
        patch("hof.agent.builtin_tools.httpx.Client", return_value=mock_client),
    ):
        raw, _s = execute_tool(
            "hof_builtin_http_get",
            '{"url": "https://example.com/ping"}',
            _allowlist(),
            max_tool_output_chars=8000,
        )

    data = json.loads(raw)
    assert data.get("status_code") == 200
    assert data.get("text") == "hello"
    assert data.get("truncated") is False


def test_calculate_expression() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        '{"expression": "2 + 3 * 4"}',
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert data.get("mode") == "expression"
    assert data.get("result") == 14


def test_calculate_aggregate_sum() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        '{"values": [1, 2, 3], "operation": "sum"}',
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert data.get("mode") == "aggregate"
    assert data.get("operation") == "sum"
    assert data.get("result") == 6


def test_calculate_aggregate_prefers_values_over_expression() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        '{"values": [10], "operation": "sum", "expression": "1+1"}',
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert data.get("result") == 10
    assert data.get("ignored_expression") is True


def test_calculate_division_by_zero() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        '{"expression": "1/0"}',
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert "error" in data


def test_calculate_expression_too_long() -> None:
    _configure()
    long_expr = "1+" + ("1+" * 3000) + "1"
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        json.dumps({"expression": long_expr}),
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert "error" in data
    assert "max length" in data["error"]


def test_calculate_too_many_values(monkeypatch) -> None:
    _configure()
    monkeypatch.setenv("HOF_AGENT_CALC_MAX_VALUES", "3")
    importlib.reload(importlib.import_module("hof.agent.builtin_tools"))
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        '{"values": [1, 2, 3, 4], "operation": "sum"}',
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert "error" in data
    assert "at most" in data["error"]


def test_calculate_missing_inputs() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        "{}",
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert "error" in data


def test_calculate_values_without_operation() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        '{"values": [1, 2]}',
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert "error" in data


def test_calculate_aggregate_stringified_json_array() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        json.dumps({"values": "[1, 2, 3]", "operation": "sum"}),
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert data.get("mode") == "aggregate"
    assert data.get("result") == 6


def test_calculate_aggregate_comma_separated_string() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        json.dumps({"values": "1, 2, 3", "operation": "mean"}),
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert data.get("mode") == "aggregate"
    assert data.get("result") == 2.0


def test_calculate_aggregate_list_of_numeric_strings() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        json.dumps({"values": ["1.5", "2.5"], "operation": "sum"}),
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert data.get("result") == 4.0


def test_calculate_aggregate_scalar_number() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        json.dumps({"values": 42, "operation": "mean"}),
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert data.get("mode") == "aggregate"
    assert data.get("result") == 42.0


def test_calculate_aggregate_values_object_rejected() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        json.dumps({"values": {"a": 1}, "operation": "sum"}),
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert "error" in data


def test_calculate_aggregate_multiple_operations() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        json.dumps({"values": [1, 2, 3], "operations": ["sum", "mean"]}),
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert data.get("mode") == "aggregate"
    assert data.get("results") == {"sum": 6, "mean": 2.0}


def test_calculate_aggregate_merges_operation_and_operations() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        json.dumps({"values": [1, 2, 3], "operation": "max", "operations": ["sum"]}),
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert data.get("mode") == "aggregate"
    assert data.get("results") == {"sum": 6, "max": 3.0}


def test_calculate_batch_expressions_mixed_success_and_error() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        json.dumps({"expressions": ["2 + 2", "1/0"]}),
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert data.get("mode") == "batch_expression"
    results = data.get("results")
    assert isinstance(results, list) and len(results) == 2
    assert results[0] == {"index": 0, "result": 4}
    assert results[1]["index"] == 1
    assert "error" in results[1]
    assert "division" in results[1]["error"].lower()


def test_calculate_values_and_expressions_conflict() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        json.dumps({"values": [1, 2], "operation": "sum", "expressions": ["1+1"]}),
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert "error" in data
    assert "values" in data["error"] and "expressions" in data["error"]


def test_calculate_expression_and_expressions_conflict() -> None:
    _configure()
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        json.dumps({"expression": "1+1", "expressions": ["2+2"]}),
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert "error" in data


def test_calculate_batch_expressions_over_limit(monkeypatch) -> None:
    _configure()
    monkeypatch.setenv("HOF_AGENT_CALC_MAX_BATCH_EXPRESSIONS", "2")
    importlib.reload(importlib.import_module("hof.agent.builtin_tools"))
    raw, _s = execute_tool(
        "hof_builtin_calculate",
        json.dumps({"expressions": ["1", "2", "3"]}),
        _allowlist(),
        max_tool_output_chars=8000,
    )
    data = json.loads(raw)
    assert "error" in data
    assert "at most" in data["error"]
