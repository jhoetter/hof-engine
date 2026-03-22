"""Tests for hof.cli.commands.fn."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from hof.cli.commands.fn import app
from hof.functions import function


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def registered_fn():
    """Register a simple test function in the registry."""

    @function(tags=["test"])
    def greet(name: str = "World") -> dict:
        """Greet someone."""
        return {"message": f"Hello, {name}!"}

    return greet


@pytest.fixture
def no_api_client():
    """Ensure no API client is available (server not running)."""
    with patch("hof.cli.api_client.get_client", return_value=None):
        yield


class TestFnList:
    def test_list_shows_registered_functions(self, runner, registered_fn, no_api_client):
        with patch("hof.cli.commands.fn.bootstrap"):
            result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "greet" in result.output

    def test_list_shows_description(self, runner, registered_fn, no_api_client):
        with patch("hof.cli.commands.fn.bootstrap"):
            result = runner.invoke(app, ["list"])
        assert "Greet someone" in result.output

    def test_list_shows_tags(self, runner, registered_fn, no_api_client):
        with patch("hof.cli.commands.fn.bootstrap"):
            result = runner.invoke(app, ["list"])
        assert "test" in result.output

    def test_list_empty_registry(self, runner, no_api_client):
        with patch("hof.cli.commands.fn.bootstrap"):
            result = runner.invoke(app, ["list"])
        assert result.exit_code == 0

    def test_list_via_api_client(self, runner):
        mock_client = MagicMock()
        mock_client.list_functions.return_value = [
            {"name": "api_fn", "description": "API fn", "tags": [], "is_async": False}
        ]
        with patch("hof.cli.api_client.get_client", return_value=mock_client):
            result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "api_fn" in result.output


class TestFnSchema:
    def test_schema_shows_json(self, runner, registered_fn, no_api_client):
        with patch("hof.cli.commands.fn.bootstrap"):
            result = runner.invoke(app, ["schema", "greet"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "greet"

    def test_schema_missing_function(self, runner, no_api_client):
        with patch("hof.cli.commands.fn.bootstrap"):
            result = runner.invoke(app, ["schema", "nonexistent"])
        assert result.exit_code != 0

    def test_schema_via_api_client(self, runner):
        mock_client = MagicMock()
        mock_client.function_schema.return_value = {"name": "remote_fn", "parameters": []}
        with patch("hof.cli.api_client.get_client", return_value=mock_client):
            result = runner.invoke(app, ["schema", "remote_fn"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "remote_fn"


class TestFnCall:
    def test_call_function_no_args(self, runner, registered_fn, no_api_client):
        with patch("hof.cli.commands.fn.bootstrap"):
            result = runner.invoke(app, ["greet"])
        assert result.exit_code == 0
        assert "message" in result.output
        assert "Hello, World!" in result.output

    def test_call_function_with_json_args(self, runner, registered_fn, no_api_client):
        with patch("hof.cli.commands.fn.bootstrap"):
            result = runner.invoke(app, ["greet", "--json", '{"name": "Alice"}'])
        assert result.exit_code == 0
        assert "Hello, Alice!" in result.output

    def test_call_function_format_json(self, runner, registered_fn, no_api_client):
        with patch("hof.cli.commands.fn.bootstrap"):
            result = runner.invoke(app, ["greet", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["message"] == "Hello, World!"

    def test_call_missing_function_exits(self, runner, no_api_client):
        with patch("hof.cli.commands.fn.bootstrap"):
            result = runner.invoke(app, ["nonexistent_fn"])
        assert result.exit_code != 0

    def test_call_via_api_client(self, runner):
        mock_client = MagicMock()
        mock_client.call_function.return_value = {"result": {"message": "Hello from API"}}
        with patch("hof.cli.api_client.get_client", return_value=mock_client):
            result = runner.invoke(app, ["greet"])
        assert result.exit_code == 0
        assert "Hello from API" in result.output

    def test_call_async_function(self, runner, no_api_client):
        @function
        async def async_greet(name: str = "Async") -> dict:
            return {"message": f"Hello async, {name}!"}

        with patch("hof.cli.commands.fn.bootstrap"):
            result = runner.invoke(app, ["async_greet"])
        assert result.exit_code == 0
        assert "async" in result.output.lower()

    def test_call_async_function_format_json(self, runner, no_api_client):
        @function
        async def async_greet(name: str = "Async") -> dict:
            return {"message": f"Hello async, {name}!"}

        with patch("hof.cli.commands.fn.bootstrap"):
            result = runner.invoke(app, ["async_greet", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "async" in data["message"].lower()
