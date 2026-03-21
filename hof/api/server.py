"""FastAPI application factory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from hof.app import HofApp, set_global_app
from hof.config import find_project_root, load_config
from hof.core.discovery import discover_all
from hof.logging_config import configure_logging

ADMIN_UI_DIR = Path(__file__).resolve().parent.parent / "ui" / "admin"
ADMIN_VITE_PORT = int(os.environ.get("HOF_ADMIN_VITE_PORT", "0"))
USER_VITE_PORT = int(os.environ.get("HOF_USER_VITE_PORT", "0"))


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    This is the entry point for uvicorn: `uvicorn hof.api.server:create_app --factory`
    """
    env_root = os.environ.get("HOF_PROJECT_ROOT")
    if env_root:
        project_root = Path(env_root).resolve()
    else:
        found = find_project_root()
        project_root = found if found is not None else Path.cwd().resolve()

    config = load_config(project_root)

    configure_logging(debug=config.debug, app_name=config.app_name)

    # Create and activate the HofApp context for this process
    hof_app = HofApp(config=config)
    set_global_app(hof_app)

    # Discover user modules — decorators register into hof_app.registry via
    # the global registry singleton (backward compat) and into the module-level
    # globals for engine/config.
    discover_all(project_root, config.discovery_dirs)

    # Initialize engines (both sync and async)
    from hof.db.engine import init_engine

    init_engine(
        config.database_url,
        pool_size=config.database_pool_size,
        echo=config.database_echo,
    )
    hof_app.init_db()

    app = FastAPI(
        title=f"{config.app_name} API",
        description=f"Auto-generated API for {config.app_name} (powered by hof-engine)",
        version="0.1.0",
        docs_url="/api/swagger",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
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
    from hof.api.routes.sse import router as sse_router
    from hof.api.routes.tables import router as tables_router
    from hof.api.routes.ws import router as ws_router
    from hof.docs.router import router as docs_router

    setup_auth(app, config)

    app.include_router(tables_router, prefix="/api/tables", tags=["tables"])
    app.include_router(functions_router, prefix="/api/functions", tags=["functions"])
    app.include_router(flows_router, prefix="/api/flows", tags=["flows"])
    app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
    app.include_router(sse_router, tags=["sse"])
    app.include_router(ws_router, tags=["realtime"])
    app.include_router(docs_router, prefix="/api/docs", tags=["docs"])

    @app.get("/api/health")
    async def health():
        from hof.core.registry import registry

        return {
            "status": "ok",
            "app": config.app_name,
            "registry": registry.summary(),
        }

    _mount_user_ui(app, project_root, config)
    _mount_admin_ui(app)
    _mount_user_pages(app, project_root, config)

    return app


def _mount_user_ui(app: FastAPI, project_root: Path, config: Any) -> None:
    """Serve user-defined React components — proxy to Vite in dev, static in prod."""
    user_ui_dist = project_root / config.ui_dir / "dist"

    if USER_VITE_PORT:
        import re as _re

        _proxy = httpx.AsyncClient(
            base_url=f"http://localhost:{USER_VITE_PORT}",
        )

        _rewrite_re = _re.compile(
            r"(?P<prefix>"
            r'(?:src|href)\s*=\s*["\']'  # HTML attributes
            r'|from\s+["\']'  # ES import … from "/…"
            r'|import\s+["\']'  # ES import "/…" (side-effect)
            r")"
            r"(?P<path>/(?:@|_|node_modules/|components/|src/))"
        )

        def _rewrite_paths(text: str) -> str:
            return _rewrite_re.sub(r"\g<prefix>/user-ui\g<path>", text)

        @app.api_route("/user-ui/{path:path}", methods=["GET", "HEAD"])
        async def user_ui_proxy(request: Request, path: str = "") -> Response:
            url = f"/{path}" if path else "/"
            if request.query_params:
                url += f"?{request.query_params}"
            fwd_headers = {
                k: v for k, v in request.headers.items() if k.lower() not in ("host", "connection")
            }
            try:
                proxy_resp = await _proxy.get(url, headers=fwd_headers)
                content = proxy_resp.content
                ct = proxy_resp.headers.get("content-type", "")

                if any(t in ct for t in ("text/html", "text/javascript", "application/javascript")):
                    text = content.decode("utf-8", errors="replace")
                    text = _rewrite_paths(text)
                    content = text.encode("utf-8")

                return Response(
                    content=content,
                    status_code=proxy_resp.status_code,
                    media_type=ct,
                )
            except httpx.ConnectError:
                return Response(content="User UI not ready", status_code=503)

    elif user_ui_dist.is_dir():
        app.mount(
            "/user-ui",
            StaticFiles(directory=str(user_ui_dist)),
            name="user-ui",
        )


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
        _admin_static = StaticFiles(directory=str(admin_dist))
        _admin_index = admin_dist / "index.html"

        @app.api_route("/admin/{path:path}", methods=["GET", "HEAD"])
        @app.api_route("/admin", methods=["GET", "HEAD"])
        async def admin_static(request: Request, path: str = "") -> Response:
            last_segment = path.rsplit("/", 1)[-1] if path else ""
            if "." in last_segment or path.startswith("assets/"):
                scope = request.scope.copy()
                scope["path"] = f"/{path}"
                try:
                    return await _admin_static.get_response(path, scope)
                except Exception:
                    pass
            return HTMLResponse(content=_admin_index.read_text())

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


def _mount_user_pages(app: FastAPI, project_root: Path, config: Any) -> None:
    """Serve user-defined pages at the root — proxy to Vite in dev, static in prod.

    Pages live in ui/pages/*.tsx and are rendered as a standalone SPA at /.
    This catch-all is registered last so /api/*, /admin/*, /user-ui/* take priority.
    """
    user_ui_dist = project_root / config.ui_dir / "dist"

    if USER_VITE_PORT:
        _proxy = httpx.AsyncClient(
            base_url=f"http://localhost:{USER_VITE_PORT}",
        )

        @app.api_route("/{path:path}", methods=["GET", "HEAD"])
        @app.api_route("/", methods=["GET", "HEAD"])
        async def pages_proxy(request: Request, path: str = "") -> Response:
            """Proxy page requests to the user Vite dev server.

            Asset requests (containing a dot in the last segment) are forwarded
            as-is. All other paths get the _pages.html SPA shell so client-side
            routing can take over.
            """
            last_segment = path.rsplit("/", 1)[-1] if path else ""
            is_asset = (
                "." in last_segment
                or path.startswith("@")
                or path.startswith("node_modules/")
                or path.startswith("_hof_")
            )

            if is_asset:
                url = f"/{path}"
            else:
                url = "/_pages.html"

            if request.query_params:
                url += f"?{request.query_params}"

            fwd_headers = {
                k: v for k, v in request.headers.items() if k.lower() not in ("host", "connection")
            }
            try:
                proxy_resp = await _proxy.get(url, headers=fwd_headers)
                return Response(
                    content=proxy_resp.content,
                    status_code=proxy_resp.status_code,
                    media_type=proxy_resp.headers.get("content-type"),
                )
            except httpx.ConnectError:
                return Response(content="App not ready", status_code=503)

    elif user_ui_dist.is_dir():
        _static = StaticFiles(directory=str(user_ui_dist))
        _pages_html = user_ui_dist / "_pages.html"
        _index_html = user_ui_dist / "index.html"
        _spa_shell = _pages_html if _pages_html.exists() else _index_html

        @app.api_route("/{path:path}", methods=["GET", "HEAD"])
        @app.api_route("/", methods=["GET", "HEAD"])
        async def pages_static(request: Request, path: str = "") -> Response:
            """Serve built assets directly; non-asset paths get the SPA shell."""
            last_segment = path.rsplit("/", 1)[-1] if path else ""
            is_asset = "." in last_segment or path.startswith("assets/")

            if is_asset:
                scope = request.scope.copy()
                scope["path"] = f"/{path}"
                try:
                    resp = await _static.get_response(path, scope)
                    return resp
                except Exception:
                    return Response(content="Not found", status_code=404)

            return HTMLResponse(content=_spa_shell.read_text())

    else:

        @app.api_route("/{path:path}", methods=["GET", "HEAD"])
        @app.api_route("/", methods=["GET", "HEAD"])
        async def pages_not_built(request: Request, path: str = "") -> Response:
            if path.startswith("api/"):
                return Response(
                    content='{"detail":"Not Found"}', status_code=404, media_type="application/json"
                )
            return HTMLResponse(
                f"<!DOCTYPE html><html><head><title>{config.app_name}</title>"
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                "<style>"
                "body{font-family:system-ui,sans-serif;display:flex;align-items:center;"
                "justify-content:center;min-height:100vh;margin:0;background:#fafafa;"
                "color:#37352f}"
                ".c{text-align:center;max-width:480px;padding:2rem}"
                "h1{font-size:1.5rem;font-weight:600;margin:0 0 .5rem}"
                "p{color:#787774;line-height:1.6;margin:0 0 1.5rem}"
                "code{background:#f0f0f0;padding:2px 6px;border-radius:4px;font-size:.85em}"
                "a{color:#2383e2;text-decoration:none}"
                "</style></head><body><div class='c'>"
                f"<h1>{config.app_name}</h1>"
                "<p>The app is running but the UI has not been built yet. "
                "Add pages to <code>ui/pages/</code> and redeploy, "
                "or visit <a href='/admin'>/admin</a> or "
                "<a href='/api/swagger'>/api/swagger</a>.</p>"
                "</div></body></html>",
                status_code=200,
            )
