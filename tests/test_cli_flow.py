"""Tests for hof.cli.commands.flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from hof.cli.commands.flow import app
from hof.flows.flow import Flow
from hof.flows.state import ExecutionStatus, FlowExecution


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def no_api_client():
    with patch("hof.cli.api_client.get_client", return_value=None):
        yield


@pytest.fixture
def sample_execution_dict():
    return {
        "id": "abcdef12-0000-0000-0000-000000000000",
        "flow_name": "test_flow",
        "status": "completed",
        "started_at": "2024-01-01T00:00:00",
        "completed_at": "2024-01-01T00:00:01",
        "duration_ms": 1000,
        "node_states": [],
        "input_data": {},
        "output_data": {},
        "error": None,
    }


class TestFlowListDefinitions:
    def test_lists_registered_flows(self, runner, no_api_client):
        flow = Flow("my_test_flow")

        @flow.node
        def step_a() -> dict:
            return {}

        with patch("hof.cli.commands.flow.bootstrap"):
            result = runner.invoke(app, ["list-definitions"])
        assert result.exit_code == 0
        assert "my_test_flow" in result.output

    def test_shows_node_count(self, runner, no_api_client):
        flow = Flow("counted_flow")

        @flow.node
        def n1() -> dict:
            return {}

        @flow.node(depends_on=[n1])
        def n2() -> dict:
            return {}

        with patch("hof.cli.commands.flow.bootstrap"):
            result = runner.invoke(app, ["list-definitions"])
        assert result.exit_code == 0
        assert "2" in result.output

    def test_via_api_client(self, runner):
        mock_client = MagicMock()
        mock_client.list_flows.return_value = [
            {"name": "remote_flow", "nodes": {"a": {}, "b": {}}}
        ]
        with patch("hof.cli.api_client.get_client", return_value=mock_client):
            result = runner.invoke(app, ["list-definitions"])
        assert result.exit_code == 0
        assert "remote_flow" in result.output


class TestFlowRun:
    def test_run_missing_flow_exits(self, runner, no_api_client):
        with patch("hof.cli.commands.flow.bootstrap"):
            result = runner.invoke(app, ["run", "nonexistent_flow"])
        assert result.exit_code != 0

    def test_run_via_api_client(self, runner):
        mock_client = MagicMock()
        mock_client.run_flow.return_value = {
            "id": "exec-123",
            "status": "running",
        }
        with patch("hof.cli.api_client.get_client", return_value=mock_client):
            result = runner.invoke(app, ["run", "my_flow"])
        assert result.exit_code == 0
        assert "exec-123" in result.output

    def test_run_with_input_json(self, runner):
        mock_client = MagicMock()
        mock_client.run_flow.return_value = {"id": "exec-456", "status": "running"}
        with patch("hof.cli.api_client.get_client", return_value=mock_client):
            result = runner.invoke(app, ["run", "my_flow", "--input", '{"x": 1}'])
        assert result.exit_code == 0
        mock_client.run_flow.assert_called_with("my_flow", {"x": 1})


class TestFlowList:
    def test_list_empty(self, runner, no_api_client):
        mock_store = MagicMock()
        mock_store.list_executions.return_value = []
        with patch("hof.cli.commands.flow.bootstrap"):
            with patch("hof.flows.state.execution_store", mock_store):
                result = runner.invoke(app, ["list"])
        assert result.exit_code == 0

    def test_list_shows_executions(self, runner, no_api_client, sample_execution_dict):
        mock_store = MagicMock()
        ex = FlowExecution(**{
            k: v for k, v in sample_execution_dict.items()
            if k in ("id", "flow_name", "status", "input_data", "output_data", "error")
        })
        mock_store.list_executions.return_value = [ex]
        with patch("hof.cli.commands.flow.bootstrap"):
            with patch("hof.flows.state.execution_store", mock_store):
                result = runner.invoke(app, ["list"])
        assert result.exit_code == 0

    def test_list_via_api_client(self, runner, sample_execution_dict):
        mock_client = MagicMock()
        mock_client.list_executions.return_value = [sample_execution_dict]
        with patch("hof.cli.api_client.get_client", return_value=mock_client):
            result = runner.invoke(app, ["list", "test_flow"])
        assert result.exit_code == 0


class TestFlowGet:
    def test_get_missing_execution_exits(self, runner, no_api_client):
        mock_store = MagicMock()
        mock_store.get_execution.return_value = None
        with patch("hof.cli.commands.flow.bootstrap"):
            with patch("hof.flows.state.execution_store", mock_store):
                result = runner.invoke(app, ["get", "nonexistent-id"])
        assert result.exit_code != 0

    def test_get_existing_execution(self, runner, no_api_client, sample_execution_dict):
        ex = FlowExecution(
            id=sample_execution_dict["id"],
            flow_name=sample_execution_dict["flow_name"],
            status=sample_execution_dict["status"],
        )
        mock_store = MagicMock()
        mock_store.get_execution.return_value = ex
        with patch("hof.cli.commands.flow.bootstrap"):
            with patch("hof.flows.state.execution_store", mock_store):
                result = runner.invoke(app, ["get", ex.id])
        assert result.exit_code == 0
        assert ex.id[:8] in result.output or ex.flow_name in result.output

    def test_get_via_api_client(self, runner, sample_execution_dict):
        mock_client = MagicMock()
        mock_client.get_execution.return_value = sample_execution_dict
        with patch("hof.cli.api_client.get_client", return_value=mock_client):
            result = runner.invoke(app, ["get", "abcdef12"])
        assert result.exit_code == 0

    def test_get_with_nodes_flag(self, runner, no_api_client):
        ex = FlowExecution(id="exec-001", flow_name="f", status="completed")
        ex.set_node_state("step_a", status="completed", duration_ms=100)
        mock_store = MagicMock()
        mock_store.get_execution.return_value = ex
        with patch("hof.cli.commands.flow.bootstrap"):
            with patch("hof.flows.state.execution_store", mock_store):
                result = runner.invoke(app, ["get", "exec-001", "--nodes"])
        assert result.exit_code == 0
        assert "step_a" in result.output
