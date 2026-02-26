"""CLI command modules."""

from __future__ import annotations

from pathlib import Path


def bootstrap(project_root: Path | None = None) -> None:
    """Discover user code and initialize the database engine.

    Call this once at the start of any CLI command that needs
    access to registered tables, functions, or flows.
    """
    from hof.config import load_config
    from hof.core.discovery import discover_all
    from hof.db.engine import init_engine

    root = project_root or Path.cwd()
    config = load_config(root)
    discover_all(root, config.discovery_dirs)
    init_engine(
        config.database_url,
        pool_size=config.database_pool_size,
        echo=config.database_echo,
    )
