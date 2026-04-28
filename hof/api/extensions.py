"""User-defined router registration.

Starters and customer apps can register additional FastAPI routers
that are mounted into the auto-generated app alongside the built-in
``/api/tables``, ``/api/functions``, ``/api/flows``, … routes.

This is the official escape hatch for the (rare) cases that don't fit
the ``@function`` POST-RPC shape — typically:

* Cross-host HTTP/WebSocket proxies (e.g. forwarding ``/api/mail/*``
  to a sister sidecar that ships its own routes).
* Compatibility shims for embedded third-party React packages whose
  bundled HTTP client expects a specific URL shape.
* Public webhook receivers that must accept arbitrary verbs / content
  types without a JSON body wrapper.

Typical usage in a starter (call it from any module that's reachable
via the discovery sweep — most naturally from a ``functions/*.py``
shim, since those are imported during ``discover_all``)::

    # functions/my_proxy.py
    from fastapi import APIRouter
    from hof.api.extensions import register_router

    router = APIRouter()

    @router.api_route("/api/mail/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def proxy_mail(path: str, request):
        ...

    register_router(router)

The registered router is mounted **after** all built-in API routers
and **before** the user-pages catch-all, so any prefix beginning with
``/api/`` is reachable from the data-app frontend without colliding
with the SPA shell.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger("hof.api.extensions")


@dataclass(frozen=True)
class RegisteredRouter:
    """A router queued for inclusion in the auto-generated FastAPI app."""

    router: APIRouter
    prefix: str = ""
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class RegisteredMiddleware:
    """A Starlette/FastAPI middleware queued for inclusion."""

    middleware_class: type
    options: dict[str, Any]


_REGISTERED: list[RegisteredRouter] = []


def register_router(
    router: APIRouter,
    *,
    prefix: str = "",
    tags: Iterable[str] | None = None,
) -> None:
    """Mount an additional FastAPI router into the auto-generated app.

    Call at module import time from a starter; the router is included
    after the built-in routers and before the user-pages catch-all.

    Multiple calls with overlapping prefixes are honored in registration
    order — first match wins (FastAPI's default behavior).
    """
    entry = RegisteredRouter(
        router=router,
        prefix=prefix,
        tags=tuple(tags or ()),
    )
    _REGISTERED.append(entry)
    logger.debug(
        "Registered user router: prefix=%r tags=%r routes=%d",
        prefix,
        entry.tags,
        len(router.routes),
    )


def registered_routers() -> tuple[RegisteredRouter, ...]:
    """Return the currently-registered routers (read-only snapshot)."""
    return tuple(_REGISTERED)


def clear_registered_routers() -> None:
    """Reset the registry (used by tests; not normally called in prod)."""
    _REGISTERED.clear()


_REGISTERED_MIDDLEWARE: list[RegisteredMiddleware] = []


def register_middleware(middleware_class: type, **options: Any) -> None:
    """Queue a Starlette/FastAPI middleware for the auto-generated app.

    Mirrors ``register_router``: call at module import time from a
    starter (typically a ``functions/*.py`` shim) and the middleware
    will be installed on the FastAPI app right after CORS, before any
    route handlers run.

    Order: middlewares are installed in registration order, but
    Starlette executes them in reverse — i.e. the *first* registered
    middleware is the *outermost* layer (runs first on the way in,
    last on the way out). This matches FastAPI's documented behaviour
    for ``app.add_middleware``.
    """
    entry = RegisteredMiddleware(middleware_class=middleware_class, options=options)
    _REGISTERED_MIDDLEWARE.append(entry)
    logger.debug("Registered middleware: %s options=%r", middleware_class.__name__, options)


def registered_middlewares() -> tuple[RegisteredMiddleware, ...]:
    """Read-only snapshot of registered middlewares, in registration order."""
    return tuple(_REGISTERED_MIDDLEWARE)


def clear_registered_middlewares() -> None:
    """Reset the middleware registry (used by tests)."""
    _REGISTERED_MIDDLEWARE.clear()


__all__ = [
    "RegisteredRouter",
    "RegisteredMiddleware",
    "register_router",
    "registered_routers",
    "clear_registered_routers",
    "register_middleware",
    "registered_middlewares",
    "clear_registered_middlewares",
]
