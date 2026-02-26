"""FastAPI application factory."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from hof.config import load_config
from hof.core.discovery import discover_all

ADMIN_UI_DIR = Path(__file__).resolve().parent.parent / "ui" / "admin"
ADMIN_VITE_PORT = int(os.environ.get("HOF_ADMIN_VITE_PORT", "0"))


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    This is the entry point for uvicorn: `uvicorn hof.api.server:create_app --factory`
    """
    project_root = Path.cwd()
    config = load_config(project_root)
    discover_all(project_root, config.discovery_dirs)

    app = FastAPI(
        title=f"{config.app_name} API",
        description=f"Auto-generated API for {config.app_name} (powered by hof-engine)",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from hof.api.auth import setup_auth
    from hof.api.routes.admin import router as admin_router
    from hof.api.routes.flows import router as flows_router
    from hof.api.routes.functions import router as functions_router
    from hof.api.routes.tables import router as tables_router

    setup_auth(app, config)

    app.include_router(tables_router, prefix="/api/tables", tags=["tables"])
    app.include_router(functions_router, prefix="/api/functions", tags=["functions"])
    app.include_router(flows_router, prefix="/api/flows", tags=["flows"])
    app.include_router(admin_router, prefix="/api/admin", tags=["admin"])

    from hof.db.engine import init_engine

    init_engine(
        config.database_url,
        pool_size=config.database_pool_size,
        echo=config.database_echo,
    )

    @app.get("/api/health")
    async def health():
        from hof.core.registry import registry

        return {
            "status": "ok",
            "app": config.app_name,
            "registry": registry.summary(),
        }

    _mount_admin_ui(app)

    return app


def _mount_admin_ui(app: FastAPI) -> None:
    """Serve the admin UI — proxy to Vite in dev, static files in prod."""
    admin_dist = ADMIN_UI_DIR / "dist"

    if ADMIN_VITE_PORT:
        _proxy = httpx.AsyncClient(base_url=f"http://localhost:{ADMIN_VITE_PORT}")

        @app.api_route("/admin/{path:path}", methods=["GET", "HEAD"])
        @app.api_route("/admin", methods=["GET", "HEAD"])
        async def admin_proxy(request: Request, path: str = "") -> Response:
            url = f"/admin/{path}" if path else "/admin/"
            if request.query_params:
                url += f"?{request.query_params}"
            proxy_resp = await _proxy.get(url, headers=dict(request.headers))
            return Response(
                content=proxy_resp.content,
                status_code=proxy_resp.status_code,
                media_type=proxy_resp.headers.get("content-type"),
            )

    elif admin_dist.is_dir():
        app.mount(
            "/admin",
            StaticFiles(directory=str(admin_dist), html=True),
            name="admin-ui",
        )

    else:
        @app.get("/admin")
        @app.get("/admin/{path:path}")
        async def admin_not_built(path: str = "") -> HTMLResponse:
            return HTMLResponse(
                "<h3>Admin UI not built</h3>"
                "<p>Run <code>hof dev</code> to start with live reload, "
                "or build with <code>cd hof/ui/admin && npm run build</code>.</p>",
                status_code=503,
            )
