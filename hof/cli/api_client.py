"""Lightweight HTTP client for CLI → API server delegation.

When `hof dev` is running, CLI commands delegate to the API so that
execution state, the admin UI, and Celery workers all share the same process.
Falls back to None when the server is unreachable.
"""

from __future__ import annotations

from typing import Any

import httpx


def get_client(port: int = 8000) -> _ApiClient | None:
    """Return an API client if the hof server is reachable, else None."""
    base = f"http://localhost:{port}"
    try:
        r = httpx.get(f"{base}/api/health", timeout=2)
        if r.status_code == 200:
            return _ApiClient(base)
    except httpx.ConnectError:
        pass
    return None


class _ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base = base_url
        self._auth: tuple[str, str] | None = None
        self._load_auth()

    def _load_auth(self) -> None:
        try:
            from hof.config import get_config

            cfg = get_config()
            if cfg.admin_username and cfg.admin_password:
                self._auth = (cfg.admin_username, cfg.admin_password)
        except Exception:
            pass

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._auth:
            kwargs.setdefault("auth", self._auth)
        return httpx.request(method, f"{self.base}{path}", timeout=300, **kwargs)

    def call_function(self, name: str, body: dict | None = None) -> dict:
        r = self._request("POST", f"/api/functions/{name}", json=body or {})
        r.raise_for_status()
        return r.json()

    def list_functions(self) -> list[dict]:
        r = self._request("GET", "/api/functions")
        r.raise_for_status()
        return r.json()

    def function_schema(self, name: str) -> dict:
        r = self._request("GET", f"/api/functions/{name}/schema")
        r.raise_for_status()
        return r.json()

    def run_flow(self, name: str, input_data: dict | None = None) -> dict:
        r = self._request("POST", f"/api/flows/{name}/run", json=input_data or {})
        r.raise_for_status()
        return r.json()

    def list_flows(self) -> list[dict]:
        r = self._request("GET", "/api/flows")
        r.raise_for_status()
        return r.json()

    def list_executions(
        self, flow_name: str, status: str | None = None, limit: int = 20
    ) -> list[dict]:
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        r = self._request("GET", f"/api/flows/{flow_name}/executions", params=params)
        r.raise_for_status()
        return r.json()

    def get_execution(self, execution_id: str) -> dict:
        r = self._request("GET", f"/api/flows/executions/{execution_id}")
        r.raise_for_status()
        return r.json()
