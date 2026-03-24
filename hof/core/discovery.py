"""Auto-discovery of user-defined components.

Scans conventional directories (tables/, functions/, flows/, cron/) and imports
all Python modules found there. The decorators in those modules handle
registration into the central registry.
"""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path

logger = logging.getLogger("hof.discovery")

DEFAULT_DIRS = {
    "tables": "tables",
    "functions": "functions",
    "flows": "flows",
    "cron": "cron",
}


def discover_all(project_root: Path, dir_overrides: dict[str, str] | None = None) -> None:
    """Import all user modules from conventional directories.

    This triggers decorator-based registration into the global registry.
    """
    dirs = {**DEFAULT_DIRS, **(dir_overrides or {})}

    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    for category, dirname in dirs.items():
        target = project_root / dirname
        if not target.is_dir():
            logger.debug("Skipping %s: directory %s not found", category, target)
            continue
        _import_directory(target, dirname)

    # Re-register after app code so ``registry.clear()`` in tests still repopulates builtins.
    importlib.reload(importlib.import_module("hof.agent.builtin_tools"))


def _import_directory(directory: Path, package_prefix: str) -> None:
    """Recursively import all .py files in a directory."""
    for py_file in sorted(directory.rglob("*.py")):
        if py_file.name.startswith("_"):
            continue

        relative = py_file.relative_to(directory.parent)
        module_name = str(relative.with_suffix("")).replace("/", ".").replace("\\", ".")

        try:
            importlib.import_module(module_name)
            logger.debug("Discovered: %s", module_name)
        except Exception:
            logger.exception("Failed to import %s", module_name)
