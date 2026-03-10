"""Tests for the FastAPI application — health, functions, flows, and admin routes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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
    from hof.api.routes.flows import router as flows_router
    from hof.api.routes.functions import router as functions_router
    from hof.api.routes.tables import router as tables_router

    app.include_router(tables_router, prefix="/api/tables", tags=["tables"])
    app.include_router(functions_router, prefix="/api/functions", tags=["functions"])
    app.include_router(flows_router, prefix="/api/flows", tags=["flows"])
    app.include_router(admin_router, prefix="/api/admin", tags=["admin"])

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
