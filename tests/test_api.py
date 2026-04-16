"""Tests for the FastAPI application — health, functions, flows, and admin routes."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hof.agent.policy import BUILTIN_AGENT_TOOL_NAMES, AgentPolicy
from hof.agent.sandbox.config import SandboxConfig
from hof.agent.sandbox.constants import HOF_BUILTIN_TERMINAL_EXEC
from hof.api.auth import verify_auth
from hof.core.registry import registry
from hof.flows.flow import Flow
from hof.functions import function

# ---------------------------------------------------------------------------
# Minimal app factory for tests (no DB, no Vite, no discovery)
# ---------------------------------------------------------------------------


def _make_test_app() -> FastAPI:
    """Create a minimal FastAPI app with all routes but no external dependencies."""
    app = FastAPI()

    from hof.api.routes.admin import router as admin_router
    from hof.api.routes.agent import router as agent_router
    from hof.api.routes.flows import router as flows_router
    from hof.api.routes.functions import router as functions_router
    from hof.api.routes.tables import router as tables_router

    app.include_router(tables_router, prefix="/api/tables", tags=["tables"])
    app.include_router(functions_router, prefix="/api/functions", tags=["functions"])
    app.include_router(flows_router, prefix="/api/flows", tags=["flows"])
    app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
    app.include_router(agent_router, prefix="/api/agent", tags=["agent"])

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "app": "test", "registry": registry.summary()}

    # Override auth to always pass in tests
    app.dependency_overrides[verify_auth] = lambda: "test-user"

    return app


@pytest.fixture
def client():
    app = _make_test_app()
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_health_includes_registry_summary(self, client):
        response = client.get("/api/health")
        data = response.json()
        assert "registry" in data
        assert "tables" in data["registry"]
        assert "functions" in data["registry"]


# ---------------------------------------------------------------------------
# Functions routes
# ---------------------------------------------------------------------------


class TestFunctionsRoutes:
    def test_list_functions_empty(self, client):
        response = client.get("/api/functions")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_functions_with_registered(self, client):
        @function
        def test_list_fn() -> dict:
            """A test function."""
            return {}

        response = client.get("/api/functions")
        assert response.status_code == 200
        names = [f["name"] for f in response.json()]
        assert "test_list_fn" in names

    def test_call_function_success(self, client):
        @function
        def add_numbers(a: int, b: int) -> dict:
            return {"sum": a + b}

        response = client.post("/api/functions/add_numbers", json={"a": 3, "b": 4})
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["sum"] == 7

    def test_call_function_not_found(self, client):
        response = client.post("/api/functions/nonexistent_fn", json={})
        assert response.status_code == 404

    def test_call_function_no_body(self, client):
        @function
        def no_args_fn() -> dict:
            return {"ok": True}

        response = client.post("/api/functions/no_args_fn")
        assert response.status_code == 200
        assert response.json()["result"]["ok"] is True

    def test_call_async_function(self, client):
        @function
        async def async_fn(x: int) -> dict:
            return {"x": x * 2}

        response = client.post("/api/functions/async_fn", json={"x": 5})
        assert response.status_code == 200
        assert response.json()["result"]["x"] == 10

    def test_stream_function_ndjson(self, client):
        def _stream_echo(msg: str):
            yield {"type": "run_start", "run_id": "r1"}
            yield {"type": "assistant_delta", "text": msg}
            yield {"type": "final", "reply": msg, "tool_rounds_used": 0, "model": "test"}

        @function(stream=_stream_echo)
        def echo_stream(msg: str) -> dict:
            return {"reply": msg}

        response = client.post("/api/functions/echo_stream/stream", json={"msg": "hi"})
        assert response.status_code == 200
        assert response.headers.get("content-type", "").startswith("application/x-ndjson")
        lines = [ln for ln in response.text.strip().split("\n") if ln]
        assert len(lines) == 3
        import json as _json

        assert _json.loads(lines[0])["type"] == "run_start"
        assert _json.loads(lines[1]) == {"type": "assistant_delta", "text": "hi"}
        assert _json.loads(lines[2])["reply"] == "hi"

    def test_stream_function_not_found(self, client):
        response = client.post("/api/functions/missing/stream", json={})
        assert response.status_code == 404

    def test_stream_function_without_stream_fn(self, client):
        @function
        def no_stream() -> dict:
            return {}

        response = client.post("/api/functions/no_stream/stream", json={})
        assert response.status_code == 404

    def test_get_function_schema(self, client):
        @function
        def schema_fn(name: str, count: int = 1) -> dict:
            """Schema test function."""
            return {}

        response = client.get("/api/functions/schema_fn/schema")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "schema_fn"
        assert "parameters" in data

    def test_get_function_schema_not_found(self, client):
        response = client.get("/api/functions/missing_fn/schema")
        assert response.status_code == 404

    def test_call_function_returns_duration(self, client):
        @function
        def timed_fn() -> dict:
            return {}

        response = client.post("/api/functions/timed_fn")
        assert response.status_code == 200
        assert "duration_ms" in response.json()

    def test_call_function_with_var_keyword_accepts_extras(self, client):
        """Regression: ``**kwargs`` must not trigger ``422 Field required``.

        Previously the schema treated ``**kwargs`` as a required parameter,
        so every call like ``update_project(id, domain=...)`` failed before
        reaching the function body. Extras should instead pass through.
        """

        @function
        def update_thing(id: str, **kwargs) -> dict:
            return {"id": id, "extras": dict(kwargs)}

        response = client.post(
            "/api/functions/update_thing",
            json={"id": "x", "domain": "acme.com", "dns_mode": "manual"},
        )
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["id"] == "x"
        assert result["extras"] == {"domain": "acme.com", "dns_mode": "manual"}

    def test_call_function_with_var_keyword_still_requires_named_params(self, client):
        """Named required params remain required even when ``**kwargs`` is present."""

        @function
        def needs_id(id: str, **kwargs) -> dict:
            return {"id": id}

        response = client.post(
            "/api/functions/needs_id",
            json={"domain": "acme.com"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Flows routes
# ---------------------------------------------------------------------------


class TestFlowsRoutes:
    def test_list_flows_empty(self, client):
        response = client.get("/api/flows")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_flows_with_registered(self, client):
        flow = Flow("api_test_flow")

        @flow.node
        def step() -> dict:
            return {}

        response = client.get("/api/flows")
        assert response.status_code == 200
        names = [f["name"] for f in response.json()]
        assert "api_test_flow" in names

    def test_get_flow_dag(self, client):
        flow = Flow("dag_test_flow")

        @flow.node
        def node_a() -> dict:
            return {}

        @flow.node(depends_on=[node_a])
        def node_b() -> dict:
            return {}

        response = client.get("/api/admin/flows/dag_test_flow/dag")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data

    def test_get_flow_dag_not_found(self, client):
        response = client.get("/api/admin/flows/nonexistent_flow/dag")
        assert response.status_code == 200
        data = response.json()
        assert "error" in data


# ---------------------------------------------------------------------------
# Agent routes
# ---------------------------------------------------------------------------


class TestAgentRoutes:
    def test_agent_tools_not_configured(self, client):
        with patch("hof.api.routes.agent.try_get_agent_policy", return_value=None):
            response = client.get("/api/agent/tools")
        assert response.status_code == 200
        data = response.json()
        assert data == {"configured": False, "tools": []}

    def test_agent_tools_configured(self, client):
        @function
        def agent_read_tool(x: int) -> dict:
            """Read-side tool."""
            return {}

        @function
        def agent_mut_tool() -> dict:
            """Mutation tool."""
            return {}

        importlib.reload(importlib.import_module("hof.agent.builtin_tools"))

        policy = AgentPolicy(
            allowlist_read=frozenset({"agent_read_tool"}),
            allowlist_mutation=frozenset({"agent_mut_tool"}),
            system_prompt_intro="test ",
        )
        with patch("hof.api.routes.agent.try_get_agent_policy", return_value=policy):
            response = client.get("/api/agent/tools")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        tools = data["tools"]
        names = {t["name"] for t in tools}
        assert names >= {"agent_mut_tool", "agent_read_tool"}
        assert BUILTIN_AGENT_TOOL_NAMES <= names
        by_name = {t["name"]: t for t in tools}
        assert by_name["agent_read_tool"]["mutation"] is False
        assert by_name["agent_mut_tool"]["mutation"] is True
        for bn in BUILTIN_AGENT_TOOL_NAMES:
            assert by_name[bn]["mutation"] is False
        read = by_name["agent_read_tool"]
        assert read["description"] == "Read-side tool."
        assert "tool_summary" in read
        assert "when_to_use" in read
        assert "when_not_to_use" in read
        assert "related_tools" in read
        assert read["related_tools"] == []
        assert read["parameters"]["type"] == "object"
        props = read["parameters"].get("properties") or {}
        assert "x" in props

    def test_agent_tools_terminal_only_lists_domain_not_terminal_transport(self, client):
        """Skills catalog keeps domain tools when the model only sees terminal exec."""

        @function
        def domain_list_rows() -> dict:
            """List rows."""
            return {}

        @function
        def domain_create_row() -> dict:
            """Create row."""
            return {}

        importlib.reload(importlib.import_module("hof.agent.builtin_tools"))

        policy = AgentPolicy(
            allowlist_read=frozenset({"domain_list_rows"}),
            allowlist_mutation=frozenset({"domain_create_row"}),
            system_prompt_intro="test ",
            sandbox=SandboxConfig(
                enabled=True,
                terminal_only_dispatch=True,
                builtins_when_terminal_only=frozenset({"hof_builtin_present_plan"}),
            ),
        )
        assert HOF_BUILTIN_TERMINAL_EXEC in policy.effective_allowlist()
        assert HOF_BUILTIN_TERMINAL_EXEC not in policy.skills_catalog_allowlist()
        with patch("hof.api.routes.agent.try_get_agent_policy", return_value=policy):
            response = client.get("/api/agent/tools")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        names = {t["name"] for t in data["tools"]}
        assert "domain_list_rows" in names
        assert "domain_create_row" in names
        assert HOF_BUILTIN_TERMINAL_EXEC not in names


# ---------------------------------------------------------------------------
# Admin overview
# ---------------------------------------------------------------------------


class TestAdminRoutes:
    def test_overview_endpoint(self, client):
        mock_store = MagicMock()
        mock_store.list_executions.return_value = []
        with patch("hof.api.routes.admin.execution_store", mock_store):
            response = client.get("/api/admin/overview")
        assert response.status_code == 200
        data = response.json()
        assert "registry" in data

    def test_pending_actions_empty(self, client):
        mock_store = MagicMock()
        mock_store.list_executions.return_value = []
        with patch("hof.api.routes.admin.execution_store", mock_store):
            response = client.get("/api/admin/pending-actions")
        assert response.status_code == 200
        assert response.json() == []


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestAuth:
    def test_unauthenticated_request_rejected(self):
        """Without the override, auth should reject requests when config is set."""
        from hof.api import auth as auth_module
        from hof.config import Config

        mock_config = MagicMock(spec=Config)
        mock_config.admin_username = "admin"
        mock_config.admin_password = "secret"
        mock_config.api_key = None

        original_config = auth_module._config
        auth_module._config = mock_config

        app = _make_test_app()
        # Remove the override to test real auth
        app.dependency_overrides.clear()

        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get("/api/functions")
            assert response.status_code == 401
        finally:
            auth_module._config = original_config

    def test_no_config_allows_anonymous(self):
        """When no config is set, auth returns 'anonymous'."""
        from hof.api import auth as auth_module

        original_config = auth_module._config
        auth_module._config = None

        app = _make_test_app()
        app.dependency_overrides.clear()

        try:
            with TestClient(app) as c:
                response = c.get("/api/functions")
            assert response.status_code == 200
        finally:
            auth_module._config = original_config
