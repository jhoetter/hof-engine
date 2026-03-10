"""HofApp: application context object.

Replaces scattered module-level globals with a single, explicit context that
owns config, registry, database engine, and LLM provider.  Multiple HofApp
instances can coexist in one process (e.g. for testing), and the "current"
app is tracked via a context variable for async-safe access.

Backward compatibility: the existing module-level helpers (get_config,
get_engine, get_session, registry, …) continue to work by delegating to the
active HofApp context.
"""

from __future__ import annotations

import threading
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hof.config import Config
    from hof.core.registry import _Registry

# ---------------------------------------------------------------------------
# Active-app context variable (async-safe)
# ---------------------------------------------------------------------------

_current_app: ContextVar[HofApp | None] = ContextVar("_current_app", default=None)
_global_app: HofApp | None = None
_global_lock = threading.Lock()


class HofApp:
    """Application context: owns config, registry, engine, and LLM provider.

    Typical usage (framework internals):
        app = HofApp.create(project_root=Path.cwd())
        with app.activate():
            ...  # all framework calls use this app

    For testing, create a fresh app per test to avoid global state leakage:
        app = HofApp(config=Config(database_url="sqlite:///:memory:"))
        with app.activate():
            ...
    """

    def __init__(self, config: Config | None = None) -> None:
        from hof.config import Config as _Config
        from hof.core.registry import _Registry

        self.config: Config = config or _Config()
        self.registry: _Registry = _Registry()
        self._engine: Any = None
        self._session_factory: Any = None
        self._async_engine: Any = None
        self._async_session_factory: Any = None
        self._llm_provider: Any = None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, project_root: Path | None = None) -> HofApp:
        """Load config from disk and create a fully-initialized app."""
        from hof.config import load_config

        root = project_root or Path.cwd()
        config = load_config(root)
        app = cls(config=config)
        return app

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------

    def init_db(self) -> None:
        """Initialize sync and async database engines from the app config."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from hof.db.engine import _make_async_url

        self._engine = create_engine(
            self.config.database_url,
            pool_size=self.config.database_pool_size,
            pool_pre_ping=True,
            echo=self.config.database_echo,
        )
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)

        async_url = _make_async_url(self.config.database_url)
        if "sqlite" not in async_url:
            from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

            self._async_engine = create_async_engine(
                async_url,
                pool_size=self.config.database_pool_size,
                pool_pre_ping=True,
                echo=self.config.database_echo,
            )
            self._async_session_factory = async_sessionmaker(
                bind=self._async_engine,
                expire_on_commit=False,
                class_=AsyncSession,
            )

    # ------------------------------------------------------------------
    # LLM provider
    # ------------------------------------------------------------------

    def init_llm(self) -> None:
        """Configure the LLM provider from the app config."""
        from hof.llm.provider import _build_provider

        self._llm_provider = _build_provider(self.config)

    def get_llm_provider(self) -> Any:
        if self._llm_provider is None:
            self.init_llm()
        return self._llm_provider

    # ------------------------------------------------------------------
    # Context manager — makes this app the "current" one
    # ------------------------------------------------------------------

    def activate(self) -> _AppContextManager:
        """Return a context manager that sets this app as the current one."""
        return _AppContextManager(self)

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<HofApp app_name={self.config.app_name!r}>"


class _AppContextManager:
    def __init__(self, app: HofApp) -> None:
        self._app = app
        self._token: Any = None

    def __enter__(self) -> HofApp:
        self._token = _current_app.set(self._app)
        return self._app

    def __exit__(self, *_: Any) -> None:
        _current_app.reset(self._token)


# ---------------------------------------------------------------------------
# Global app helpers
# ---------------------------------------------------------------------------


def set_global_app(app: HofApp) -> None:
    """Set the process-wide default app (used by the server and CLI)."""
    global _global_app
    with _global_lock:
        _global_app = app


def get_current_app() -> HofApp | None:
    """Return the app bound to the current async context, or the global default."""
    ctx_app = _current_app.get()
    if ctx_app is not None:
        return ctx_app
    return _global_app


def require_app() -> HofApp:
    """Return the current app, raising if none is active."""
    app = get_current_app()
    if app is None:
        raise RuntimeError(
            "No HofApp is active. Call HofApp.create() and use app.activate() "
            "or set_global_app() before using framework features."
        )
    return app
